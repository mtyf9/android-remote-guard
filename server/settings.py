"""Deployment values shared with the Windows tools."""
import ipaddress
import json
from pathlib import Path

config_file = Path(__file__).resolve().parent.parent / "config.local.json"
settings = json.loads(config_file.read_text(encoding="utf-8-sig"))
DEVICE_NAME = settings["device_name"].strip()
DEVICE_SERIAL = settings["device_serial"].strip()
DEVICE = str(ipaddress.IPv4Address(settings["device_ip"])) + ":5555"
SERVER_IPS = [str(ipaddress.IPv4Address(value)) for value in settings["server_ips"]]
if not DEVICE_NAME or not SERVER_IPS or not DEVICE_SERIAL or DEVICE_SERIAL.startswith("REPLACE_"):
    raise ValueError("请先在 config.local.json 填写设备名称、实际序列号和服务端地址")
