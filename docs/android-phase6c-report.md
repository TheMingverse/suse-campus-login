# Android 第六阶段 6C-1 开发报告

日期：2026 年 11 月 17 日（北京时间）。本轮仅完成不依赖真实 Gitee 仓库的 6C-1，完成后停止，等待维护者验收。

## 1. 交付状态与验证边界

| 类别 | 本轮结果 |
| --- | --- |
| 已实现 | 本地四文件发行包预检查、导出前强制预检查、离线双目录比较、GitHub Android 附件过滤完善 |
| 自动化测试通过 | Python 238 项，0 失败/错误/跳过；Android Debug/Release 各 178 项；两种变体 lint 各 0 错误、27 条既有警告 |
| 真实环境已验证 | 用本机真实 SDK 对既有正式 APK 重新进行默认/V2/V3 验签、包信息读取、ZIP 和对齐检查；GitHub 官方仓库匿名 GET 返回 HTTP 200 |
| 本地真实 APK 比较 | 正式发行目录与临时本地副本比较 PASS；这不是远程 Gitee 同步验收 |
| 仍需 Gitee 仓库 | 匿名 Release/附件接口、真实 HTTPS/CDN 下载、双平台远程下载一致性验收 |
| 仍需 6D 真机验收 | 更新页面、未知来源安装授权、FileProvider、系统安装器、生命周期及校园网现场回归 |
| 首次公开发行 | 未执行；6D 完成并经维护者另行确认前不得进行 |

保持 versionName `0.3.0`、versionCode `4`、applicationId `io.github.themingverse.susecampus`、Tag `android-v0.3.0`、正式证书与 origin 不变。`android/update-sources.json` 仍为 `{"giteeRepository": null}`。

versionName 是用户看到的版本名称；versionCode 是 Android 用来判断升级先后的整数。SHA-256 是文件内容的校验摘要，文件变化后摘要也会变化；证书指纹是签名者的公开身份，不是签名私钥。

## 2. 任务 A：既有发行体系审查结论

本轮先只读检查交接文档、发行工具、配置、现存正式目录及 6B 客户端/测试，确认以下能力已经存在，继续复用：

| 对象 | 原有能力 | 本轮处理 |
| --- | --- | --- |
| `tools/android_release.py` | 构建未签名 Release、Gradle 外签名、签名后立刻记录哈希、审核后暂存并导出、防止覆盖正式目录、失败保留诊断 | 在目录最终导出前增加四文件预检查 |
| `tools/android_verify.py` | APK 和当前源码构建报告审核，Debug/Release 区分 | 增加 `--release-dir`，检查既有发行包；不另造预检查脚本 |
| `tools/android_artifacts.py` | APK ZIP、aapt 包信息/编译清单、SDK、zipalign、证书、三轮验签、安全配置及报告解析 | 增加共享发行包检查函数，复用原有工具调用和签名策略 |
| `android/release-identity.json` | 正式包名、GitHub 仓库与公开证书指纹 | 不修改 |
| `android/update-sources.json` | 编译默认 Gitee 配置，当前未配置 | 不修改，不虚构仓库 |
| `android-release.json` | schemaVersion 1，含包名、版本、Tag、文件名、大小、APK 哈希、证书、官方仓库及源码来源 | 维持协议，严格核对实际 APK |
| `SHA256SUMS.txt` | 发行脚本生成；6B 客户端检查目标 APK 条目唯一且哈希一致 | 增加本地发行目录与两端原始文件内容检查 |
| 6B 更新客户端 | 三档渠道、GitHub 分页筛选、HTTPS 重定向、下载校验、安装前再验、错误分类 | 继续复用，只完善 Android 所需附件过滤并补充测试 |

原发行脚本的 APK、元数据与校验文件均使用已验证 APK 的同一份 SHA-256 和字节数；复制前后还会重新核对哈希。正式证书由公开身份配置固定。版本号来自 `android/version.properties`，原 APK 核验已要求内部版本与它一致。签名报告带有默认/V2/V3 各轮退出码、原始输出、方案状态和证书。

此前缺少对已导出四文件目录的统一复核入口。现在既能独立复核，也会在未来正式发行脚本完成暂存后、进入正式目录前强制运行。

