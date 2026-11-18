# Android 第六阶段 6A 开发报告

日期：2026-11-17。

## 结论与验收范围

已完成不需要维护者正式密钥或远程授权的 6A 工作：独立版本配置、未签名 Release 构建、正式签名入口、发行身份及 APK 核验、失败保护、签名与迁移操作指南，以及 6B–6D 架构规划。

当前 Android 准备版本为 **0.3.0 / versionCode 4**，Tag 为 `android-v0.3.0`，包名保留 `io.github.themingverse.susecampus`。官方来源记录为 `TheMingverse/suse-campus-login`。正式证书指纹仍是 `null`，未生成或读取维护者的正式私钥，没有产出已正式签名、可安装的发行 APK。

## 现有仓库检查

- 实施前 Android 实际为 0.2.1 / code 3，已有 102 项 JVM 测试和 Debug 构建核验；用户请求中提及的 0.2.0 属于更早版本。
- Windows 版本来自 `campus_login.__version__`，为 1.1.3；Windows 打包与核验工具独立。
- macOS 使用既有原生打包脚本和 `v1.2.0-macos-beta.1` Tag，现有 `.github/workflows/macos.yml` 包含 Windows 回归、两种 Mac 架构构建和工件上传，没有 Android 正式签名与发布流程。
- 中英文主 README 的 Windows 下载使用仓库全局 `/releases/latest`，因此后续 Android Release 需要 `make_latest=false`；Android 自身不能用全局 latest 判断更新。
- 本地 origin 仍为旧用户名 `tsiskjsjs532-hash` 对应地址；用户已确认改名为 TheMingverse。本轮未连接、验证或修改远程仓库。
- 原有 `.gitignore` 修改、Android 工程及工具原本就有未提交内容；未清理或覆盖这些成果。核验报告记录 HEAD 为 `5d3c776cb9acbf6c9736eeebacf7634c1996b739`，同时明确 `workingTreeDirty=true`、`sourceIncludesUncommittedChanges=true`，该 HEAD 不能代表完整的当前 Android 源码。

## 实现内容

### 版本与构建

新增 `android/version.properties` 统一维护版本；Gradle、发行和核验脚本共同读取。稳定版 Tag 使用 `android-v<versionName>`；预发布支持 `alpha.N / beta.N / rc.N`。versionCode 从当前 3 增至 4，后续每次发行递增，包括预发布转正式版，不关联桌面版或 Actions 运行次数。

Release 显式关闭调试，不开启新的混淆、资源裁剪，不升级依赖。应用业务 Kotlin、认证 core、账号存储、权限清单和网络规则均未修改。

`tools/android_release.py --unsigned` 可完成无密钥 Release 测试、lint、构建、检查与中间产物导出。默认发行入口需要公开证书指纹和维护者本人的密钥，缺少信息时停止，不回退 Debug 签名。

### 密钥隔离与交付保护

`android/release-identity.json` 只允许包名、官方仓库、公开证书 SHA-256 三个字段，不允许夹带密码配置。私钥必须位于仓库与构建缓存之外；发行方案为 PKCS12、RSA 3072、固定别名、10,000 天有效期，具体建钥由维护者本人操作。

源码同步改为允许清单，排除本机签名和配置文件；以前由脚本复制、如今不再允许的文件，只在已记录且经路径检查的临时副本内移除。不会清理用户原文件或任意目录。Gradle 子进程剔除所有 `SUSE_ANDROID_*` 签名变量。密码由隐藏输入或受保护环境变量提供，只传给签名工具，不出现在命令参数或报告中。

使用 SDK 官方 apksigner JAR，通过 Java 直接启动，避免 Windows 批处理解释密钥路径。签名前后检查 16 KiB 文件对齐，启用 v2/v3 签名；核验通过后不修改 APK。

正式交付通过同磁盘临时目录完成后整体改名，现有同 Tag 发行目录不会被覆盖。未签名包只进入 build 下的中间产物目录，不生成正式版本信息或正式校验文件。

### 实际 APK 核验

检查 APK 内部包名、版本、SDK，读取编译清单确认调试、备份、权限及组件导出状态；按实际资源 ID 查找网络安全与备份 XML，同时兼容 Release 优化后的资源文件名。检查两种小组件没有周期刷新。

还检查 ZIP 完整性、重复条目、必要代码与许可文件、不应打包的密钥或凭据文件、对齐、签名有效性及预先登记的证书指纹。通过快照检查和复制前后哈希，防止被检查文件与交付文件内容不一致。Release 不信任 APK 自报的证书，也不把 Debug 证书视为正式身份。

签名成功后才生成 `android-release.json`、`SHA256SUMS.txt` 与验证报告，版本信息区分文件 SHA-256 和签名证书 SHA-256。当前未配置正式身份，没有生成上述正式发行目录。

## 验证结果

