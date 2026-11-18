# Android 第六阶段 6B 开发报告

日期：2026-11-17。

## 结论与本轮边界

已实现三档渠道、持久化设置、独立 Android 版本发现、下载进度与取消、完整性及归档身份检查、安装授权和 Android 安装器入口。更新功能位于独立 app 层，不修改认证 core、账号加解密或 Keystore。没有后台服务、周期检查或 Wi-Fi 自动认证。

应用版本仍为 **0.3.0 / versionCode 4 / minSdk 29**，包名保持 `io.github.themingverse.susecampus`。正式证书指纹、Git origin、既有正式发行物均未修改；没有正式签名、提交、推送、Tag、Release、APK 上传或 Actions 发布工作流。本轮完成代表代码及自动化测试通过，不代表公开发行。

采用用户手动检查，满足本轮“应用启动或用户手动操作时检查”的手动分支。首页新增“更新设置与关于”入口，打开页面不自动发更新请求，不抢占打开 App 时原有的一次校园网认证。

## 现有结构和发行协议检查

认证 core 与 Android 系统适配原本分开；UI 使用 Compose Material 3，网络使用 OkHttp，异步使用协程。这些依赖继续复用，只补充已有同版本的 MockWebServer 测试依赖，无新增生产第三方库。

已读取 `release/android/android-v0.3.0` 内的 `android-release.json`、`SHA256SUMS.txt`、`verification.json`。复用 schemaVersion 1，未重写已有发行资产。现有正式 APK SHA-256 核对为：

```text
d85d496f66680a57d2219342176e17ffb0ce2f74fe6ebf3c2115314cd4d5038a
```

客户端字段映射如下，不另建不兼容格式：

| 更新信息 | 来源与校验 |
| --- | --- |
| applicationId、versionName、versionCode | 现有 android-release.json，必填且严格检查类型 |
| releaseTag | 现有 `tag`，必须与 Release API 的 tag_name、版本号一致 |
| releaseNotes | 同一个 Release 的 body；空日志显示明确说明 |
| APK 文件名、大小、SHA-256 | 现有 manifest；附件文件名和大小必须一致 |
| 下载地址 | 同一个 Release 的公开附件 API，限定 HTTPS；不猜用户仓库或附件地址 |
| 文件校验列表 | SHA256SUMS.txt 必须含唯一目标文件且哈希与 manifest 一致 |
| 发行证书身份 | 本地发行配置编译进资源；远程指纹仅供一致性检查，不能改写信任根 |
| verification.json | 保留作为维护者的发行审核证据，不把远程自报的验签结果当作信任根 |

GitHub 分页读取 Release 列表，筛选稳定 `android-vX.Y.Z`、非草稿、非预发布发行，在合法 Android 信息中按 versionCode 选最大值；不调用仓库全局 latest，不取列表第一项。Gitee 依据本轮核对的官方 GET 发行及 attach_files 接口读取附件，没有用户授权 Token 或上传请求。

## 修改和新增文件

Android 生产文件的公共前缀为 `android/app/src/main/kotlin/io/github/themingverse/susecampus/`。

