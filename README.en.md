# SUSE Campus Login

[中文](README.md) | **English**

Connect to the campus network and let the app handle login.

For the **Yibin campus of Sichuan University of Science & Engineering**. Supports campus Ethernet, including USB Ethernet adapters, and `SUSE_Hostel` / `SUSE` Wi-Fi on **64-bit Windows 10/11**.

**[Download for Windows](https://github.com/tsiskjsjs532-hash/suse-campus-login/releases/latest)** · [v1.1.3 release notes](docs/releases/v1.1.3.md#english)

## Get started

1. Download `SUSE-CampusLogin-Windows-v1.1.3.zip`, extract it completely into a permanent folder, and open `CampusLogin.exe`.
2. Connect to campus Ethernet or Wi-Fi, enter your own campus account and password, and select your service.
3. Click **保存并测试 (Save and test)**. Keep the app running to sign in automatically when authentication is required.

Windows protects the password stored on your PC.

![Settings window](docs/settings-window.png)

## Everyday use

- **Automatic login**: signs in when authentication is needed and skips login while online.
- **Wired priority**: checks Ethernet first when both Ethernet and campus Wi-Fi are connected.
- **Service list**: loads current campus services; select and save again if your service is renamed.
- **Background operation**: closing the window keeps the app in the system tray; startup is optional.
- **Notifications**: alerts you when connected or when action is needed; can be disabled in settings.

| Action | Control shown in the app |
| --- | --- |
| Open settings | Right-click the tray icon → 打开设置; the icon may be under the up arrow |
| Check now | 立即检查 |
| Pause / resume | 暂停自动登录 / 恢复自动登录 |
| Change account, service or notification settings | Make changes, then click 保存并测试 |
| Refresh services | 刷新服务列表; select a service and save |
| Exit completely | 退出程序, in the window or tray menu |

## Common questions

| Situation | What to do |
| --- | --- |
| Already online; service list cannot refresh | Keep your selection and update the list when login is needed again |
| Account or password rejected | Check your account, password and service, then click 保存并测试; use 打开官方登录页 if manual action is needed |
| App does not start with Windows | Enable 开机自动运行 and save; check that it is enabled in Task Manager's startup apps |
| Other connection problems | Click 连接诊断, copy the report and include the window message in an [issue](https://github.com/tsiskjsjs532-hash/suse-campus-login/issues) |

Include your campus, Windows version and connection type when reporting a problem. Do not send passwords; hide your account in screenshots.

## Upgrade

Exit the old app from the system tray, then extract and open the new version. Existing settings are retained. If you use startup, click 保存并测试 once in the new version to update the startup location, then keep the app folder in place.

[Illustrated guide — Chinese](docs/使用说明.html) · [Development and maintenance](docs/development.md#english)

An unofficial university tool.
