# Android 第二阶段开发报告

日期：2026 年 11 月 16 日。

第二阶段实现和本地验证已完成：版本 0.2.0（versionCode 2），最低 Android 10，target SDK 36。Debug APK 构建成功，81 项 Android JVM 测试通过、135 项原有 Python 回归测试通过，lint 0 错误、24 警告。当前没有连接的 Android 设备，未运行 Android 模拟器；本轮尚未进行实际桌面、控制中心和真实校园网的第二阶段验收。

## 交付

- APK：`D:\校园网自动化\android\app\build\outputs\apk\debug\app-debug.apk`
- APK 大小：30,752,006 字节。
- SHA-256：`5d5042ffb7bb01a7edf26625d59fedc338fa243c27da3c56de3d074716c8a6c5`
- 设备测试 APK：`D:\校园网自动化\android\app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk`
- 核验报告：`build/android/verification.json`。
- 使用说明：`android/README.md`；技术说明：`docs/android-development.md`。

保留包名、本地调试签名、Keystore alias 与配置格式，可以覆盖安装；不要为了升级卸载旧版本，否则系统会移除本地账号数据和密钥。

## 已实现

1. 原生 1×1、2×1 RemoteViews 小组件。小组件点击直接通过不可变、显式 PendingIntent 启动轻量认证页，不通过广播中转启动。
2. 轻量认证页自动检查并按需登录；已联网不提交凭据；未配置引导进入原配置页。成功更新结果后约一秒关闭，失败保留说明、重试和设置入口。
3. SUSE 登录快捷设置磁贴。锁屏先解锁，API 29–33 与 34+ 分支启动同一页面，TileService 不执行网络请求，监听结束注销状态收集。
4. 首页添加小组件及磁贴的系统请求入口和手动添加说明。保持原有首页、账号配置、只读刷新和自动检查开关。
5. 应用级共享认证核心：三个入口只有一个 LoginEngine、一份 AndroidWifiAccess 和一份 SecureConfigurationStore，通过协调器加入正在执行的任务，不能并发提交。
6. 显式登录可取消并等待只读刷新；保存配置等待旧任务结束。网络绑定、服务精确匹配、密码算法、HTTP 限制及凭据错误保护继续复用第一阶段。
7. 应用完全离开前台、返回桌面或锁屏取消任务；旋转保留任务，App 页面与临时页面交接不取消；进程结束不恢复认证。
8. 小组件使用明确的历史结果和时间。独立本地记录只有固定状态码、时间和任务标识，不含账号、密码、服务、IP、MAC、Cookie 或服务器原始文本。遗留未完成任务显示中断，配置更新后提示重新检查。
9. 深浅色资源、最小尺寸排布、辅助功能描述、多个小组件状态同步、删除和恢复时只重绘。

未增加周期任务、Wi-Fi 后台自动登录、开机认证、长期后台监听、常驻前台服务或厂商接口。

## 主要新增与调整

| 模块 | 作用 |
| --- | --- |
| core/LoginCoordinator.kt | 应用内启动/加入、去重、取消、配置保存序列化、任务标识及终态发布 |
| core/Models.kt、LoginEngine.kt | 增加可选失败分类，完善 finally 解锁，协议与密码处理未改写 |
| app/CampusApplication.kt | 唯一依赖容器及统一的前台可见性管理 |
| app/CampusViewModel.kt | 首页接入共享任务，不再自建引擎 |
| app/QuickLoginActivity.kt | 简洁认证 UI、配置与权限引导、旋转和重复 Intent 处理 |
| app/QuickWidgets.kt 与 widget XML | 两种小组件、直接点击入口和系统广播恢复 |
| app/QuickResultStore.kt | 不参与备份的原子历史状态记录 |
| app/LoginTileService.kt | 用户磁贴点击、解锁、API 版本兼容和显示 |
| app/QuickEntryControls.kt | 首页的添加与使用入口 |
| tools/android_test_jdk.py | 校验并准备独立测试 JDK 21，不改系统 Java |
| tools/android_verify.py | 允许精确的小组件/磁贴组件，核验版本、权限、签名与安全边界 |

## 实际测试

| 测试组 | 数量 | 结果 |
| --- | ---: | --- |
| 协议及原有 RSA 向量 | 8 | 全部通过，包含原有五组密码向量 |
| HTTP 网络传输 | 8 | 全部通过 |
| 第一阶段一次性登录流程 | 18 | 全部通过 |
| 共享任务协调器 | 9 | 全部通过 |
| 保留的前台会话测试 | 2 | 全部通过 |
| 小组件、历史与 Activity 生命周期组件模拟 | 27 | 9 场景 × API 29/34/36，全部通过 |
| TileService 组件模拟 | 9 | 3 场景 × API 29/34/36，全部通过 |
| 原有 Python/Windows 回归 | 135 | 全部通过 |

