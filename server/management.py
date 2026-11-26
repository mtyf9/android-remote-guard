import datetime
import html
import http.client
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

KEY_PATTERN = re.compile(r"sctp([0-9]+)t[A-Za-z0-9_-]+")
HOST = "127.0.0.1:18762"
from settings import ADB, SCRCPY, TOOLS, DEVICE, DEVICE_NAME, DEVICE_SERIAL
updates = threading.Condition()
revision = secrets.randbits(50)
push_wake = threading.Event()


def changed(push=False):
    global revision
    with updates:
        revision += 1
        updates.notify_all()
    if push:
        push_wake.set()


def timeout_minutes(db):
    return db.execute("SELECT minutes FROM heartbeat_settings WHERE id=1").fetchone()[0]


def battery_chart(samples, end):
    if not samples:
        return "<p>等待电量上报</p>"
    start = end - 86400
    left, right, top, bottom = 48, 740, 14, 160
    svg = ['<svg viewBox="0 0 790 194" style="display:block;width:100%;min-width:480px" role="img" aria-label="最近24小时电量曲线">']
    for level in (0, 25, 50, 75, 100):
        y = bottom - (bottom-top)*level/100
        svg.append(f'<path d="M{left} {y}H{right}" stroke="#dde5e4"/><text x="40" y="{y+4}" text-anchor="end" font-size="13">{level}%</text>')
    for hours in (0, 6, 12, 18, 24):
        x = left + (right-left)*hours/24
        label = time.strftime("%H:%M", time.localtime(start+hours*3600))
        svg.append(f'<text x="{x}" y="184" text-anchor="middle" font-size="13">{label}</text>')
    segments = []
    previous = None
    for sampled, level in samples:
        if previous is None or sampled-previous > 300:
            segments.append([])
        x = left + (right-left)*(sampled-start)/86400
        y = bottom - (bottom-top)*level/100
        segments[-1].append((x,y))
        previous = sampled
    for segment in segments:
        if len(segment)==1:
            x,y=segment[0]
            svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.5" fill="#166c67"/>')
        else:
            points=" ".join(f"{x:.2f},{y:.2f}" for x,y in segment)
            svg.append(f'<polyline points="{points}" fill="none" stroke="#166c67" stroke-width="2.5"/>')
    return "".join(svg)+"</svg>"


def stamp(value):
    if not value:
        return "—"
    dt=datetime.datetime.fromtimestamp(value)
    return dt.strftime("%m-%d %H:%M:%S")


