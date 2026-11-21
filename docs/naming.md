# 命名规范

| 对象 | 规则 | 示例 |
|---|---|---|
| 项目与发布产物 | 产品名统一为 AndroidRemoteGuard，仓库地址使用小写连字符 | `android-remote-guard`、`AndroidRemoteGuard.apk`、`AndroidRemoteGuardAlerts.app` |
| Android 组件目录 | 以 AndroidGuard 开头，PascalCase，后缀说明职责 | `AndroidGuardApp/`、`AndroidGuardModule/` |
| 通用目录 | 小写，按职责划分 | `server/`、`tools/`、`docs/` |
| PowerShell 入口 | 动词-名词，PascalCase | `Build-App.ps1`、`Connect-Device.ps1` |
| Python 模块与脚本 | 小写，下划线分词 | `install_desktop.py`、`provision_device.py` |
| 构建环境变量 | 大写，下划线分词，项目前缀 ANDROID_REMOTE_GUARD | `ANDROID_REMOTE_GUARD_KEYSTORE`、`ANDROID_REMOTE_GUARD_PASS_FILE` |

用户文档和界面统一使用「受控端」「服务端」「通知端」。设备的显示名称取自部署配置中的 `device_name`。Android、Magisk 和操作系统指定的入口文件沿用各自约定，例如 `AndroidManifest.xml`、`module.prop` 和 `service.sh`。

Android 包名、广播 action、Magisk 模块 ID、服务端登录项及通知组件的 bundle identifier 属于现有安装的持久标识。更改这些标识需要另行设计迁移，以保留应用数据、覆盖升级能力和通知授权。构建脚本兼容旧的签名环境变量和旧目录中的密钥。