**现存正式 APK 属于 6A，尚不包含后续 6B/6C 的更新源码。** 其历史报告记录 102 项测试和 24 条 lint 警告；这些历史数字没有被本轮 178 项/27 条覆盖。当前新源码通过测试，不代表原正式 APK 已含这些修改。预检查也不证明 APK 与当前工作区源码完全相同；历史源码来源仍如实保留 dirty 状态。

## 3. 任务 B：发行包本地预检查

执行：

```powershell
Set-Location -LiteralPath 'D:\校园网自动化'
.\.venv\Scripts\python.exe -B -X utf8 tools\android_verify.py --release-dir release\android\android-v0.3.0
```

可附加 `--tag android-v0.3.0`；必须与当前版本配置一致。成功输出 JSON，`status` 为 `PASS`，退出码 0；失败输出具体原因并以非零退出码停止。该模式只输出到控制台，不改写原目录、APK 或旧 `verification.json`，也不依赖当前工作区的历史测试报告。

检查内容：

1. 四文件齐全，没有额外 unsigned/debug APK、临时文件或子目录，成员必须是普通本地文件，拒绝符号链接。
2. 元数据 JSON 结构正确，拒绝重复键、错误类型、布尔值冒充整数、错误协议/平台及非法版本。
3. 包名、GitHub 官方仓库、正式证书指纹符合登记身份。
4. versionName、versionCode、Tag 符合当前配置，APK 文件名严格对应版本。
5. 实际 APK 字节数、SHA-256、元数据和 `SHA256SUMS.txt` 一致。
6. 对 APK 的临时只读快照重新运行默认验签、V2 专项（API 24–27）、V3 专项（API 28–32）。三轮均须成功且各轮证书匹配，不能把 V2/V3 改成二选一。
7. 重用 ZIP 完整性/许可文件检查、aapt 实际包名和版本检查、minSdk 29/targetSdk 36 检查，以及 16 KiB 对齐检查。
8. 实际编译清单不是 debuggable 或 testOnly；正式签名指纹和 Debug 证书检查同时生效，未签名 APK 一律拒绝。
9. 旧 `verification.json` 的包名、版本、Tag、大小、哈希、证书、验签状态、ZIP/对齐状态与新实测一致；源码来源与元数据一致，签名后即时哈希若存在也必须一致。
10. 重新解析历史三轮验签原始输出，核对 SDK 范围、退出码、方案状态与证书；不只相信其中的 `passed: true`。
11. 核验结束重算所有发行文件哈希，检查期间有变化则失败。

发行包检查标记为 `distribution-artifact`。它审核已冻结 APK 的身份与完整性；原 `verify_apk` 的当前源码组件、安全资源、编译信任和 FileProvider 审核保持原有要求。这样可以正确检查 6A 发行包，又不会因它没有后来新增的 6B 页面而误判损坏。发行包模式没有声称执行当前源码的全套构建审核。

正式发行脚本将预检查放在临时暂存目录中运行，成功后才导出正式目录。任一步失败，不生成新的正式发行目录；已存在的正式目录继续拒绝覆盖。预检查不会签名或重新签名，也不需要任何签名密码。

`PASS` 只表示本地文件审核通过，结果中明确保留 `publicReleaseAuthorized: false`，不代表已允许公开发布。

## 4. 发行包结构与协议

```text
release/android/android-v0.3.0/
  SUSE-CampusLogin-Android-v0.3.0-release.apk
  android-release.json
  SHA256SUMS.txt
  verification.json
```

`android-release.json` 是客户端读取的机器可读版本信息；`SHA256SUMS.txt` 保存正式 APK 的 SHA-256；`verification.json` 是同次正式构建的核验证据。镜像应原样复制这四个文件，不按平台重新构建、重签或重新生成元数据/证据。

本地完整发行包检查与比较要求四文件齐全。6B 应用内更新仍只下载所需的元数据、校验表和 APK，不会为了此工具改成强制下载 `verification.json`。

本轮实测原 APK：

```text
文件大小：22775875 字节
SHA-256：d85d496f66680a57d2219342176e17ffb0ce2f74fe6ebf3c2115314cd4d5038a
证书指纹：d2311bc8eca941cefe1dfc8a75af476e3de5b230b4622a8820d6191af7452f36
```