| 检查 | 本轮结果 |
| --- | --- |
| 原有 Android Debug JVM 测试 | 102 通过，0 失败、错误或跳过；已用 `--rerun-tasks` 强制重跑 |
| Android Release JVM 测试 | 102 通过，0 失败、错误或跳过 |
| 原有 Python/Windows 与新增工具测试 | 167 通过 = 原有 135 + 新增 32 |
| 跨语言协议样例 | 通过，仅合成数据 |
| Debug / Release lint | 各 0 错误、24 警告 |
| Debug APK / 设备测试 APK | 构建成功，签名检查通过 |
| 未签名 Release APK | 构建、版本、编译安全配置、ZIP、许可和对齐检查通过 |
| 真实 APK 拒绝路径 | 8 项按预期拒绝，见下文 |
| Git 空白检查 | 通过；仅提示既有 LF/CRLF 转换信息 |
| Android 真机 | adb 列表为空，未执行设备测试或真校园网认证 |
| 正式签名与安装 | 等待维护者密钥，未执行 |

Debug 和 Release 的 102 项均由共享核心 43 项加对应变体 App 59 项组成，不应宣称为 204 项不同逻辑测试。组件模拟仍为 API 29/34/36 的 Robolectric 测试，不是手机桌面或系统安装器的现场验收。

新增 32 项发行工具测试覆盖非法/缺失版本、Tag 冲突、未配置指纹、实际清单检查逻辑、权限扩大、资源映射、备份与 HTTP 规则、密钥文件排除、临时复制路径保护、密码遮挡、签名身份不符、错误哈希和原子导出。正向正式签名路径使用模拟工具响应验证流程；没有因此生成临时密钥，也不将其记为真实签名成功。

另外用实际构建 APK 验证 8 项拒绝路径：Debug APK 被当作未签名 Release、错误文件哈希、Windows Tag、缺少可信证书、真实 Debug 签名身份、真实未签名 APK 的正式签名检查、真实 APK 截断副本，以及实际 APK 与内存中设置的错误期望版本不符。原 APK 和正式身份配置未为这些检查作修改。

24 条 lint 警告涉及依赖版本建议、固定文案、紧凑字号、旧系统忽略新版属性及 KTX 建议；没有新增 lint 错误。构建仍有原有路径检查实验选项、Kotlin jvmTarget/测试 API 弃用、原生库未剥离符号等提示。本轮不顺带升级工具链或修改界面。

## 产物与报告

未签名中间产物：

```text
build/android-delivery/SUSE-CampusLogin-Android-v0.3.0-unsigned.apk
字节数：22764539
SHA-256：980109c3c17a28a3be511456ba8f430e4c5a54f06a3b4b32b935e308413a22e9
```

**该文件不可直接安装或作为正式 APK 发布。**报告中 `signatureVerified=false`、`releaseReady=false`、`officialSigningIdentityConfigured=false` 均属预期，不是“正式签名已经完成”。

Debug 构建用于回归，内部版本同为 0.3.0 / code 4，原始输出为 `android/app/build/outputs/apk/debug/app-debug.apk`，SHA-256 为 `1a74b6aa7389451af28a1ae6e094021b4f90c47fa75686c4b71a4d78fb3622b8`；它仍是 Debug，不可冒充正式发行包。

机器可读证据：

- `build/android/verification.json`：Debug 核验及质量结果。
- `build/android/release-verification.json`：未签名 Release 核验及质量结果。
- `build/android/rejection-checks.json`：8 项真实 APK 拒绝检查。
- `android/core/build/test-results/test/`、`android/app/build/test-results/testDebugUnitTest/`、`testReleaseUnitTest/`：JUnit 报告。
- `android/app/build/reports/lint-results-debug.xml`、`lint-results-release.xml`：lint 明细。

主要执行命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_build.py :core:test :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest -- --rerun-tasks
.\.venv\Scripts\python.exe -X utf8 tools\android_release.py --unsigned --tag android-v0.3.0
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -X utf8 tools\android_protocol_vectors.py --check
.\.venv\Scripts\python.exe -X utf8 tools\android_verify.py
.\.venv\Scripts\python.exe -X utf8 tools\android_verify.py --variant release --allow-unsigned --apk build/android-delivery/SUSE-CampusLogin-Android-v0.3.0-unsigned.apk
git diff --check
```

不带 `--unsigned` 的发行入口也已检查，因正式指纹未配置而按预期返回失败，在构建和读取密钥之前停止。

## 维护者本人待办与后续停点

按[正式签名与首次迁移指南](android-signing.md)本人创建密钥、设置密码、保存两份独立加密备份、验证备份、登记公开指纹，再本人完成首次正式签名。密钥及密码无需交给 AI。之后才具备正式签名、正式证书匹配与手机安装的真实验证条件。

正式包核验通过前，不要卸载现有 Debug。首次换签名后需要重新输入账号、选择服务并添加小组件/磁贴；旧账号密文不能脱离原手机 Keystore 恢复。后续同一签名、更高 code 的正式版可正常覆盖升级。

[发行架构文档](android-release-architecture.md)已记录 6B 更新模块、独立 HTTPS 与前台生命周期、必要安装授权、6C Actions/Gitee 同步和 6D 真机验收方案。本轮未添加更新 UI、安装权限、后台服务、周期检测、Wi-Fi 自动认证、Actions YAML 或镜像同步程序。

Windows/macOS 生产源码、既有发布脚本、工作流及主 README 均未修改。没有 Git 提交、Tag 创建、推送、远程地址更改、远程仓库操作、APK 上传或公开发布。完成本报告后停在 6A，等待用户验收。
