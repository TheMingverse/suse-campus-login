# Android 第一阶段完成报告

日期：2026 年 11 月 16 日。

结论：Android 第一阶段代码、核心与应用单元测试、静态检查和调试 APK 构建已完成。尚无 Android 设备测试和真实校园网登录结果，当前交付用于安装试用及现场验收，不能描述为已经完成所有设备验证。

## 交付文件

- 工程：`D:\校园网自动化\android`
- 应用 APK：`D:\校园网自动化\android\app\build\outputs\apk\debug\app-debug.apk`
- 设备测试 APK：`D:\校园网自动化\android\app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk`
- 开发说明：`docs/android-development.md`
- 简短使用说明：`android/README.md`
- 机器可读核验报告：`build/android/verification.json`

应用包名 `io.github.themingverse.susecampus`，版本 `0.1.0`，最低 Android 10（API 29），目标 API 36，使用本地调试签名。

应用 APK SHA-256：

```text
bbce150487b5d0da6b33ba58774a756283620b63d6c08541e06351877b119aeb
```

## 工程目录

```text
android/
├─ app/
│  ├─ src/main/kotlin/.../
│  │  ├─ MainActivity.kt
│  │  ├─ CampusScreen.kt
│  │  ├─ CampusViewModel.kt
│  │  ├─ AndroidWifiAccess.kt
│  │  ├─ WifiOverview.kt
│  │  └─ SecureConfigurationStore.kt
│  ├─ src/main/res/xml/        HTTP 例外、备份与迁移规则
│  ├─ src/main/assets/         第三方说明与许可
│  ├─ src/test/                前台会话逻辑测试
│  └─ src/androidTest/         Keystore 与 Compose 设备测试
├─ core/
│  ├─ src/main/kotlin/.../
│  │  ├─ Models.kt
│  │  ├─ Protocol.kt
│  │  ├─ PortalClient.kt
│  │  ├─ BoundHttpTransport.kt
│  │  └─ LoginEngine.kt
│  └─ src/test/                协议、流程、模拟 HTTP 与跨语言样例
├─ gradle/wrapper/
├─ gradlew / gradlew.bat
└─ Gradle 配置与 README
```

主要文件作用与接口说明见开发文档。额外新增四个工具：`android_bootstrap.py` 下载并校验构建工具；`android_build.py` 解决本机中文路径构建问题；`android_protocol_vectors.py` 建立 Python/Kotlin 合成协议一致性；`android_verify.py` 核验 APK 和测试报告。

## 已实现功能

- 中文账号配置、密码加密保存、动态运营商列表、只读刷新及精确服务匹配。
- 网络不可用时保存加密草稿；已有配置保留服务名，不提供猜测的服务 ID。
- 手动检查并登录、取消本次操作、前台一次自动检查及可关闭的设置。
- Wi-Fi 与默认网络分离，探测、DNS、认证和复核均绑定目标 Wi-Fi 的 Network；失败不回落移动数据。
- 校园 Wi-Fi 名称与可信 Portal 双重限制，按本次跳转获取连接参数。
- 学校 pageInfo、getServices、login 流程、旧式 RSA、中文与表情 UTF-16 处理、双重编码及错误分类。
- 已联网不重复认证；未知入口/参数/认证方式停止；任务去重、网络或设置变化取消。
- 认证成功后复核同一 Wi-Fi；认证接受但互联网不可用时单独提示，不假报联网成功。
- 错误凭据保护跨重启保存，只读刷新不解除；显式保存配置才解除。POST 前保存保护标记，进程意外结束后不默认重复认证。
- Keystore AES-256-GCM、随机 IV、原子保存、密文损坏与密钥丢失提示、备份和设备迁移排除。
- 手机/平板布局、深浅色、可滚动页面；前台只读观察连接变化，及时清除旧在线状态和服务列表。
- 无后台认证服务、定时检查、开机自动任务、小组件或厂商专有接口。

两个外部测网主机的 HTTP 例外由用户明确同意；请求不含账号密码和认证 Cookie。凭据只允许提交至确认的学校接口。日志与错误提示不输出原始服务器回复或敏感认证 URL。学校 HTTP 和旧式密码协议不等于现代端到端加密。

## 实际验证结果

| 检查 | 结果 |
| --- | --- |
| Python 现有回归测试 | 135 项通过 |
| Kotlin 协议测试 | 8 项通过，其中含原有五组 RSA 数据 |
| Kotlin 一次性流程测试 | 18 项通过 |
| HTTP 传输与安全边界测试 | 8 项通过 |
| Android 前台会话单元测试 | 2 项通过 |
| Python/Kotlin 合成协议样例核对 | 通过 |
| Android lint | 0 错误，9 警告 |
| 应用调试 APK | 构建成功 |
| 设备测试 APK | 构建成功，尚未运行 |
| APK 签名 | 应用与测试包校验通过；应用使用 v2 签名 |
| APK ZIP 完整性与资源 | 通过，第三方许可已包含 |
| APK 版本与最低系统 | API 29 / target 36，与工程一致 |
| Git 空白错误检查 | 通过 |
| adb devices -l | 无连接设备 |

