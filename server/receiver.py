import hmac
import json
import os
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import management
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "data"
os.umask(0o077)
TOKEN = (ROOT / "token").read_text().strip()
NAMES = {"pin_error": "第二层锁 PIN 输入错误", "armed": "已布防", "disarmed": "已撤防", "movement": "检测到机身移动",
         "plug": "USB 供电线已接入", "unplug": "USB 供电线已断开", "screen_off": "屏幕已关闭",
         "home": "Home 键按下", "back": "返回键按下", "menu": "菜单或最近任务键按下",
         "power": "电源键按下", "test": "测试通知", "offline": "心跳超时，受控端 已离线",
         "online": "心跳已恢复", "battery_low": "受控端电量过低", "battery_high": "受控端电量过高"}
LOCK = threading.Lock()
DB = sqlite3.connect(ROOT / "events.sqlite3", check_same_thread=False)
DB.executescript("""
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, kind TEXT, device_time INTEGER,
                                  received INTEGER, battery INTEGER, powered INTEGER);
CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY, last INTEGER, armed INTEGER, offline INTEGER);
INSERT OR IGNORE INTO state VALUES(1,0,0,0);
""")

def queue_desktop(event_id,kind):
    if sys.platform == "darwin":
        DB.execute("INSERT INTO desktop_alert(id,body) VALUES(?,?)",(event_id,NAMES[kind]))

def wake_desktop():
    if sys.platform != "darwin":
        return
    (ROOT/"desktop-wake").touch()
    subprocess.Popen(["/usr/bin/open","-gj",str(ROOT.parent/"AndroidRemoteGuardAlerts.app")],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def record_battery(msg, now):
    level = msg["battery"]
    if not 0 <= level <= 100:
        return None
    low,high,previous = DB.execute("SELECT low,high,zone FROM battery_settings WHERE id=1").fetchone()
    zone = "battery_low" if level <= low else "battery_high" if level >= high else "normal"
    DB.execute("INSERT OR REPLACE INTO latest VALUES(1,?,?)",(level,msg["powered"]))
    DB.execute("UPDATE battery_settings SET sampled=?, zone=? WHERE id=1",(now,zone))
    DB.execute("INSERT OR REPLACE INTO battery_history(sampled,level) VALUES(?,?)",(now,level))
    DB.execute("DELETE FROM battery_history WHERE sampled<?",(now-86400,))
    if zone == previous or zone == "normal":
        return None
    event_id = zone+"-"+str(time.time_ns())
    DB.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",(event_id,zone,msg["time"],now,level,msg["powered"]))
    queue_desktop(event_id,zone)
    return zone

def record(msg):
    received_ms = time.time_ns() // 1000000
    now = received_ms // 1000
    notices = []
    with LOCK, DB:
        _, armed, offline = DB.execute("SELECT last,armed,offline FROM state").fetchone()
        kind = msg["kind"]
        if kind in ("heartbeat","mode_status"):
            battery_notice = record_battery(msg,now)
            if battery_notice:
                notices.append(battery_notice)
            armed = int(msg["armed"])
            if isinstance(msg.get("mode_request"),str):
                DB.execute("DELETE FROM mode_command WHERE slot=1 AND request=?",(msg["mode_request"],))
        else:
            cur = DB.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)",
                             (msg["id"], kind, msg.get("occurred_ms",msg["time"]*1000)/1000,
                              received_ms/1000, msg["battery"], msg["powered"]))
            if cur.rowcount:
                notices.append(kind)
                if kind in ("armed","disarmed") and msg.get("server_mode") is True:
                    DB.execute("UPDATE log_item SET seen=1 WHERE id=?",(msg["id"],))
                else:
                    queue_desktop(msg["id"],kind)
                if kind in ("armed", "disarmed") and "mode_protocol" not in msg:
                    armed = int(kind == "armed")
        if offline and armed:
            event_id="online-"+str(time.time_ns())
            DB.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                       (event_id, "online", now, now, msg["battery"], msg["powered"]))
            queue_desktop(event_id,"online")
            notices.append("online")
        DB.execute("UPDATE state SET last=?,armed=?,offline=0", (now, armed))
    if notices:
        wake_desktop()
    management.changed(push=bool(notices))

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(8)
        self.request = self.server.tls.wrap_socket(self.request, server_side=True)
        super().setup()

    def finish(self):
        try:
            super().finish()
        finally:
            self.request.close()

    def log_request(self, code="-", size="-"):
        if code == 204:
            with LOCK:
                if self.server.last_peer == self.client_address[0]:
                    return
                self.server.last_peer = self.client_address[0]
        super().log_request(code, size)

    def do_POST(self):
        if self.path != "/v1/report":
            return self.send_error(404)
        if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer "+TOKEN):
            return self.send_error(403)
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 2048:
                raise ValueError()
            msg = json.loads(self.rfile.read(size))
            if (msg["kind"] not in set(NAMES).difference({"offline","online","battery_high","battery_low"}) | {"heartbeat","mode_status"}
                    or not isinstance(msg["id"], str) or not 1 <= len(msg["id"]) <= 64
                    or not all(type(msg[k]) is int for k in ("time","battery"))
                    or not all(type(msg[k]) is bool for k in ("powered","armed"))
                    or ("occurred_ms" in msg and (type(msg["occurred_ms"]) is not int
                        or not 0 < msg["occurred_ms"] < 4102444800000))):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            return self.send_error(400)
        record(msg)
        self.send_response(204)
        self.end_headers()

def watchdog():
    previous = time.time()
    observing_since = previous
    while True:
        time.sleep(10)
        current = time.time()
        if current-previous>60:
            observing_since=current
        previous=current
        with LOCK, DB:
            timeout = management.timeout_minutes(DB) * 60
            if current-observing_since<=timeout:
                continue
            now = int(time.time())
            cur = DB.execute("UPDATE state SET offline=1 WHERE armed=1 AND offline=0 AND last>0 AND last<?",
                             (now-timeout,))
            alert = bool(cur.rowcount)
            if alert:
                event_id="offline-"+str(time.time_ns())
                DB.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                           (event_id, "offline", now, now, -1, 0))
                queue_desktop(event_id,"offline")
        if alert:
            management.changed(push=True)
            wake_desktop()

if __name__ == "__main__":
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(ROOT / "cert.pem", ROOT / "key.pem")
    server = ThreadingHTTPServer(("", 18761), Handler)
    server.tls = ctx
    server.last_peer = None
    management.start(ROOT,DB,LOCK,NAMES)
    wake_desktop()
    threading.Thread(target=watchdog, daemon=True).start()
    server.serve_forever()
