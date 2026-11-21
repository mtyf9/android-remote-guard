# Windows 可选工具

远控手机或访问管理页时，在本目录把 `config.example.json` 复制为 `config.local.json` 并填写连接信息。单独构建 APK 可以直接运行 `Build-App.ps1`。请备份首次生成的签名密钥，后续覆盖升级时使用同一密钥。

| 入口 | 用途与依赖 |
|---|---|
| `Connect-Device.ps1` | 使用 PATH 中的 scrcpy 和已授权的 ADB 连接受控端。填写 `device_name`、`device_ip` 和设备实际的 `device_serial`。 |
| `Open-Dashboard.ps1` | 使用 OpenSSH 转发服务端管理页。填写 `ssh_host`；可选 `ssh_identity` 指定私钥路径。 |
| `Build-App.ps1` | 可选的 Windows 构建入口，无需连接配置。需要 PowerShell 7.3+、JDK 17 或 21、Android SDK Platform 35、Build Tools 35.0.0 和 ANDROID_HOME。产物在 AndroidGuardApp/build/。 |
