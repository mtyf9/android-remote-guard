"""Run on the server after installing the app. Uses an already authorized rooted device."""
import json
import hashlib
import shlex
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
config = json.loads((root/"config.local.json").read_text(encoding="utf-8-sig"))
adb = str(root/"server/scrcpy/adb")
target = config["device_ip"]+":5555"
subprocess.run([adb,"connect",target],check=True)
cmd = [adb,"-s",target]
serial = subprocess.check_output(cmd+["shell","getprop","ro.serialno"],text=True).strip()
if not serial or serial != config["device_serial"]:
    raise SystemExit("受控端序列号不符")
def shell(command, payload=None):
    return subprocess.run(cmd+["shell","-T","su -c "+shlex.quote(command)],
                          input=payload or b"",stdout=subprocess.PIPE,check=True).stdout

def write_file(dest,payload,setup):
    shell(f"umask 077; cat > {dest}.new && {setup} && mv {dest}.new {dest} && restorecon {dest}",payload)
    if shell(f"sha256sum {dest}").split()[0].decode()!=hashlib.sha256(payload).hexdigest():
        raise RuntimeError("配对文件校验失败: "+dest)

app="/data/user/0/local.devicewatch.guard"
module="/data/adb/modules/devicewatch_keys"
shell(f"test -d {app} && mkdir -p {app}/files && chown $(stat -c %u:%g {app}) {app}/files && chmod 700 {app}/files")
for name in ("cert.pem","token","device.json"):
    dest=f"{app}/files/{name}"
    payload=(root/"server/data"/name).read_bytes()
    write_file(dest,payload,f"chown $(stat -c %u:%g {app}) {dest}.new")
shell(f"mkdir -p {module}")
for name,mode in (("module.prop","644"),("service.sh","755")):
    write_file(f"{module}/{name}",(root/"AndroidGuardModule"/name).read_bytes(),f"chmod {mode} {module}/{name}.new")
print("设备配置和模块已写入。请在合适时重启受控端以启动模块。")
