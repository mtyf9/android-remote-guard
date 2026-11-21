"""Run on the server after installing the app. Uses an already authorized rooted device."""
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config = json.loads((root/"config.local.json").read_text(encoding="utf-8-sig"))
adb = str(root/"server/scrcpy/adb")
target = config["device_ip"]+":5555"
subprocess.run([adb,"connect",target],check=True)
cmd = [adb,"-s",target]
serial = subprocess.check_output(cmd+["shell","getprop","ro.serialno"],text=True).strip()
if not serial or serial != config["device_serial"]:
    raise SystemExit("受控端序列号不符")
def shell(command, payload=None):
    subprocess.run(cmd+["exec-in","su","-c","'"+command+"'"],input=payload,check=True)

app="/data/user/0/local.devicewatch.guard"
module="/data/adb/modules/devicewatch_keys"
shell(f"test -d {app} && mkdir -p {app}/files && chown $(stat -c %u:%g {app}) {app}/files && chmod 700 {app}/files")
for name in ("cert.pem","token","device.json"):
    dest=f"{app}/files/{name}"
    payload=(root/"server/data"/name).read_bytes()
    shell(f"umask 077; cat > {dest}.new && chown $(stat -c %u:%g {app}) {dest}.new && mv {dest}.new {dest} && restorecon {dest}",payload)
shell(f"mkdir -p {module}")
for name,mode in (("module.prop","644"),("service.sh","755")):
    shell(f"cat > {module}/{name}.new && chmod {mode} {module}/{name}.new && mv {module}/{name}.new {module}/{name}",(root/"AndroidGuardModule"/name).read_bytes())
print("设备配置和模块已写入。请在合适时重启受控端以启动模块。")