Robolectric 是在 JVM 中模拟 Android 组件的测试工具，不是运行真实桌面的 Android 模拟器。组件测试验证了 RemoteViews 创建、点击 Intent、版本分支、解锁取消/完成、监听停止、夜间资源、历史结果恢复、Activity 交接与旋转。没有以这些结果宣称真实 Launcher/SystemUI 已通过。

协调器测试额外确认取消发生在任务第一次执行前时也不会卡在忙碌状态，历史写入失败不会向临时页面发布“已完成桌面更新”的成功结果。失败响应、网络切换、移动数据与目标 Wi-Fi 分离继续由原核心测试覆盖。设备专用的真实 RemoteViews 和组件清单测试也已加入并编译，尚未运行。

实际命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_test_jdk.py
.\.venv\Scripts\python.exe -X utf8 tools\android_build.py
.\.venv\Scripts\python.exe -X utf8 tools\android_protocol_vectors.py --check
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -X utf8 tools\android_verify.py
.\.cache\android-tools\sdk\platform-tools\adb.exe devices -l
git diff --check
```

构建实际执行 `:core:test :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest`，最终为 BUILD SUCCESSFUL。核验包含官方 apksigner 签名验证、aapt 版本读取、ZIP 完整性、组件导出与绑定权限、HTTP 限制及备份规则。

## 构建中解决的问题

- 系统恢复广播可能同时分发 onRestored 和 onUpdate：改为每个广播只领取一次异步 PendingResult，并在 finally 释放，消除重复领取导致的空引用。
- target 36 的 lint 拦截旧 TileService Intent 重载：保留 29–33 必需兼容路径并局部说明，34+ 使用 PendingIntent，测试覆盖两个分支。
- Robolectric 的 API 36 镜像要求 Java 21：单独下载 Microsoft JDK 21.0.13.0.2 并核对官方 SHA-256，仅应用组件测试进程使用；构建和应用字节码保持 Java 17。最初校验链接未返回校验文本，未执行下载内容，修正为官方固定版本 checksum 链接后核验通过。
- 修复重复 Intent 在页面恢复前触发导致无法开始、权限返回覆盖原提示、首页加载配置覆盖共享忙碌状态等情况。
- 系统控制中心会给图标统一着色：新增单色 Wi-Fi 图标，避免使用带整块背景的应用图标。
- 修正测试 SystemUI shadow 的生命周期继承，使服务销毁和监听清理也参与测试；最终全部通过。

## 未完成的设备验收与剩余事项

本轮 `adb devices -l` 无设备，且按方案不下载安装 Android 模拟器。因此没有真实桌面添加/点击、小组件实际刷新、控制中心磁贴启动或第二阶段真实校园网认证结果。不能将组件模拟测试记为模拟器或真机通过。

第一阶段真实小米手机校园网认证成功属于用户反馈，已保留该验证来源和范围；它不代替第二阶段入口验收。

lint 的 24 条警告包括依赖存在较新版本、旧系统忽略新版 widget 尺寸属性、紧凑尺寸字号、固定中文文本及 KTX 风格建议；没有 lint 错误。新版属性同时有旧版最小尺寸作为回退。小组件在不同桌面网格、大字体下的实际排布仍需真机检查。

没有已知阻塞构建或自动测试的严重问题，但后台 Activity 启动规则在真实 Launcher/SystemUI 上的执行、不同厂商的格数和权限交互尚无本轮设备证据。

## 用户验收建议

1. 覆盖安装新版，确认已有账号配置仍保留。
2. 首页请求添加两种小组件；若桌面不支持请求，长按桌面从列表添加。
3. 点击小组件，确认无需再次点登录，已联网时不会重新提交；检查 2×1 的“上次检查”结果和时间。
4. 控制中心添加 SUSE 登录，验证未锁屏点击、锁屏解锁成功及取消解锁。
5. 认证时连续点击小组件/磁贴，确认只显示同一任务；检查旋转不会重复提交。
6. 按 Home 或锁屏，确认本次任务取消；失败时检查重试和配置/权限入口。
7. 删除、重新添加小组件及重启手机，确认只显示历史状态，不自行认证。
8. 在手机/平板、深浅色和大字体下检查可读性。

有专用测试设备后，可运行 `python tools/android_build.py :app:connectedDebugAndroidTest`。自动设备测试使用合成数据和独立测试密钥；实际校园网验收由使用者在手机输入自己的凭据，不提供到聊天或测试文件。

## 工作区保护

Windows/macOS 生产代码和原发布包没有修改，第一阶段未提交工程继续保留；没有 git reset、提交、推送或远程发布，没有读取真实账号密码。新增及修改内容限 Android 工程、Android 验证工具和对应文档，第二阶段至此停止。
