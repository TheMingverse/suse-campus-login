# Mac 使用说明

适用：四川轻化工大学宜宾校区，macOS 15 及以上。

## 下载和使用

1. 在[下载页](https://github.com/TheMingverse/suse-campus-login/releases/tag/v1.2.0-macos-beta.1)选择对应机型的 DMG：Apple 芯片选 `arm64`，Intel 选 `x86_64`。机型可在苹果菜单的“关于本机”查看。
2. 打开 DMG，将 `SUSECampusLogin.app` 拖入“应用程序”，再打开应用。若系统阻止首次打开，到“系统设置 → 隐私与安全性”查看并确认。
3. 连接校园 Wi-Fi 或网线，填写自己的账号密码、选择服务，点击“保存并测试”。识别 Wi-Fi 名称时请允许定位服务。

密码保存在 Mac 钥匙串中。

## 日常操作

关闭窗口后，程序继续在顶部菜单栏运行。点击“校园网”可打开设置、检查连接、暂停或退出。

更换服务时点击“刷新服务列表”，选择后保存。当前已在线、暂时无法刷新时，保留原选择即可。

勾选“登录 Mac 时自动运行”并保存；如系统要求确认，到“系统设置 → 通用 → 登录项”中允许。

## 问题反馈

点击“连接诊断”，报告会复制到剪贴板。请在 [Issues](https://github.com/TheMingverse/suse-campus-login/issues) 中附上 Mac 芯片类型、系统版本、连接方式和窗口提示。请不要发送密码，截图遮住账号。

## 停止使用

取消登录时启动并保存，退出程序后从“应用程序”移除应用。需要删除账号设置时，可在钥匙串访问中查找 `io.github.themingverse.suse-campus-login`，并移除 `~/Library/Application Support/SUSECampusLogin` 中的设置文件。

非学校官方工具。