| 文件/分组 | 职责 |
| --- | --- |
| `update/UpdateModels.kt` | 渠道、错误类型、版本比较、schemaVersion 1 元数据和校验列表验证 |
| `update/UpdateNetwork.kt` | 独立 HTTPS 客户端、有限重定向、正文上限、超时、取消请求 |
| `update/ReleaseSources.kt` | GitHub/Gitee API、分页、版本选择、自动模式及同一下载的备用源核对 |
| `update/ApkDownload.kt` | 私有临时文件、进度、取消、SHA-256 和包身份验证、验证后移入 ready |
| `update/AndroidUpdate.kt` | 独立 SharedPreferences、编译信任配置、系统归档读取、FileProvider 与安装 Intent |
| `update/UpdateViewModel.kt` | 页面操作、任务去重与取消、授权返回、缓存生命周期 |
| `update/UpdateActivity.kt`、`UpdateScreen.kt` | 不导出的更新页，复用现有 Material 风格 |
| `MainActivity.kt`、`CampusScreen.kt` | 仅增加更新入口与页面跳转回调 |
| `android/app/src/main/AndroidManifest.xml` | 更新 Activity、受限 FileProvider、REQUEST_INSTALL_PACKAGES |
| `android/app/src/main/res/xml/update_file_paths.xml` | 仅暴露私有 cache 的 updates/ready |
| `android/app/build.gradle.kts` | 由公开 JSON 生成信任/默认镜像资源；补充同版本测试依赖 |
| `android/update-sources.json` | 可为空的默认 Gitee 仓库，当前 null |
| `tools/android_build.py` | 仅允许复制新增公开构建配置，构建前验证其字段 |
| `tools/android_artifacts.py` | 扩展精确权限/组件清单，核验编译信任资源与 FileProvider 范围 |
| `tools/android_verify.py` | 6B 报告标记与新增组件模拟统计 |
| `tests/test_android_release.py` | 更新预期清单，增加编译信任与镜像配置安全测试 |
| `android/app/src/test/.../update/UpdatePolicyTest.kt` | 渠道、版本、元数据、错误分类及备用下载策略 |
| `android/app/src/test/.../update/UpdateSourceTest.kt` | 两平台公开 API 的模拟响应与分页 |
| `android/app/src/test/.../update/UpdateDownloadTest.kt` | 本地服务器下载、进度、中断、取消及 HTTPS 限制 |
| `android/app/src/test/.../update/AndroidUpdateTest.kt` | API 29/34/36 的持久化、系统归档证书、授权、路径和 Intent 模拟 |
| `android/README.md`、`docs/android-development.md`、`docs/android-release-architecture.md`、本报告 | 使用、实现、配置、结果及后续依赖 |

没有修改 `CampusViewModel`、`CampusApplication`、认证核心、账号存储、原网络安全 HTTP 例外、正式身份 JSON、版本配置、Windows/macOS 生产代码或既有发布工作流。

## 功能与数据流

用户选渠道并保存 → 手动检查 Release API → manifest 与 SHA256SUMS 一致性检查 → versionCode 比较 → 展示日志/大小/来源 → 用户确认下载 → 私有 partial → 文件及归档身份检查 → 私有 ready → 检查安装授权 → 再次检查 APK → Android 系统确认安装。

三档渠道及已填写的镜像路径使用独立的 `update_settings` 保存，不读取或解密校园网账号。用户保存的镜像配置优先于编译默认值；显式清空会保持为空。默认 AUTO，Gitee 未配置时使用 GitHub。

AUTO 仅对网络失败、超时或 HTTP 服务不可用换到 GitHub。手动渠道不自动切换。非法 JSON、缺失字段、错误 Tag、校验列表冲突、文件哈希或证书不符等安全错误立即停止。镜像空列表显示暂时无法判断；低于当前版本会拒绝降级；等于当前版本显示“当前已是最新版本”，结果以页面展示的实际来源为准。

Gitee 下载中发生网络故障时，AUTO 可重新取得 GitHub 发行信息；只有版本、Tag、文件名、大小和 SHA-256 全部相同才从备用源重新下载。若两边发行不同，要求重新检查并确认，不静默改为另一版本。中断/取消的 partial 删除，重试从头开始，不保留不可信断点文件。

更新任务由更新页 ViewModel 管理。离开页面/进入后台取消网络任务，旋转保留；没有 WorkManager、下载常驻服务或通知权限。进程重启时旧更新缓存不直接视为可信，清理后需重新检查下载。缓存清理与新操作串行，防止清理任务删除新下载。

## 安全机制

