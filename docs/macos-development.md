# Mac 开发与验证

## 结构

`main_macos.py` 为独立入口，`campus_login/macos/` 提供 AppKit 窗口与菜单栏、SystemConfiguration/CoreWLAN 网络读取、CoreLocation 权限、Darwin 绑定请求、钥匙串、系统通知与登录项。

共用 `engine`、`portal`、`network`、`models` 和通知策略。Windows 原入口、DPAPI 设置格式和发布包保持不变。

## 构建

在 macOS 15 或以上使用 Python 3.13：

```sh
python -m pip install -r requirements-macos.txt
python -m unittest discover -s tests/macos -v
python tools/package_macos.py
python tools/check_macos_app.py
```

依赖版本固定在 `requirements-macos.txt`，构建产物同时附带完整 `pip freeze`。产物位于 `build/macos-release`。DMG 和 ZIP 包含临时签名的原生架构应用、使用说明、第三方许可和 Applications 快捷入口。

## 自动验证

[GitHub 工作流](https://github.com/TheMingverse/suse-campus-login/actions/workflows/macos.yml)分别运行 Windows、macos-15（Apple 芯片）和 macos-15-intel。

- Windows：现有 135 项测试。
- Mac：43 项共用认证、引擎和网络测试；4 项 Windows 存储测试明确跳过，由 Mac 钥匙串与存储测试覆盖。
- 每种 Mac：8 项新增逻辑与系统集成测试，包括真实回环 HTTP 与 requests 调用链、网卡绑定状态、无效接口失败、系统网络快照、临时钥匙串 CRUD、单实例及原子保存。
- 打包后应用：核对 Mach-O 架构和签名，实际启动原生窗口与菜单栏，检查窗口关闭与重新打开、服务选择保留、过期列表忽略、暂停恢复、后台引擎退出和控件边界。
- 登录项：在临时运行器中调用注册与取消注册，记录状态；系统要求批准时如实记录。截图、应用报告和依赖列表作为 Actions artifacts 保留。

CI 仅使用合成账号和临时钥匙串，不读取真实校园网密码。测试机器上如出现仅用于本地 HTTP 测试的本地网络授权弹窗，截图工具尝试确认该弹窗，不修改 Gatekeeper 或用户设备设置。

## 验证范围

云端测试能够验证构建、系统接口、合成认证流程与应用生命周期；运行器没有学校 Wi-Fi 和物理网线条件。真实校园网登录、定位权限批准与拒绝、系统通知实际显示、睡眠唤醒和物理网卡切换尚需现场验证。

应用采用临时签名，未使用 Apple Developer ID 或 Apple 公证，不以云端启动成功代替下载后的 Gatekeeper 验收。首次打开的正常系统确认步骤见使用说明。

旧 Windows v1.1.3 继续作为默认稳定版本，Mac 测试版使用独立标签 `v1.2.0-macos-beta.1`。
