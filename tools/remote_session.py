"""Run scrcpy with a short-lived second-lock lease, or pair a trusted host over authorized root ADB."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

adb, device, *args = sys.argv[1:]
base = [adb, "-s", device]
directory = Path.home() / ".android-remote-guard"
directory.mkdir(mode=0o700, exist_ok=True)
path = directory / (hashlib.sha256(device.encode()).hexdigest() + ".json")

if args == ["--pair"]:
    if not path.exists():
        with open(path,"x", opener=lambda p,f: os.open(p,f,0o600)) as out:
            json.dump([secrets.token_hex(16),secrets.token_hex(32)],out)
    host, secret = json.loads(path.read_text())
    folder = "/data/user/0/local.devicewatch.guard/files"
    dest = folder + "/remote-" + host
    cmd = f"umask 077 && cat > {dest}.new && chown $(stat -c %u:%g {folder}) {dest}.new && restorecon {dest}.new && mv {dest}.new {dest}"
    subprocess.run(base+["shell","-T","su -c '"+cmd+"'"],input=bytes.fromhex(secret),check=True,timeout=15)
    sys.exit(0)

host, secret = json.loads(path.read_text()) if path.exists() else ("0"*32,"")

def broadcast(op,proof=None):
    cmd=base+["shell","am","broadcast","--user","0","-n","local.devicewatch.guard/.RemoteLock","--es","host",host,"--es","op",op]
    if proof:
        cmd+=["--es","proof",proof]
    result=subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=6)
    match=re.search(r'data="([^"]*)"',result.stdout)
    return match[1] if match else ""

def lease(op):
    nonce=broadcast("challenge")
    if nonce=="disabled":
        return False
    if not secret or not re.fullmatch(r"[0-9a-f-]{36}",nonce):
        raise RuntimeError("Second lock: host pairing unavailable")
    sig=hmac.digest(bytes.fromhex(secret),f"{host}|{op}|{nonce}".encode(),"sha256")
    if broadcast(op,base64.b64encode(sig).decode())!="ok":
        raise RuntimeError("Second lock: authentication failed")
    return True

leased=lease("open")
child=None
try:
    child=subprocess.Popen(args)
    while True:
        try:
            sys.exit(child.wait(timeout=8))
        except subprocess.TimeoutExpired:
            leased=lease("open")
finally:
    if child and child.poll() is None:
        child.terminate()
    if leased:
        lease("close")
