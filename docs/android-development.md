# Android 开发说明

## 结构与范围

`android/core` 是纯 Kotlin/JVM 模块，负责协议、受限 HTTP 传输和有限认证流程；`android/app` 负责 Android Network、Keystore、Compose 界面和生命周期。系统能力通过 `WifiAccess`、`WifiLease`、`HttpTransport`、`ConfigurationStore` 接口进入核心。

Windows、macOS 的生产代码、入口和发布物未修改。Android 第二阶段增加两种桌面小组件和快捷设置 TileService；不使用后台认证服务、开机认证广播、定时任务、厂商接口或 WebView 自动点击。TileService 只负责用户点击和显示，不执行网络请求。

| 文件 | 职责 |
| --- | --- |
| `core/.../Protocol.kt` | 可信地址、原始查询参数、旧式 RSA、编码、服务列表和结果分类 |
| `core/.../PortalClient.kt` | 只读准备、一次性准备对象、认证、双探测和跳转提取 |
| `core/.../BoundHttpTransport.kt` | 主机/路径/方法限制、Cookie 隔离、禁止重定向和重试、取消及正文上限 |
| `core/.../LoginEngine.kt` | 一次性检查、去重、错误保护、网络变化取消、联网复核和资源释放 |
| `app/.../AndroidWifiAccess.kt` | 按 Wi-Fi Network 获取信息、绑定 SocketFactory/DNS、监听目标变化 |
| `app/.../WifiOverview.kt` | 前台只读观察网络、更新状态并使旧服务列表失效 |
| `app/.../SecureConfigurationStore.kt` | Keystore AES-GCM、本地原子保存、配置版本和暂停标记 |
| `app/.../CampusViewModel.kt` | 界面状态、保存、前台会话自动触发和后台取消 |
| `app/.../CampusScreen.kt`、`MainActivity.kt` | 中文手机/平板界面和前台权限 |

## 协议来源

全部学校协议来源于本地现有 `campus_login/portal.py`、`network.py`、`models.py`、`engine.py` 及测试，没有下载其他学校源码。

- Wi-Fi 名称仅允许 `SUSE`、`SUSE_Hostel`；凭据只提交到 `10.23.2.4` 的 `/eportal/InterFace.do`，端口为 80 或 8080。
- 从真实跳转取得当次 `wlanuserip`、`wlanacname`、`mac`，保留原始查询，不使用设备自身 MAC 或历史地址。
- `pageInfo → getServices → login`，服务字段是最新列表中的完整名称，不猜服务 ID。
- `pageInfo` 表单编码一次；服务查询中的连接参数编码一次；登录字段使用 JavaScript `encodeURIComponent` 规则编码两次。
- RSA 保留 UTF-16 单元反转、16 位 limb、JavaScript 32 位进位及学校旧式分块。不是 PKCS#1/OAEP。
- `tests/rsa_vectors.json` 直接作为核心测试资源；五组输入为合成凭据，历史记录说明它们与学校 security.js 结果一致。
- `tools/android_protocol_vectors.py` 调用未修改的 Python 核心生成合成样例，`--check` 验证样例仍与 Python 一致。
- Android 对未知认证标志、URL fragment 和错误 UTF-8 增加拒绝，不让解析差异导致静默凭据提交。

HTTP 探测地址沿用 `http://www.msftconnecttest.com/connecttest.txt` 和 `http://detectportal.firefox.com/success.txt`。用户已明确同意两个精确主机的无凭据 HTTP 例外。探测不携带认证 Cookie；Cookie 不写入磁盘。系统网络安全配置默认禁止其他 HTTP，代码进一步检查路径、端口、方法和用途。

## 生命周期与错误保护

一次任务最多提交一个登录 POST。当前 Wi-Fi 已联网时立即结束。HTTP 自动重定向、代理、缓存、认证器和自动重试关闭。两个探测只要有一个返回预期正文，就按目标 Wi-Fi 已联网处理。

任务总时限 75 秒；探测连接/读取时限 3/4 秒，单请求总时限 8 秒；Portal 连接/读取时限 4/6 秒，单请求总时限 12 秒。正文分别限制为 64 KiB 和 200,000 字节。