lint 的九条警告为八条依赖存在较新版本提示和一条 KTX 写法建议；没有权限/API 等级错误。按确认的版本基线固定依赖，没有为消除版本提示临时升级依赖。

实际使用的主要命令（项目根目录）：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_bootstrap.py
.\.venv\Scripts\python.exe -X utf8 tools\android_protocol_vectors.py
.\.venv\Scripts\python.exe -X utf8 tools\android_protocol_vectors.py --check
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -X utf8 tools\android_build.py
.\.venv\Scripts\python.exe -X utf8 tools\android_verify.py
.\.cache\android-tools\sdk\platform-tools\adb.exe devices -l
git diff --check
```

构建脚本实际调用 Gradle 8.13，执行：

```text
:core:test :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest
```

最终一轮结果为 `BUILD SUCCESSFUL`。APK 签名另外调用官方 `apksigner verify --verbose`，版本与权限使用官方 `aapt dump badging` 核验。

## 已处理的构建问题

- 缺少 SDK：使用官方工具下载平台 API 36、Build Tools 35.0.0 和 platform-tools。接受许可前询问用户，得到明确接受条款和安装授权后才继续安装。
- 新版 SDK 安装器命令变化：使用其实际提供的 `android.exe --no-metrics ... sdk install` 命令安装。
- 中文项目路径：Android 插件提供路径检查开关，但 JDK 17 的测试进程仍出现 ClassNotFoundException；改为英文临时路径编译，产物复制回项目。源码保留原位置。
- OkHttp DNS 适配编译错误：改为明确实现 Dns 接口，后续构建和测试通过。
- API 29 的静态检查提示：使用兼容的未知 SSID 判断，消除该 API 等级警告。
- aapt 对绝对中文输入路径解析失败：核验脚本改用相对 APK 路径，后续核验通过。

## 尚未完成验证和问题边界

目前没有阻塞构建或单元测试的已知严重问题，但以下项目没有真机证据：

1. Android Keystore 在真实设备上的保存、恢复、损坏处理和失败回滚；对应设备测试已编译。
2. Compose 界面的真实渲染、手机/平板、大字体、旋转和权限交互；本轮没有设备截图或视觉验收。
3. 校园 Wi-Fi 下真实账号认证、运营商服务和认证后互联网访问；测试未使用真实密码。
4. Wi-Fi 和移动数据同时开启时，真实设备的网络绑定行为；本地测试证明传输代码使用注入的 Wi-Fi SocketFactory/DNS、失败不走默认路径，但不能替代真机。
5. 不同品牌系统对 SSID 权限、定位开关、网络切换、VPN和私有 DNS 的实际表现。

适配范围仍为已经确认的学校认证系统及两个校园 Wi-Fi 名称，没有扩大到自贡或未经确认的其他认证系统。

## 真机验收顺序

先安装应用调试 APK，连接校园 Wi-Fi，再输入账号密码。不要把真实密码发送到聊天或写入测试文件。

1. 首次配置并刷新服务，验证可选名称来自学校。
2. 开启移动数据，点击登录，确认校园 Wi-Fi 本身可访问互联网。
3. 已联网时再次检查，确认不重复提交。
4. 测试权限拒绝、定位关闭和设置入口；检查非校园 Wi-Fi 不认证。
5. 认证期间切换 Wi-Fi、返回桌面和修改配置，确认旧任务停止。
6. 使用自己的测试条件检查凭据失败保护，避免反复提交错误密码触发学校限制。
7. 检查再次打开自动执行一次、关闭开关后只允许手动执行。
8. 在手机/平板、横屏、大字体和深色模式下检查布局。

连接专用测试设备后，可运行 `python tools/android_build.py :app:connectedDebugAndroidTest`。该测试只使用合成凭据和独立测试密钥，不访问学校认证服务器。

## 现有客户端保护与下一阶段

Windows/macOS 生产代码和原发布包未修改。Git 中仅修改根忽略规则，新增 Android 工程、四个本地工具及 Android 文档；没有提交、推送或发布远程仓库，没有读取个人配置或真实密码。

先收集上述真机验收结果并处理差异。用户检查第一阶段后，再基于现有有限认证接口讨论桌面小组件、可选 Wi-Fi 自动认证和定时任务；本次未实现这些功能。
