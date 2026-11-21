"""Run as the logged-in 服务端 user in the installed receiver directory."""
from settings import SERVER_IPS, DEVICE_NAME
import json
import os
import plistlib
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

program = Path(__file__).resolve().parent
if sys.platform == "darwin" and not (program / "AndroidRemoteGuardAlerts.app/Contents/MacOS/AndroidRemoteGuardAlerts").is_file():
    subprocess.run([sys.executable,str(program / "install_desktop.py")],check=True)
root = program / "data"
os.umask(0o077)
root.mkdir(parents=True,exist_ok=True)
if not (root / "token").exists():
    (root / "token").write_text(secrets.token_hex(32))
if not (root / "cert.pem").exists():
    openssl = shutil.which("openssl")
    if not openssl:
        raise SystemExit("请将 OpenSSL 加入 PATH，然后重新运行安装程序。")
    cfg = root / "openssl.cnf"
    cfg.write_text("[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ext\n"
                   "[dn]\nCN=AndroidRemoteGuard\n[ext]\nsubjectAltName=" + ",".join("IP:"+ip for ip in SERVER_IPS) + "\n"
                   "basicConstraints=critical,CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
                   "extendedKeyUsage=serverAuth\n")
    subprocess.run([openssl,"req","-x509","-nodes","-newkey","rsa:2048",
                    "-days","730","-keyout",str(root/"key.pem"),"-out",str(root/"cert.pem"),
                    "-config",str(cfg)], check=True)
(root/"device.json").write_text(json.dumps(dict(name=DEVICE_NAME,servers=SERVER_IPS)),encoding="utf-8")
if sys.platform != "darwin":
    print(f'配置完成。启动服务端："{sys.executable}" "{program / "receiver.py"}"')
    sys.exit(0)
agent = Path.home()/"Library/LaunchAgents/local.devicewatch.guard.plist"
agent.parent.mkdir(exist_ok=True)
label = "local.devicewatch.guard"
agent.write_bytes(plistlib.dumps(dict(Label=label, ProgramArguments=[sys.executable,str(program/"receiver.py")],
                                     RunAtLoad=True,KeepAlive=True,ThrottleInterval=10,
                                     StandardErrorPath=str(root/"receiver.log"))))
domain = "gui/"+str(os.getuid())
subprocess.run(["launchctl","bootout",domain+"/"+label],stderr=subprocess.DEVNULL)
subprocess.run(["launchctl","bootstrap",domain,str(agent)],check=True)