同一应用进程通过 LoginCoordinator 共用一个 LoginEngine、AndroidWifiAccess 和 SecureConfigurationStore，首页、轻量认证页和磁贴入口跨页面去重，不排队认证。网络、地址、路由、DNS 或校园 Wi-Fi 身份变化会使当前租约失效并取消请求。后台取消、旋转保留任务，前台会话触发一次自动检查；权限/系统设置返回不重复自动提交。任务结束注销任务回调、取消请求、清理 Cookie 并释放连接池。界面另有前台只读网络观察器，显示连接变化并使旧列表/在线提示失效；进入后台即注销，不发送探测请求或启动认证。

登录 POST 前先原子保存 `UNVERIFIED` 标记，避免进程在提交后退出时下一次自动重复认证。实际联网复核成功才清除此标记。错误凭据保存 `CREDENTIALS`，显式保存配置才解除。人工状态和复核失败阻止后续自动提交，允许用户处理后手动检查；错误凭据即使手动检查也不再提交，直到保存配置。只读刷新不解除保护。

## 安全存储与权限

账号、密码、服务和设置整体使用 AES-256-GCM 加密，密钥由 Android Keystore 生成且不可导出；每次加密使用新 IV 和固定版本 AAD。密文位于 `noBackupFilesDir/account.enc`，AtomicFile 负责替换和失败回滚。禁止云备份，并为旧备份和设备迁移明确排除数据。

密文损坏/密钥丢失会提示重新配置，不在读取时覆盖文件或恢复为空密码。显式保存新配置可修复。配置版本用于阻止旧任务覆盖新配置。应用不记录请求、原始响应、异常细节或凭据日志；敏感对象输出固定遮挡文本。密码不使用 `rememberSaveable` 或 SavedStateHandle。

Keystore 保护本地保存内容，不能改变学校 HTTP 和旧式密码格式的传输安全属性，不宣称端到端加密。

认证部分请求 INTERNET、ACCESS_NETWORK_STATE、ACCESS_WIFI_STATE 和前台粗略/精确位置权限。精确位置与系统定位用于读取 Wi-Fi 名称，不调用位置坐标 API。Android 12+ 使用 FLAG_INCLUDE_LOCATION_INFO 网络回调；Android 10/11 使用公开兼容接口且只接受唯一 Wi-Fi。未获得可确认身份就停止，不将“附近设备”权限当成读取 SSID 的普遍替代。6B 应用更新额外声明 REQUEST_INSTALL_PACKAGES，仅在用户安装更新时引导系统授权，不申请存储或后台权限。

当前 compile/target SDK 36，min SDK 29。针对 SDK 37 时需按官方规则增加本地网络权限，当前版本不提前请求该权限。

## 本地构建

固定版本见工程 Gradle 文件。构建工具链为 JDK 17、Gradle 8.13、AGP 8.13.2、平台 API 36、Build Tools 35.0.0。Gradle Wrapper 固定下载 URL 和 SHA-256。

已安装 Android Studio/SDK 的开发环境，在配置好 JAVA_HOME 和 ANDROID_HOME 后，可直接进入 `android` 执行：

```powershell
.\gradlew.bat :core:test :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest
```

本机 Windows 的中文项目路径在 JDK 17 的 Gradle 测试进程中导致 ClassNotFoundException；提供独立构建入口，将 Android 源码同步到用户目录的英文临时路径，构建产物和报告复制回原项目，不移动或重写原源码：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_bootstrap.py
# 阅读并接受 Android SDK 条款后，安装所需平台与工具。
# 当前官方工具提供 android.exe；--no-metrics 关闭 CLI 指标采集。
.\.cache\android-tools\sdk\cmdline-tools\latest\bin\android.exe --no-metrics --sdk="D:\校园网自动化\.cache\android-tools\sdk" sdk install "platforms;android-36" "build-tools;35.0.0" "platform-tools"
.\.venv\Scripts\python.exe -X utf8 tools\android_build.py
```

`android_bootstrap.py` 从 Google 官方仓库元数据下载并校验 SDK 工具，从 Gradle 官方站下载并校验 Gradle；不自动接受 SDK 条款。本次用户已明确阅读、接受条款并授权 SDK 安装。构建脚本只设置子进程环境，不改全局变量。自动探测到的本机 JDK 为 PyCharm 自带 JDK 17，也可自行指定 JAVA_HOME。

本机临时目录为 `%USERPROFILE%\.cache\suse-campus-build`，Gradle 缓存为 `%USERPROFILE%\.cache\suse-campus-gradle`，工具下载位于项目 `.cache/android-tools`。第六阶段 6A 已授权本地 Release 构建工具开发与无密钥验证；不含推送或 CI 发布。

跨语言和旧客户端回归：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_protocol_vectors.py --check
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 tools\android_verify.py
```