def transmit(key, title, body):
    uid = KEY_PATTERN.fullmatch(key).group(1)
    connection = http.client.HTTPSConnection(uid + ".push.ft07.com", timeout=10)
    try:
        payload = json.dumps(dict(title=title, desp=body, tags="设备布防")).encode()
        connection.request("POST", "/send/" + key + ".send", payload, {"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return "HTTP " + str(response.status)
        result = json.loads(response.read(65536))
        code = result.get("code")
        if type(code) is int and code == 0:
            return ""
        return "接口错误 " + str(code if type(code) is int else "未知")
    finally:
        connection.close()


def start(root, db, lock, names):
    keyfile = root / "sc3.key"
    token_path = root / "desktop-token"
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32))
    desktop_token = token_path.read_text()
    wake_path = root / "desktop-wake"
    wake_path.touch()
    csrf = secrets.token_urlsafe(32)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS heartbeat_settings(id INTEGER PRIMARY KEY, minutes INTEGER NOT NULL);
    INSERT OR IGNORE INTO heartbeat_settings VALUES(1,10);
    CREATE TABLE IF NOT EXISTS push(id TEXT PRIMARY KEY, attempts INTEGER DEFAULT 0,
      due INTEGER DEFAULT 0, sent INTEGER DEFAULT 0, error TEXT DEFAULT '');
    CREATE TRIGGER IF NOT EXISTS queue_push AFTER INSERT ON events BEGIN
      INSERT INTO push(id) VALUES(NEW.id);
    END;
    CREATE TABLE IF NOT EXISTS latest(id INTEGER PRIMARY KEY, battery INTEGER, powered INTEGER);
    CREATE TABLE IF NOT EXISTS battery_settings(id INTEGER PRIMARY KEY,low INTEGER NOT NULL,high INTEGER NOT NULL,
      zone TEXT NOT NULL,sampled INTEGER NOT NULL);
    INSERT OR IGNORE INTO battery_settings VALUES(1,20,85,'normal',0);
    CREATE TABLE IF NOT EXISTS battery_history(sampled INTEGER PRIMARY KEY, level INTEGER NOT NULL);
    INSERT OR IGNORE INTO battery_history SELECT sampled,battery FROM latest JOIN battery_settings USING(id)
      WHERE sampled>=strftime('%s','now')-86400 AND battery BETWEEN 0 AND 100;
    CREATE TABLE IF NOT EXISTS mode_command(slot INTEGER PRIMARY KEY, request TEXT NOT NULL,
        armed INTEGER NOT NULL CHECK(armed IN (0,1)));
    CREATE TABLE IF NOT EXISTS log_item(seq INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT UNIQUE NOT NULL, seen INTEGER NOT NULL, cleared INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS desktop_alert(id TEXT PRIMARY KEY,body TEXT NOT NULL,submitted INTEGER NOT NULL DEFAULT 0);
    CREATE TRIGGER IF NOT EXISTS discard_desktop AFTER UPDATE OF seen,cleared ON log_item
      WHEN NEW.seen OR NEW.cleared BEGIN DELETE FROM desktop_alert WHERE id=NEW.id; END;
    INSERT INTO log_item(id,seen) SELECT id,1 FROM events e
      WHERE NOT EXISTS(SELECT 1 FROM log_item l WHERE l.id=e.id) ORDER BY rowid;
    CREATE TRIGGER IF NOT EXISTS new_log_item AFTER INSERT ON events BEGIN
        INSERT INTO log_item(id,seen) VALUES(NEW.id,0);
    END;
    CREATE TRIGGER IF NOT EXISTS ignore_cleared_alert BEFORE INSERT ON events
      WHEN EXISTS(SELECT 1 FROM log_item WHERE id=NEW.id AND cleared=1)
      BEGIN SELECT RAISE(IGNORE); END;
    """)

    def deliver():
        while True:
            push_wake.clear()
            if not keyfile.exists():
                push_wake.wait()
                continue
            try:
                key = keyfile.read_text().strip()
                with lock:
                    row = db.execute("""SELECT e.id,e.kind,e.device_time,e.received,e.battery,p.attempts
                      FROM push p JOIN events e USING(id) WHERE p.sent=0 AND p.due<=?
                      ORDER BY e.rowid LIMIT 1""", (int(time.time()),)).fetchone()
                    due = None if row else db.execute("SELECT min(due) FROM push WHERE sent=0").fetchone()[0]
                if not row:
                    push_wake.wait(None if due is None else max(0.1,due-time.time()))
                    continue
                event_id, kind, occurred, received, battery, attempts = row
                body = "发生于 " + stamp(occurred)
                if battery >= 0:
                    body += "，电量 " + str(battery) + "%"
                try:
                    error = transmit(key, DEVICE_NAME + " · " + names[kind], body)
                except Exception as exc:
                    error = type(exc).__name__
                now = int(time.time())
                with lock, db:
                    db.execute("UPDATE push SET sent=?,attempts=attempts+1,due=?,error=? WHERE id=?",
                               (0 if error else now, now + min(3600,30 * 2**min(attempts,7)),error,event_id))
                    if not error and db.execute("SELECT cleared FROM log_item WHERE id=?",(event_id,)).fetchone()==(1,):
                        db.execute("DELETE FROM push WHERE id=?",(event_id,))
                        db.execute("DELETE FROM events WHERE id=?",(event_id,))
                changed()
                time.sleep(1)
            except Exception as exc:
                print("Push worker:",type(exc).__name__,flush=True)
                time.sleep(5)

    mode_wake = threading.Event()

    def deliver_mode():
        while True:
            mode_wake.clear()
            with lock:
                cmd=db.execute("SELECT request,armed FROM mode_command WHERE slot=1").fetchone()
            if not cmd:
                mode_wake.wait()
                continue
            request,enabled=cmd
            try:
                subprocess.run([ADB,"connect",DEVICE],capture_output=True,timeout=10,check=True)
                target=[ADB,"-s",DEVICE,"shell"]
                model=subprocess.run(target+["getprop","ro.serialno"],capture_output=True,text=True,timeout=5,check=True)
                if model.stdout.strip()==DEVICE_SERIAL:
                    subprocess.run(target+["am","broadcast","--user","0","-n","local.devicewatch.guard/.Keys",
                        "-a","local.devicewatch.guard.SET_MODE","--es","request",request,
                        "--ez","armed","true" if enabled else "false"],capture_output=True,timeout=12,check=True)
            except (OSError, subprocess.SubprocessError):
                pass
            mode_wake.wait(30)

    remote_lock = threading.Lock()
    session = None
    remote_status = ""

    def connect_remote():
        nonlocal session,remote_status
        with remote_lock:
            if session and session.poll() is None:
                remote_status = "远控窗口已在服务端桌面运行"
                return
            try:
                subprocess.run([ADB,"connect",DEVICE],capture_output=True,timeout=12)
                result = subprocess.run([ADB,"-s",DEVICE,"shell","getprop","ro.serialno"],
                                        capture_output=True,text=True,timeout=6)
                if result.returncode or result.stdout.strip()!=DEVICE_SERIAL:
                    remote_status = "连接失败，请检查两端的 IPv4 连接 和受控端的 ADB 授权"
                    return
                with (root / "scrcpy.log").open("wb") as log:
                    session = subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/"tools/remote_session.py"),ADB,DEVICE,SCRCPY,"-s",DEVICE,"--no-audio","--no-power-on"],
                        cwd=TOOLS,env=dict(os.environ,ADB=ADB),stdin=subprocess.DEVNULL,stdout=log,stderr=log)
                remote_status = "远控窗口已在服务端桌面运行"
            except (OSError,subprocess.TimeoutExpired):
                remote_status = "启动失败，请检查服务端上的 scrcpy 和手机网络"

    class Page(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def do_GET(self):
            if self.headers.get("Host") != HOST:
                return self.send_error(404)
            path=urlsplit(self.path)
            if path.path=="/refresh.js":
                data=(Path(__file__).resolve().parent/"refresh.js").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type","text/javascript; charset=utf-8")
                self.end_headers()
                self.wfile.write(data)
                return
            if path.path=="/changes":
                since=parse_qs(path.query).get("since",[""])[0]
                with updates:
                    updates.wait_for(lambda: str(revision)!=since,timeout=55)
                    data=str(revision).encode()
                self.send_response(200)
                self.send_header("Cache-Control","no-store")
                self.end_headers()
                try: self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError): pass
                return
            if path.path!="/":
                return self.send_error(404)
            with updates:
                version=revision
            try:
                offset = max(0,int(parse_qs(urlsplit(self.path).query).get("offset",["0"])[0]))
                offset = min(offset,1000000000)
            except ValueError:
                return self.send_error(400)
            with lock:
                minutes = timeout_minutes(db)
                last,armed,offline = db.execute("SELECT last,armed,offline FROM state").fetchone()
                pending_mode=db.execute("SELECT armed FROM mode_command WHERE slot=1").fetchone()
                latest = db.execute("SELECT battery,powered FROM latest").fetchone()
                low,high,zone,sampled = db.execute("SELECT low,high,zone,sampled FROM battery_settings WHERE id=1").fetchone()
                chart_end = int(time.time())
                samples = db.execute("SELECT sampled,level FROM battery_history WHERE sampled BETWEEN ? AND ? ORDER BY sampled",
                                     (chart_end-86400,chart_end)).fetchall()
                top,unread=db.execute("SELECT coalesce(max(seq),0),count(case when seen=0 then 1 end) FROM log_item WHERE cleared=0").fetchone()
                rows = db.execute("""SELECT e.kind,e.device_time,e.received,e.battery,p.attempts,p.sent,p.error,l.seq,l.seen
                   FROM events e JOIN log_item l USING(id) LEFT JOIN push p USING(id)
                   WHERE l.cleared=0 ORDER BY l.seq DESC LIMIT 51 OFFSET ?""",(offset,)).fetchall()
                waiting = db.execute("SELECT count(*) FROM push WHERE sent=0").fetchone()[0]
            items = []
            def log_action(action,seq,title):
                return (f'<form method="post" action="/{action}"><input type="hidden" name="csrf" value="{csrf}">'
                        f'<input type="hidden" name="seq" value="{seq}"><button>{title}</button></form>')
            for kind,t,r,b,attempts,sent,error,seq,seen in rows[:50]:
                status = "历史记录" if attempts is None else ("服务已受理" if sent else error or "待发送")
                mark="已读" if seen else log_action("read",seq,"未读 · 标为已读")
                items.append(("<tr>" if seen else '<tr class="unread">')+"".join("<td>"+html.escape(str(x))+"</td>" for x in
                         (stamp(t),stamp(r) if kind not in ("offline","online") else "服务端本机判定",
                          ("—" if kind in ("offline","online") else f"{round(r-t)} 秒"),
                          names.get(kind,kind),str(b)+"%" if b>=0 else "—",status))+f"<td>{mark}</td></tr>")
            nav = (f'<a href="/?offset={max(0,offset-50)}">上一页</a> ' if offset else "")
            if len(rows)>50:
                nav += f'<a href="/?offset={offset+50}">下一页</a>'
            online = "心跳已暂停" if not armed else ("离线" if offline else ("在线" if time.time()-last<=minutes*60 else "等待上报"))
            next_mode=1-(pending_mode[0] if pending_mode else armed)
            mode_notice=("等待受控端 确认"+("开始布防" if pending_mode[0] else "暂停布防")) if pending_mode else ""
            connection = remote_status
            if session and session.poll() is not None and connection=="远控窗口已在服务端桌面运行":
                connection = "远控窗口已关闭" if session.returncode==0 else "远控已中断，请查看 scrcpy.log"
            battery = str(latest[0])+"%" if latest and latest[0]>=0 else "—"
            supply = ("已接电" if latest[1] else "电池供电") if latest else ""
            battery_warning = {"battery_low":" · 偏低","battery_high":" · 偏高"}.get(zone,"")
            key_status = "已配置" if keyfile.exists() else "待配置"
            page = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
            <title>{html.escape(DEVICE_NAME)} · 布防</title><style>body{{font:16px system-ui;color:#142a33;background:#f4f7f6;max-width:990px;margin:5vh auto;padding:0 16px}}
            section{{background:white;padding:18px 22px;border-radius:12px;margin:16px 0;overflow:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #dde5e4;white-space:nowrap}}input,button{{font:inherit;padding:6px}}a{{color:#166c67}}</style>
            <style>.unread{{background:#e3f4ed;font-weight:600}}.actions{{display:flex;gap:1em;align-items:baseline;flex-wrap:wrap;margin-bottom:1em}}summary,button{{cursor:pointer}}</style>
            <meta name="revision" content="{version}"><script src="/refresh.js" defer></script>
            <h1>{html.escape(DEVICE_NAME)} · 布防</h1><section id="state"><b>{online} ·受控端最近确认{'已布防' if armed else '已暂停'}</b>　最近上报 {stamp(last)}　<a href="/">刷新</a>
            <p><strong>最近电量 {battery}{battery_warning}</strong>　{supply}　电量更新时间 {stamp(sampled)}</p>
            <form method="post" action="/mode"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="armed" value="{next_mode}">
            <button>{'开始布防' if next_mode else '暂停布防'}</button> {mode_notice}</form>
            <h2>电量变化 · 最近 24 小时</h2>{battery_chart(samples,chart_end)}</section>
            <section><form method="post" action="/timeout"><input type="hidden" name="csrf" value="{csrf}">
            <label>心跳超时（分钟） <input type="number" min="1" max="1440" name="minutes" value="{minutes}" required></label>
            <button>保存</button></form><p></p><form method="post" action="/battery"><input type="hidden" name="csrf" value="{csrf}">
            <label>低电量 ≤ <input type="number" min="0" max="99" name="low" value="{low}" required>%</label>
            <label>高电量 ≥ <input type="number" min="1" max="100" name="high" value="{high}" required>%</label>
            <button>保存电量阈值</button></form><p></p><form method="post" action="/connect"><input type="hidden" name="csrf" value="{csrf}">
            <button>在服务端上远控受控端</button> {connection}</form></section>
            <section><h2>Server酱³</h2><p id="delivery">{key_status}　待发送 {waiting} 条</p><form method="post" action="/key">
            <input type="hidden" name="csrf" value="{csrf}"><label>SendKey <input name="key" type="password" autocomplete="off" required></label>
            <button>保存密钥</button></form></section><section id="logs"><h2>通知日志 · {unread} 条未读</h2><div class="actions">
            {log_action('read-all',top,'全部标为已读') if unread else ''}
            <details><summary>清除日志</summary><p>清除本次刷新前的全部日志。待发通知仍会投递。</p>{log_action('clear',top,'确认清除')}</details>
            </div><table><tr><th>发生时间</th><th>服务端收到</th><th>两端时差</th><th>事件</th><th>电量</th><th>通知端推送</th><th>阅读状态</th></tr>
            {''.join(items)}</table><p>{nav}</p></section></html>""".encode()
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Security-Policy","default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            if self.path=="/desktop-changed":
                if self.headers.get("Host")!=HOST or not secrets.compare_digest(
                        self.headers.get("Authorization",""),"Bearer "+desktop_token):
                    return self.send_error(403)
                changed()
                self.send_response(204)
                self.end_headers()
                return
            if self.path not in ("/mode","/key","/clear","/read","/read-all","/timeout","/battery","/connect") or self.headers.get("Host") != HOST or self.headers.get("Origin") != "http://"+HOST:
                return self.send_error(403)
            try:
                size = int(self.headers.get("Content-Length","0"))
                if not 0<size<=2048:
                    raise ValueError()
                form=parse_qs(self.rfile.read(size).decode())
                if not secrets.compare_digest(form["csrf"][0],csrf):
                    raise ValueError()
                if self.path=="/key":
                    key=form["key"][0].strip()
                    if not KEY_PATTERN.fullmatch(key): raise ValueError()
                elif self.path=="/mode":
                    desired=form["armed"][0]
                    if desired not in ("0","1"): raise ValueError()
                elif self.path=="/timeout":
                    minutes=int(form["minutes"][0])
                    if not 1<=minutes<=1440: raise ValueError()
                elif self.path=="/battery":
                    low,high=int(form["low"][0]),int(form["high"][0])
                    if not 0<=low<high<=100: raise ValueError()
                elif self.path!="/connect":
                    seq=int(form["seq"][0])
                    if not 0<=seq<2**63: raise ValueError()
            except (ValueError,KeyError):
                return self.send_error(400,"Invalid form or ServerChan3 SendKey")
            if self.path=="/connect":
                connect_remote()
            with lock,db:
                if self.path=="/mode":
                    db.execute("INSERT OR REPLACE INTO mode_command VALUES(1,?,?)",(secrets.token_hex(16),int(desired)))
                elif self.path=="/connect":
                    pass
                elif self.path=="/timeout":
                    db.execute("UPDATE heartbeat_settings SET minutes=? WHERE id=1",(minutes,))
                elif self.path=="/battery":
                    db.execute("UPDATE battery_settings SET low=?,high=? WHERE id=1",(low,high))
                elif self.path=="/clear":
                    db.execute("UPDATE log_item SET cleared=1,seen=1 WHERE seq<=?",(seq,))
                    db.execute("DELETE FROM events WHERE id IN (SELECT id FROM log_item WHERE cleared=1) AND id NOT IN (SELECT id FROM push WHERE sent=0)")
                    db.execute("DELETE FROM push WHERE sent>0 AND id IN (SELECT id FROM log_item WHERE cleared=1)")
                elif self.path=="/read-all":
                    db.execute("UPDATE log_item SET seen=1 WHERE seq<=?",(seq,))
                elif self.path=="/read":
                    db.execute("UPDATE log_item SET seen=1 WHERE seq=?",(seq,))
                else:
                    tmp=keyfile.with_suffix(".tmp")
                    tmp.write_text(key)
                    os.chmod(tmp,0o600)
                    os.replace(tmp,keyfile)
                    db.execute("UPDATE push SET due=0 WHERE sent=0")
            changed(push=self.path=="/key")
            if self.path=="/mode":
                mode_wake.set()
            if self.path in ("/read","/read-all","/clear"):
                wake_path.touch()
            self.send_response(303)
            self.send_header("Location","/")
            self.end_headers()

    server=ThreadingHTTPServer(("127.0.0.1",18762),Page)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    threading.Thread(target=deliver,daemon=True).start()
    threading.Thread(target=deliver_mode,daemon=True).start()