- GitHub 仓库、包名和正式证书 SHA-256 从 `android/release-identity.json` 生成 Android 资源；只包含公开信息，不使用私钥、密码或账户配置。核验工具读取实际 APK 资源，确认编译值与本地公开配置一致。
- 独立 OkHttp 客户端不共享认证 Cookie、DNS/SocketFactory 绑定或登录参数，不改变系统网络路由，不强制切换 Wi-Fi/移动数据。
- 生产请求仅接受无用户名/密码、无 fragment 的 HTTPS 443 URL；每次重定向重新检查，拒绝 HTTPS 降级至 HTTP。连接 8 秒、读取 20 秒，元数据单次总体 30 秒；下载请求最长 10 分钟。禁止自动重试和自动重定向，最多处理 5 次合法重定向。
- Release 列表单页上限 2 MiB、最多 20 页，每页 100；元数据/校验文件上限 128 KiB；APK 大小上限 250 MiB。非法 UTF-8、异常文件长度或编码拒绝处理。
- 下载只能写入私有 cache 的 `updates/partial`，校验 SHA-256、实际大小、包名、版本编号/名称、系统要求和当前签名证书后才移动至 `updates/ready`。
- 证书使用系统 `GET_SIGNING_CERTIFICATES` 读取当前 APK 签名身份，要求唯一签名者与编译的正式指纹一致，不接受远程更换证书。系统安装器仍负责最终平台验签和用户确认，不宣称客户端自行执行了桌面 apksigner 的全部 V2/V3 审核。
- FileProvider 不导出，仅映射 `updates/ready/`，不提供 partial、根目录或账号数据路径；只临时授予 URI 读取权限，无写权限。安装前重新计算哈希及检查身份，阻止授权期间文件变化或版本已经过时。
- 没有安装授权时说明原因，由用户按钮进入本应用的未知来源安装设置；返回后重新检查权限，未授权不启动安装器。无静默安装、Root 或 file:// URI。

测试中发现并修复了取消期间直接并发关闭响应体引起的 OkHttp 异常。现改为取消对应 Call，由读取线程退出并关闭资源；取消及同一下载器重试均已通过本地服务器测试。

## 测试命令与结果

| 项目 | 结果 |
| --- | --- |
| Android Debug | **170 项通过**，0 失败、错误、跳过 |
| Android Release | **170 项通过**，0 失败、错误、跳过 |
| 其中新增更新功能 | 每种变体 **68 项**：策略 14、来源 8、下载 10、Android 适配 36 |
| 原有 Android | 共享 core 43 + 既有 App 59 均通过 |
| Debug / Release lint | 各 **0 错误、27 条警告** |
| Python/Windows 与发行工具 | **191 项通过**，原有 135 + 发行工具 56，0 跳过 |
| 其中真实 apksigner 集成 | 原有 8 项已显式启用并通过，不访问正式私钥 |
| Python/Kotlin 协议样例 | 通过 |
| Debug APK、设备测试 APK、未签名 Release | 构建成功 |
| APK 结构、安全配置、编译信任与 FileProvider 范围核验 | Debug 与未签名 Release 均通过 |
| 既有正式 APK | 哈希仍为报告开头的 d85d...，未改变 |
| Git 空白检查 | 通过，只有既有 LF/CRLF 提示 |

170 = core 43 + App 127；Debug/Release 复用同一组逻辑，不能称为 340 项不同场景。Android 适配的 36 项为 12 个测试在 API 29/34/36 的模拟执行，不是真机安装。27 条 lint 警告中保留原有 24 条，新增是测试依赖版本建议和两条 KTX 风格建议，没有通过降低安全要求消除警告。

覆盖本轮要求的三档选择和保存、AUTO 优先 Gitee、网络失败备用、手动源不切换、Gitee 未配置、版本新旧比较、同版本不更新、降级拒绝、包名/哈希/证书不符、中断取消及重试、授权不足与重新授权、非法/不完整元数据。另覆盖分页越过桌面版、预发布过滤、附件来源、校验列表冲突、HTTPS 降级、响应大小和 UTF-8 限制、授权期间篡改文件、partial 无法进入安装路径。