调试 APK 预期位置为 `android/app/build/outputs/apk/debug/app-debug.apk`；设备测试 APK 为 `android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk`。实际是否成功、测试数量与校验值以本次完成报告为准。

`android_verify.py` 检查 APK 签名、版本、归档完整性、学校 HTTP 例外、备份限制、测试结果及 lint 错误，输出机器可读报告至 `build/android/verification.json`。

## 设备验证

单元测试采用合成数据和本地 MockWebServer，测试 SocketFactory 将连接限定在回环地址。不会连接学校服务器或使用真实账号。

`app/src/androidTest` 的真实 Keystore 和 Compose 测试需要 Android 设备。连接测试设备后执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_build.py :app:connectedDebugAndroidTest
```

现场验收清单：

- Android 10/11 与 Android 12+ 的精确权限、定位开关、拒绝和永久拒绝后的恢复。
- 校园 Wi-Fi 未认证且移动数据可用时，Portal 和联网复核均经过目标 Wi-Fi。
- 真实服务列表、中文/特殊字符密码、真实登录及已经联网不重复提交。
- 断开、切换 Wi-Fi、校园内漫游、修改配置和后台切换时取消旧操作。
- 凭据错误保护跨重启保持，刷新列表不解除；明确保存配置可解除。
- 认证接受但外网不可用、校内服务、VPN/私有 DNS 导致的失败提示。
- 手机/平板、横屏、系统大字体、深色模式和屏幕旋转。

没有真机测试时，上述项目不能记为通过。不同厂商兼容性不能由模拟 HTTP 测试推断。

## 第三方组件

Android 新增 Kotlin、Coroutines、Serialization、AndroidX/Compose、OkHttp/Okio、jsoup，以及测试用 JUnit、MockWebServer、Robolectric 和 AndroidX Test。主要许可为 Apache-2.0（Kotlin/AndroidX/OkHttp）、MIT（jsoup）、EPL-1.0（JUnit 4，仅测试）。APK 的 assets 中附第三方说明、Apache-2.0 正文及 jsoup 许可，同时保留依赖原有 META-INF 许可和 OkHttp NOTICE；未新增项目整体许可证。


## 第二阶段：小组件与快捷登录

第二阶段最终版本为 0.2.1（versionCode 3），当时保留包名、Keystore alias、账户文件和本地调试签名，Debug 间覆盖安装可保留第一阶段配置。第六阶段准备版本为 0.3.0（versionCode 4）；首次换用正式签名的迁移规则见文末。

`CampusApplication` 的依赖容器只持有一份存储、网络适配、引擎和 `LoginCoordinator`。协调器以互斥锁序列化开始/加入、取消及保存。显式登录可取消并等待只读刷新结束；已有登录任务则所有入口加入相同任务。结果带任务标识，不能将旧成功当成本次结果。网络请求与协议仍由第一阶段核心执行。

`QuickLoginActivity` 为不导出的 singleTask Activity，使用独立 taskAffinity 并从最近任务排除，不使用 noHistory。旋转通过 ViewModel/SavedStateHandle 仅保留任务标识和是否已经启动，不保存凭据；重复 Intent 加入已有任务。成功先写历史和更新小组件，再展示约一秒并关闭；失败显示重试、配置及权限入口。进程结束后不重启认证。

应用 Activity 生命周期统一决定是否仍在前台；页面间交接不会取消共享工作，真正返回桌面或锁屏才取消。权限和设置返回不额外触发自动检查。首页的只读网络观察仍只在首页前台存在。

`SmallLoginWidget` 和 `WideLoginWidget` 使用原生 RemoteViews；通过显式、不可变的 Activity PendingIntent 直接打开轻量页，不通过广播中转启动。小组件提供旧版 dp 最小尺寸与 Android 12+ 目标网格属性、夜间颜色和辅助功能说明。updatePeriodMillis=0。添加、尺寸变化、恢复、重新添加只重绘，不认证。一个恢复广播可能依次触发 onRestored/onUpdate，异步 PendingResult 按整个广播领取并释放一次。

`QuickResultStore` 使用 noBackupFilesDir 的独立原子文件，仅保存枚举状态码、时间和任务标识，无账号、密码、服务、网络参数或原始服务器文本。显示“上次检查：MM-dd HH:mm · 结果”，从不宣称缓存实时有效。遗留 REQUESTED 在新进程中解释为 INTERRUPTED。配置保存后显示需重新检查。小组件和磁贴刷新只读取该记录，不解密账号。

`LoginTileService` 受 BIND_QUICK_SETTINGS_TILE 保护，未设置独立进程。仅在控制中心监听期间收集状态，onStopListening/onDestroy 取消收集。锁定时先 unlockAndRun；API 34+ 使用 startActivityAndCollapse(PendingIntent)，29–33 的唯一可用 Intent 重载封装于明确版本分支，针对该兼容方法局部说明 lint 例外。仅快捷入口的显式、不可变 PendingIntent 在 API 35+ 授予必要的 creator 启动许可；API 36 使用公开 ALLOW_ALWAYS，API 35 使用当时的 ALLOWED 常量。令牌仅交给用户操作的 Launcher/SystemUI，不对其他入口全局放开。启动被拒绝时提示通过 App 重试，不绕过系统限制。历史成功使用 INACTIVE，只有活动任务使用 ACTIVE，不将磁贴作为持续联网开关。

## 第二阶段测试环境

Robolectric 4.16 用于 Android 10、14、16（API 29/34/36）的组件模拟，属于 JVM 模拟测试，不是 Android 模拟器，也不能替代真实 Launcher/SystemUI 验收。Android 16 的 Robolectric 系统镜像要求 Java 21，因此仅测试进程使用隔离 Microsoft JDK 21；Gradle 和应用 Java/Kotlin 字节码继续使用原有 Java 17 基线。

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_test_jdk.py
.\.venv\Scripts\python.exe -X utf8 tools\android_build.py
```