原目录四文件检查前后的哈希全部相同，记录于 `build/android/phase6c-summary.json`。本轮没有新建正式发行包。

## 5. 任务 C：双平台发行一致性工具

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\android_release_parity.py --github 'D:\下载\github-android' --gitee 'D:\下载\gitee-android'
```

工具仅访问两个本地目录，不连接 GitHub/Gitee，不需要账号或 Token。目录名可以自选，便于未来比较两边分别下载的附件。它先独立预检查两份包，再比较 Tag、versionName、versionCode、applicationId、文件名、大小、APK 哈希、正式证书和全部元数据字段，并比较四文件原始字节的 SHA-256。

比较模式依据包内声明和实际 APK 检查历史版本，不要求与当前工作区版本相同；两个不同的合法版本依然比较失败。官方身份、版本格式、SDK 和签名要求仍然生效。

| 输出 | 退出码 | 含义 |
| --- | --- | --- |
| `PASS` | 0 | 两个本地完整发行包逐字节一致 |
| `FAIL` | 1 | 单侧预检查失败，或两侧版本/身份/元数据/任一文件不同 |
| `NOT_CONFIGURED` | 2 | GitHub 本地包通过，但没有提供 Gitee 本地下载目录，无法完成比较 |

检查未配置状态：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\android_release_parity.py --github release\android\android-v0.3.0
# 预期 NOT_CONFIGURED，退出码 2；这不是命令故障，也不是同步成功。
```

若 GitHub 本地包本身无效，会先返回 FAIL，避免掩盖问题。`--gitee` 是显式提供本地待比较样本，不等于设置应用默认镜像；即便应用镜像仍为 null，也可以用临时目录测试工具。

单包检查允许 `verification.json` 中 APK 的原构建机路径不同于下载路径，只核对文件名，便于跨机器读取；但两端比较仍要求原 `verification.json` 的字节一致。不要为了下载到另一台电脑而改写路径或时间戳。

结果始终说明 `scope: local-directories-only`、`dualPlatformVerified: false`。即使两份本地样本 PASS，也不能证明远程仓库已经创建、上传或同步。

## 6. 任务 D：GitHub 官方渠道

唯一官方仓库仍为 `TheMingverse/suse-campus-login`。本轮继续使用 6B 的 `GitHubUpdateSource`、`UpdateHttp`、`ApkDownloader`、`ApkVerifier`，没有开发第二套更新客户端。

现有能力已通过代码审查及补充测试复核：匿名 Release 列表分页、只选稳定 `android-v<versionName>`、按 versionCode 选择 Android 版本、不使用仓库全局 latest；APK/元数据/校验表必须属于同一次 Release；下载前仅允许无凭据的 HTTPS 443 地址；301/302/303/307/308 每次跳转重新检查，最多五跳；下载后校验大小、SHA-256、归档包名/版本/证书，再进入 ready 目录。

本轮生产代码只补充一个缺口：在 Android Release 内先筛选目标 APK、`android-release.json` 和 `SHA256SUMS.txt`，再处理其地址和大小。即便同条 Release 意外带有桌面附件，也不会把 Windows/macOS 文件当成 Android 更新下载，或因无关桌面 URL 失败而阻断 Android 检查。必要 Android 附件缺失、重复、不安全 URL、来源不符仍会拒绝。

HTTP 403/404/429/500/503 返回明确服务错误；连接/读取超时和网络中断返回网络错误；哈希/签名/元数据错误保持安全错误，不作为网络问题静默换源。

### 真实只读核查

2026 年 11 月 17 日 21:53（北京时间），未附带 Authorization 的公开 GET：

```text
https://api.github.com/repos/TheMingverse/suse-campus-login/releases?per_page=100&page=1
HTTP 200
公开 Release 数：2（一页完整）
稳定 Android Release 数：0
```

两条为 `v1.2.0-macos-beta.1` 和 `v1.1.3`，附件属于 macOS/Windows。此结果只证明官方仓库匿名 Release 列表目前可读；尚无公开 Android APK，无法实测该仓库 Android 附件的真实 CDN 下载/安装闭环。重定向和错误处理的通过结果来自本地模拟服务器，不能写成线上 Android 下载已验收。

