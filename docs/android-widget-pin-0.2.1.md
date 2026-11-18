# 0.2.1 小组件添加入口优化报告

本次完成小组件添加流程优化，版本 0.2.1，versionCode 3。保留包名、签名与账号加密格式，可覆盖安装。未增加后台认证或调整学校协议。

## 安装包

`D:\校园网自动化\build\android-delivery\SUSE-CampusLogin-Android-v0.2.1-debug.apk`

SHA-256：`c3c7cb19f1315fbe5b98e7061bad7b3592f7feb483620ea89a3e5c9b7423f6f5`

原构建输出仍为 `android/app/build/outputs/apk/debug/app-debug.apk`，设备测试包也已成功编译。使用带版本号的交付文件重新发送到手机，安装器应显示原版本 → 0.2.1。

## 行为变化

- 点击添加按钮向桌面发起公开 API 请求，附上对应尺寸的静态预览。预览不包含登录 PendingIntent。
- 请求返回 true 仅显示“已请求系统添加”，不将其视为确认框已显示或添加成功。
- 收到匹配的系统成功回调后才显示“已添加到桌面”。回调使用不导出接收器及显式、不可变 PendingIntent；只更新添加提示，不访问账号或启动认证。
- 等待期间合并普通重复点击。取消确认没有回调时不推断失败，不自动再次申请。用户可明确选择重新请求 1×1 或 2×1。
- 显式重新请求使旧令牌失效，迟到的旧回调不能覆盖新请求。独立原子文件只保存阶段、尺寸和令牌，支持进程重建。
- 不支持、被拒绝或异常时提供手动步骤。只有点击“返回桌面”才使用公开 HOME Intent 离开 App，不自动抢走可能已显示的确认框。

Android 的桌面程序决定是否展示和如何展示确认页，当前实现不能保证每个桌面都会弹出，也不强制跳转厂商私有的小组件列表或无关权限设置页。

## 实现

新增 `WidgetPinController.kt`、`AndroidWidgetPinGateway.kt`（包含 PinFile 与 WidgetPinResultReceiver）。首页 QuickEntryControls 接入共享添加控制器；应用容器将其与认证容器分离。QuickWidgets 增加仅供添加预览使用的非交互模式，实际桌面点击登录保留原行为。

清单新增一个不导出的成功回调接收器，验证脚本检查精确组件列表和回调约束。README 与开发说明已更新。

## 实际验证

- Android 全部 JVM 测试：**102 项通过，0 失败、0 跳过**；比 0.2.0 新增 21 项，其中纯控制器 12 项、API 29/34/36 组件模拟 9 项。
- 组件模拟总数：**45 项**，包含既有小组件、磁贴测试及新增的添加网关测试。
- 原有 Python/Windows 回归：**135 项通过**。
- Python/Kotlin 合成协议样例：通过。
- Android lint：0 错误、24 条警告，主要为依赖更新、旧版本尺寸属性、紧凑字号与文案/写法建议。
- Debug APK 和设备测试 APK：BUILD SUCCESSFUL。
- 签名、版本、ZIP 完整性、安全配置及新回调接收器：核验通过。

测试覆盖请求受理不等于成功、无回调取消、重复点击、拒绝、不支持、异常、同步回调、令牌替换、跨进程恢复、存储失败、主动返回桌面、两种预览和不可变回调。Robolectric 在此测试中记录广播而不自动创建清单接收器；测试验证发送载荷后，将同一记录交给实际接收器，以验证处理逻辑。没有把这种模拟当成真实 Launcher 回调交付结果。

执行命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_build.py
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -X utf8 tools\android_protocol_vectors.py --check
.\.venv\Scripts\python.exe -X utf8 tools\android_verify.py
git diff --check
```

## 待真机验证

本机未检测到连接设备，未运行 Android 模拟器。实际手机桌面确认框是否出现、成功回调是否由该桌面交付、用户取消和系统杀进程后恢复，仍需真机验证。没有发现阻塞构建或自动测试的问题，但不能据模拟测试保证小米桌面一定显示确认页。

建议覆盖安装新版后依次检查两种尺寸：点击请求 → 系统确认 → 回 App 显示成功；取消时保持等待；没有确认框时尝试明确的重新请求或“返回桌面”手动添加。实际已添加的小组件点击登录不受本次修改影响。

Windows/macOS 源码未修改，未读取真实密码，未提交、推送或发布远程仓库。本次优化到此停止。