测试 JDK 从 Microsoft 官方 HTTPS 地址下载并核对 SHA-256，不安装到系统，不改 JAVA_HOME。构建脚本将 SUSE_TEST_JAVA_HOME 仅传给子进程；若自行直接运行 Gradle，可将该变量指向本地 JDK 21。所有设备测试使用合成数据；本轮是否连接设备与实际执行结果以第二阶段报告为准。

第一阶段用户已反馈真实小米手机校园网认证成功；该记录不覆盖第二阶段小组件、磁贴、锁屏和桌面恢复的实机表现。


相关系统接口依据：[AppWidget 尺寸](https://developer.android.com/develop/ui/views/appwidgets/layouts)、[TileService](https://developer.android.com/reference/android/service/quicksettings/TileService)、[ActivityOptions 后台启动模式](https://developer.android.com/reference/android/app/ActivityOptions)。


## 0.2.1：系统小组件添加确认

`WidgetPinController` 将 INITIAL / WAITING / SUCCESS / MANUAL 分开处理。requestPinAppWidget 返回 true 只进入等待，收到匹配成功回调才显示添加成功；用户取消没有回调，保持等待，不定时重试或推断失败。重复普通点击合并，显式重新请求可以选择尺寸并更换令牌，旧回调失效。

`AndroidWidgetPinGateway` 用公开接口申请对应 provider，附上不包含登录动作的静态预览。成功回调为指向不导出 WidgetPinResultReceiver 的显式、不可变广播 PendingIntent；令牌在原 Intent.data 中，不依赖系统填入的 widget ID。接收器只通知添加控制器，不访问认证容器或账号。请求状态以枚举、尺寸和令牌保存在 noBackupFilesDir 的独立原子文件，支持确认期间进程重建；没有账号或网络参数。添加系统页面属于外部交互，不因返回 App 而额外触发自动检查。

无法申请或发生异常时显示手动步骤，不伪称已打开确认页；返回桌面使用 ACTION_MAIN/CATEGORY_HOME，只由用户按钮触发，不自动抢走系统确认框。不同 Launcher 是否展示确认页仍由其决定，没有通用接口强制打开厂商小组件列表。

新增纯控制器和 API 29/34/36 组件模拟测试，包括等待、成功、取消无回调、不可用、异常、显式重试、旧令牌、进程重建和无自动认证。Robolectric 不自动实例化本测试中的清单广播接收器，因此测试先发送 PendingIntent、检查其记录的广播及组件，再将同一广播交给生产接收器；这验证载荷和处理逻辑，不代替真实 Launcher 回调交付验收。

## 第六阶段 6A：发行构建

当前 Android 版本由 `android/version.properties` 统一维护为 `0.3.0 / 4`，稳定 Tag 为 `android-v0.3.0`。包名不变；Windows/macOS 版本及工作流不变。

`tools/android_release.py --unsigned` 执行 Release 测试、lint、构建与中间产物检查。默认不带 `--unsigned` 的入口需要维护者本人创建的密钥及预先登记的正式证书指纹，否则停止。正式签名在 Gradle 外完成，源码同步使用允许清单，Gradle 子进程不接收签名环境变量。

`tools/android_verify.py` 保留 Debug 检查，新增 `--variant release`、`--apk`、`--expected-sha256`、`--tag`；只有显式 `--allow-unsigned` 才检查未签名 Release。检查对象包括 APK 内实际编译的清单、网络安全和备份 XML，以及签名、版本、ZIP 和 16 KiB 对齐，不只检查源码声明。

操作见[正式签名与迁移](android-signing.md)，版本信息接口和 6B–6D 规划见[发行架构](android-release-architecture.md)，本轮结果见[6A 开发报告](android-phase6a-report.md)。首次从 Debug 换正式签名需卸载并重新配置；目前只有未签名中间产物时无需操作手机。

### 三层验签回归与真实 SDK 集成测试

V2/V3 验证修复与诊断保留结果见[验签修复报告](android-signature-verification-fix.md)。普通 Python 回归包含验签策略、诊断保留与清理测试；真实 SDK 测试需显式启用，并预先准备固定提交、固定 SHA-256 的 AOSP 公开预签名 APK：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\android_signature_fixtures.py
$env:SUSE_ANDROID_SIGNATURE_INTEGRATION = '1'
try {
  .\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -q
  if ($LASTEXITCODE -ne 0) { throw '回归测试失败。' }
} finally {
  Remove-Item Env:\SUSE_ANDROID_SIGNATURE_INTEGRATION -ErrorAction SilentlyContinue
}
```

下载工具仅下载清单中的公开 APK，不获取或生成任何私钥；数据在 `.cache/android-signature-fixtures`，测试结果在 `build/android-signature-tests`，均不进入 Git。加 `--check` 可只校验本地缓存、不联网。测试自身不下载文件；未显式启用时真实 SDK 集成测试显示跳过，不能据此声称已验证。

## 第六阶段 6B：应用内更新

实现与现场验收说明见 [6B 开发报告](android-phase6b-report.md)。Android `app/.../update` 独立负责设置、版本来源、下载、归档身份检查及系统安装，不进入认证 core 或 SecureConfigurationStore。

`android/release-identity.json` 的公开信任信息通过 Gradle 生成 Android 资源；不使用 BuildConfig Java 代码生成，也不复制私钥。`android/update-sources.json` 单独提供可为空的默认 Gitee 仓库。构建脚本只允许其唯一公开字段，实际 APK 核验也检查编译资源与配置一致。

默认采用用户手动检查，不在 App 启动或快捷认证时额外发更新请求。更新 Activity 离开前台时取消请求，旋转保留任务；安装授权返回时重新检查权限并再次核对文件。普通进程重启不恢复下载或信任旧缓存文件，用户可重新检查下载。

6B 保留 `0.3.0 / code 4`，没有重新正式签名或公开发行。既有正式 APK 位于 `release/android/android-v0.3.0`，不被 Debug/未签名构建覆盖。未来公开更新需要维护者另行确认递增 versionCode，不能把本阶段同 code 构建作为应用内“新版本”推出。


## GitHub 单渠道更新起点：0.4.0

当前候选已调整为 0.4.0 / code 5，新安装默认 GitHub，并增加首页前台自动更新提醒；此前 6A/6B 小节保留为历史阶段记录。Gitee 默认仍为 null。实现、测试、签名状态及两版手机验证流程见 [GitHub 单渠道实施报告](android-github-bootstrap-report.md)。