所有更新数据来自内存模拟或本地 MockWebServer，没有为了测试公开上传 APK。HTTP 仅用于测试构造的回环服务器，生产验证规则始终拒绝 HTTP。安装 Intent 测试在 Windows/Robolectric 中仅替代 URI 创建步骤，以避开 AndroidX 对 Android 路径分隔符的假设；真实 XML 路径、目录限制、权限判断、再验和 Intent 标志均测试。不能把该结果当作真机 FileProvider/安装器验收。

主要执行命令：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\android_build.py :core:test :app:testDebugUnitTest :app:testReleaseUnitTest :app:lintDebug :app:lintRelease :app:assembleDebug :app:assembleDebugAndroidTest :app:assembleRelease -- --rerun-tasks
# 新增默认镜像构建资源后，再执行对应测试、lint 与构建；最后测试源码修改也已重跑两个变体。
$env:SUSE_ANDROID_SIGNATURE_INTEGRATION = '1'
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -q
# 测试后已移除该临时环境变量；完整结果另保存 JSON。
.\.venv\Scripts\python.exe -B -X utf8 tools\android_protocol_vectors.py --check
.\.venv\Scripts\python.exe -B -X utf8 tools\android_verify.py
.\.venv\Scripts\python.exe -B -X utf8 tools\android_verify.py --variant release --allow-unsigned --apk android/app/build/outputs/apk/release/app-release-unsigned.apk
git diff --check
```

证据文件：`build/android/verification.json`、`release-verification.json`、`phase6b-python-tests.json`、两种变体的 JUnit XML、lint XML，以及 `build/android-signature-tests/integration-results.json`。

## Gitee 配置与 6C 依赖

当前 `android/update-sources.json` 为：

```json
{"giteeRepository": null}
```

没有编造账号、仓库或下载地址。取得真实镜像信息后，维护者可将该字段设置为真实“所有者/仓库名”，作为新安装的默认值；用户也可在更新设置中填写路径或完整的 `https://gitee.com/所有者/仓库名`。显式保存的用户值优先，不需要修改正式发行身份文件。

6C 需要确认真实公开 Gitee 仓库、匿名可读的 Release/附件接口、HTTPS 下载及重定向，发布相同 Android Tag、同名 manifest/校验文件和完全相同的 APK。GitHub 需要公开的稳定 Android Release 和上述附件。客户端不内置上传 Token；上传和镜像同步流程本轮未实现。

为保持兼容，不要求 manifest 新增固定平台下载 URL；URL 和日志由各平台同次发行的 API 资产信息补齐。两个平台仍可发布相同的 manifest 和 APK。未来公开更新前必须由维护者另行确认递增 versionCode；本轮保持 4，远程同为 4 时按要求不提供升级。

## 未完成事项与维护者验收

当前无已知构建或自动测试失败。没有连接 Android 设备，未执行新增更新页、授权返回、原生 FileProvider 和系统安装器的真机操作；6A 既有真机使用反馈不冒充 6B 的验证结果。由于尚未配置真实 Gitee 镜像，也没有进行真实双平台下载验收。

维护者后续需在真机检查页面布局、大字体/横屏、返回和锁屏取消、拒绝/允许未知来源、安装器确认及校园网认证并行状态；真实更新包必须使用同一正式签名、更高 versionCode，不能把本轮同号 Debug 包直接覆盖已安装正式版。不要为测试更新而先卸载正在使用的正式版或丢失账号。

本轮没有调用正式发行脚本、读取密钥、生成签名包或覆盖已有正式发行目录。公开发布和双平台同步留待 6C、6D。到此停止，等待维护者验收。

官方接口依据：[GitHub Release 列表](https://docs.github.com/en/rest/releases/releases#list-releases)、[Gitee API 文档](https://gitee.com/api/v5/swagger)、[Gitee 机器可读接口定义](https://gitee.com/api/v5/doc_json)、[FileProvider](https://developer.android.com/reference/androidx/core/content/FileProvider)、[安装来源授权](https://developer.android.com/reference/android/content/pm/PackageManager#canRequestPackageInstalls())。
