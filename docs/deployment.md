# 在服务端部署

只需一台服务端电脑和一部受控 Android 设备。以下命令均在服务端的项目根目录执行。只有需要在另一台 Windows 电脑上操作时，才使用文末的可选工具。

## 1. 填写本地配置

将根目录的 `config.example.json` 复制为 `config.local.json`。在服务端填写该文件。示例地址均须替换。

| 字段 | 用途 |
|---|---|
| `device_name` | 自定义机器名，显示在受控端、网页和通知标题中 |
| `device_ip` | 控制端可访问的受控端 IPv4 地址，ADB 监听 TCP 5555 |
| `device_serial` | 在已确认身份的设备上执行 `adb shell getprop ro.serialno` 得到的序列号 |
| `server_ips` | 受控端可访问的服务端 IPv4 地址列表，首项优先，也是接收器证书的 IP SAN |

## 2. 准备服务端

当前实现依赖 Apple 桌面系统的 launchd、AppKit 和 UserNotifications。准备 Python 3、Xcode Command Line Tools，以及与服务端架构相符的官方 scrcpy 发行包。将其内容解压至 `server/scrcpy/`，确认该目录含可执行的 `adb`、`scrcpy` 和配套的 scrcpy-server。从项目根目录以当前桌面用户运行：

```sh
python3 server/install.py
```

安装程序在 `server/data/` 生成私有令牌、证书、密钥和受控端连接配置，编译原生通知组件，并安装用户级 LaunchAgent。用户登录后服务自启；服务端须保持唤醒。服务端地址变更时，应在维护窗口更新证书及受控端信任配置。

## 3. 构建并配对受控端

已有与受控端安装版本签名一致的 APK 时，直接使用该 APK。需要自行构建时，在服务端准备 JDK 17 或 21、Android SDK Platform 35 和 Build Tools 35.0.0，设置 `ANDROID_HOME` 并将 JDK 命令加入 PATH：

```sh
bash tools/server/build_app.sh
```

首次构建会提示创建签名密钥。请私下备份密钥供后续覆盖升级使用。将产物安装到已获 ADB 授权的手机（也可先用 USB 安装）：

```sh
server/scrcpy/adb devices -l
read -r device    # 输入上一行列表中的设备连接标识
server/scrcpy/adb -s "$device" install -r AndroidGuardApp/build/AndroidRemoteGuard.apk
```

先配置可信 IPv4 网络和 ADB 授权，验证服务端能够连接受控端的 TCP 5555。异地组网可以选用 Tailscale。项目的按键模块**不会配置 ADB 的网络监听或防火墙**。随后从服务端的项目根目录运行：

```sh
python3 tools/server/provision_device.py
```

该脚本验证序列号，通过已授权的 root shell 将接收证书、令牌和设备配置放入应用私有目录，并安装 `AndroidGuardModule/` 到 Magisk 模块目录。受控端重启后模块生效。模块按输入驱动名称过滤实体按键，并读取 USB 在位和电池节点；更换机型时请先核对 `service.sh` 中的驱动名称和 sysfs 节点，再逐项实测。只验证过 Android 9 设备的原部署流程。

## 4. 验证与使用

在服务端浏览器打开 `http://127.0.0.1:18762/`。允许「受控端 布防」系统通知，在受控端点「向服务端发送测试通知」。在通知端安装 Server酱³，使用自己的 SendKey 登录，并在管理页保存对应 SendKey。实测通知端锁屏、使用移动数据时能否收到测试告警。

管理页支持暂停和开始布防、查看设备确认状态、设置心跳超时、查看和清理日志，以及启动服务端桌面上的远控窗口。

## 可选：在另一台 Windows 电脑上操作

[Windows 工具说明](../tools/windows/README.md)介绍了连接受控端、打开管理页及构建 APK 三个独立入口。服务端日常运行无需启动这些工具。

## 注意事项

- **无人值守冷启动**：本方案在开机首次解锁后启动布防与网络组件。如果现场没有人解锁，而你需要重启后自动恢复，部署时应移除受控端的系统锁屏 PIN、图案或密码，并实测一次断电重启。移除系统凭据会降低设备遗失时的数据保护；第三方锁屏不能提供相同的加密保护。
- **root 与模块**：完整部署需要受控端已 root，并安装本项目的 Magisk 模块。仅装 APK 无法采集模块提供的实体按键及物理插拔线事件。请保留可恢复的本地管理方式。
- **网络与权限**：将网络 ADB 限制到可信网络接口及已授权的管理设备。不要向公共 Wi-Fi 或公网开放 5555。心跳上报另用 TLS 端口 18761；管理页只监听回环地址。
- **数据与恢复**：受控端本地 SQLite 保留未获确认的告警，服务恢复后按事件 ID 去重补传。服务端数据库、私钥及 SendKey 位于 `server/data/`，请私下备份。两端时钟应开启自动校时。
