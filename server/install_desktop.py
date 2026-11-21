"""Build the local macOS notification agent alongside receiver.py."""
import plistlib
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent
bundle = root / "AndroidRemoteGuardAlerts.app"
contents = bundle / "Contents"
binary = contents / "MacOS" / "AndroidRemoteGuardAlerts"
binary.parent.mkdir(exist_ok=True, parents=True)
subprocess.run(["xcrun","swiftc","-O",str(root/"DesktopAlerts.swift"),"-o",str(binary)],check=True)
(contents/"Info.plist").write_bytes(plistlib.dumps(dict(
    CFBundleIdentifier="local.devicewatch.guard.alerts", CFBundleName="受控端 布防",
    CFBundleDisplayName="受控端 布防", CFBundleExecutable=binary.name,
    CFBundlePackageType="APPL", CFBundleVersion="1", CFBundleShortVersionString="1.0",
    LSUIElement=True, NSPrincipalClass="NSApplication")))
subprocess.run(["codesign","--force","--sign","-",str(bundle)],check=True)