GitHub 文档确认公开资源列表可匿名访问，并提供分页和 `browser_download_url` 字段；将来 Android 发布仍应设置 `make_latest=false` 保护桌面版的 latest 入口。本轮仅查阅文档，不调用发布接口。参考：[GitHub Release API 官方文档](https://docs.github.com/en/rest/releases/releases)。

## 7. 任务 E：自动化测试与证据

| 检查 | 本轮结果 |
| --- | --- |
| 新增 Python 预检查/比较测试 | 47 项通过 |
| Python 完整回归 | 238 项通过 = 原有 191 + 新增 47，0 失败/错误/跳过 |
| 真实 SDK 签名集成 | 原有 8 项显式启用并通过，使用已有 AOSP 公开预签名样例 |
| Android Debug | core 43 + App 135 = 178 项通过 |
| Android Release | 同组 178 项通过，两种变体不重复计为独立场景 |
| 其中 GitHub 新增测试 | 每种变体 8 项；更新相关总数由 68 增为 76 |
| Debug/Release lint | 各 0 错误、27 条警告，与 6B 一致 |
| Python/Kotlin 协议样例 | 通过 |
| 原正式发行包本机 SDK 预检查 | PASS，默认/V2/V3 三轮全部成功 |
| 原正式目录与临时副本比较 | PASS；没有把本地副本称为真实镜像 |
| 未提供 Gitee 目录 | NOT_CONFIGURED，非双平台成功 |
| Git 空白检查 | 通过；只有原 `.gitignore` 的 LF/CRLF 提示 |

Python 新测试覆盖正常包、APK 缺失/损坏/坏 ZIP、错误 SHA、版本名称/编号/Tag/包名/证书不符、未签名/Debug 签名/debuggable、默认/V2/V3 失败、过期或伪造报告、错误 SDK 范围、JSON 重复键、缺失/错误旁文件、额外 unsigned 文件、错误文件名和路径、检查中途文件变更、防覆盖和导出失败清理，以及两端一致、版本不同、文件大小/哈希/名称不同、签名/校验表不同、元数据/证据字节不同、Gitee 未配置和 CLI 退出码。

新增 Android 测试通过 MockWebServer（仅在本机运行的假服务器）实际驱动既有网络/解析/下载代码，覆盖匿名检查到 CDN 重定向下载的完整模拟链路、桌面附件排除、五种 HTTPS 重定向码、缺少 Location/循环跳转、服务错误、元数据读取超时、下载超时及缓存清理、选中 APK 的 HTTPS 和官方仓库约束。原有 HTTP 降级拒绝、哈希错误、取消/中断、包名/证书错误和安装授权等测试继续通过。

测试中把 HTTPS 请求映射到本机假服务器只是测试设施；生产 HTTPS 检查未放宽，没有连接虚构域名、创建测试私钥或公开测试 Release。新增 Python 策略测试使用合成 ZIP 和模拟 SDK 输出；真实密码学验证另由已启用的 SDK 集成测试和真实正式 APK 实测提供，二者不混淆。

主要复现命令：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\android_build.py :core:test :app:testDebugUnitTest :app:testReleaseUnitTest :app:lintDebug :app:lintRelease
$env:SUSE_ANDROID_SIGNATURE_INTEGRATION = '1'
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -q
Remove-Item Env:SUSE_ANDROID_SIGNATURE_INTEGRATION
.\.venv\Scripts\python.exe -B -X utf8 tools\android_protocol_vectors.py --check
.\.venv\Scripts\python.exe -B -X utf8 tools\android_verify.py --release-dir release\android\android-v0.3.0
git diff --check
```

Gradle 对未改变的 core 复用已有通过结果，本轮有变化的 App 两种变体测试和 lint 实际执行。本轮没有执行 APK assemble、正式签名或正式发行命令，也没有把旧 APK 描述成此次新构建。

证据文件：

- `build/android/phase6c-python-tests.json`：完整 Python 测试计数及集成开关。
- `build/android/phase6c-preflight.json`：现存正式包真实 SDK 复核结果和三轮原始输出。
- `build/android/phase6c-github-readonly.json`：匿名 GET 时间、HTTP 状态、Tag 和公开附件名。
- `build/android/phase6c-summary.json`：版本、四文件哈希、比较结果、Android 测试/lint 汇总和未完成边界。
- `android/app/build/test-results/testDebugUnitTest/`、`testReleaseUnitTest/` 下 JUnit XML，以及 `android/app/build/reports/lint-results-debug.xml`、`lint-results-release.xml`。
- `build/android-signature-tests/integration-results.json`：原有真实签名集成测试证据。

这些机器生成结果保留在本地 build 下，不会混入正式发行目录。

## 8. 修改文件清单

| 文件 | 修改内容 |
| --- | --- |
| `tools/android_artifacts.py` | 新增发行 APK 实测、严格 JSON 解析和四文件发行包预检查，共享原签名/归档核验逻辑 |
| `tools/android_verify.py` | 增加只读 `--release-dir` 模式 |
| `tools/android_release.py` | 正式目录导出前强制预检查 |
| `tools/android_release_parity.py` | 新增离线比较 CLI 和 PASS/FAIL/NOT_CONFIGURED 退出状态 |
| `tests/test_android_release_preflight.py` | 新增 47 项预检查、异常、比较及导出保护测试 |
| `tests/test_android_release.py` | 原导出单元测试隔离新预检查依赖，并确认调用 |
| `tests/test_android_signature_policy.py` | 原签名暂存/清理单元测试隔离新预检查依赖 |
| `android/app/src/main/kotlin/io/github/themingverse/susecampus/update/ReleaseSources.kt` | 先筛选 Android 三类必要附件，忽略桌面附件 |
| `android/app/src/test/kotlin/io/github/themingverse/susecampus/update/UpdateGithubChannelTest.kt` | 新增 8 项本地 GitHub 网络/下载模拟测试 |
| `docs/android-phase6c-report.md` | 本报告、操作方法、证据及后续边界 |

原先大量 Android 成果仍未被 Git 跟踪，`git diff` 不会展示这些未跟踪文件的全部变更；本轮保留它们，没有 reset/clean、自动暂存或提交。

## 9. 将来接入 Gitee 的操作步骤（未执行）

1. 维护者准备真实公开仓库，记录“所有者/仓库名”，确认匿名 Release 列表、附件列表和下载接口可用。本轮不创建仓库。
2. 在获准开展后续接入时，将 `android/update-sources.json` 的 `giteeRepository` 填为真实路径，或者先在应用更新设置中填写。仅改本地配置不代表远端发行已经可用；编译默认值需要后续构建才能进入 APK。
3. 完成 6D 真机验收，并由维护者另行决定公开发行、版本号和递增的 versionCode。当前同为 code 4 的包不会被当成已安装 code 4 的更新。
4. 使用同一份正式签名构建运行完整源码审核及本地发行预检查。已有正式目录不可覆盖；本轮的旧 6A 包不能冒充已经包含 6B/6C 新功能的包。
5. 仅在另行获得发布授权后，在 GitHub/Gitee 使用相同 Android Tag 和原样四文件；GitHub Android Release 设置 `make_latest=false`。不要按渠道重新编译、重签或改写元数据。
6. 分别匿名下载两平台四文件到独立目录，运行 `android_release_parity.py --github ... --gitee ...`，要求退出码 0；再在真实网络检查跳转、CDN、下载完整性及 App AUTO/手动源行为。
7. 完成实际手机的下载、安装授权、FileProvider、系统安装器和异常恢复验收后记录结果。自动发布、Secrets、签名工作流等需要单独授权，本轮未设计或创建。

## 10. 本轮停止点

6C-1 的本地独立开发与自动化验证完成。Gitee 仍未配置，真实双平台发行、Android 线上下载和 6D 真机验收未完成。没有创建 Gitee 仓库、改 origin、push、创建远程 Tag/Release、上传 APK/私钥、设置 Secrets、新建签名发布工作流、改写正式 APK、升级版本或删除既有发行产物。

停止在 6C-1，等待维护者验收，不自动进入 6C-2；首次公开发行继续等待 6D 完成和维护者另行确认。
