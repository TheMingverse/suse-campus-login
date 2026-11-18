# Android 第六阶段最终发行前审查

审查日期：2026 年 11 月 17 日（北京时间）。目标：首个具备完整应用内更新能力的 Android 正式版本，候选为 `0.4.0 / versionCode 5`。

## 1. 结论

**目前不具备“完整更新链路已真实验证，可以直接正式发布”的条件。** 可以继续完成修复、候选配置与本地正式构建准备；首次公开发行仍需 6D 真机验收及维护者另行确认。

本轮只进行只读仓库/代码/产物审查、现有测试检查和隔离兼容性实验，新增本报告及 `build/android/` 审查证据。没有修改生产代码、版本、默认镜像、applicationId、证书或正式发行目录，没有上传文件、创建 Release/Tag、提交或推送代码、修改签名密钥、设置 Secrets 或发布工作流。

主要未闭环事项：

1. 两平台都没有 Android Release，真实 APK 附件匿名下载、重定向和双端一致性没有实测对象。
2. Gitee 仓库实际已创建，但 `android/update-sources.json` 仍是 null，默认 AUTO 当前只使用 GitHub。
3. AUTO 只对网络/服务异常回落；Gitee 空发行列表、镜像版本落后不会触发 GitHub 查询。
4. 升级版本前需要消除两处测试对当前 `0.3.0 / 4` 的耦合。
5. 当前没有连接 Android 设备，原生 FileProvider、授权返回、系统安装器和完整更新操作未完成 6D。
6. 原正式 `0.3.0 / 4` APK 没有更新入口，首个具备更新能力的版本需要用户手动覆盖安装。
7. 没有 GitHub Release 到 Gitee 的镜像同步实现；仅在 GitHub 发布不能保证 AUTO 用户发现新版本。
8. Android 工程和发行工具仍有大量未跟踪文件，正式构建前应审阅并提交完整源码，不能只提交已跟踪文件。

## 2. Gitee 与 GitHub 实际检查

### 仓库身份

| 项目 | Gitee | GitHub |
| --- | --- | --- |
| 实际地址 | https://gitee.com/TheMingverse/suse-campus-login | https://github.com/TheMingverse/suse-campus-login |
| 所有者/仓库 | `TheMingverse/suse-campus-login` | `TheMingverse/suse-campus-login` |
| 匿名仓库 API | HTTP 200 | HTTP 200 |
| 公开状态 | public=true、private=false | 公开、private=false |
| 默认分支 | master | main |
| 匿名 Release 列表 | HTTP 200，0 条 | HTTP 200，2 条桌面发行 |
| Android 稳定发行 | 0 条 | 0 条 |

地址来自已有创建记录、用户账号和本轮真实 API 返回值，不是猜测。网络核查没有附带 Authorization、Cookie 或访问令牌。

Gitee 主页匿名 HTTPS GET 也返回 HTTP 200。本轮观测的主页/API 请求没有重定向；这不能作为 APK CDN 重定向已通过的证据。

GitHub 两条发行仍为 `v1.2.0-macos-beta.1`、`v1.1.3`，附件是 macOS/Windows。Android 客户端通过独立 `android-v<versionName>` Tag 筛选，不会将这些桌面发行当成 Android 最新版。

### 匿名附件下载与 HTTPS

Gitee 官方机器可读 API 定义确认以下 GET 接口及字段与当前客户端实现一致：

- `/api/v5/repos/{owner}/{repo}/releases`。
- `/api/v5/repos/{owner}/{repo}/releases/{release_id}/attach_files`，附件字段包括 id、name、size、browser_download_url。
- `/api/v5/repos/{owner}/{repo}/releases/{release_id}/attach_files/{attach_file_id}/download`。

上述 GET 接口的 access_token 参数在定义中为非必填。**这是接口设计依据，不等于本仓库的 APK 匿名下载已通过。** 当前仓库没有 Release/附件，不能构造不存在的 release_id 或下载地址来冒充实测。

现有客户端逐次检查 HTTPS、443 端口、无 URL 凭据和 fragment，处理 301/302/303/307/308，最多五跳，拒绝 HTTP 降级。GitHub 初始附件还必须位于官方仓库同一 Tag 的下载路径。对应行为有本地模拟测试，真实 Android 附件重定向仍待实际发行对象。

参考：[Gitee 官方 API 定义](https://gitee.com/api/v5/doc_json)、[GitHub Release 官方 API](https://docs.github.com/en/rest/releases/releases)。

### 默认镜像配置

当前 `android/update-sources.json`：

```json
{"giteeRepository": null}
```

这是合法的“尚未启用默认镜像”状态，不是错误仓库地址，但尚未实现本轮目标所需的默认双渠道。未来首发冻结前应在获准修改时设置为：

```json
{"giteeRepository": "TheMingverse/suse-campus-login"}
```

该配置被编译进 APK；不是改一下远程仓库就会更新手机内的默认值。若首发 0.4.0 希望默认具备 Gitee 能力，应在最终构建前确定并配置，不能发布后重新构建另一份同版本 APK。本轮没有执行该修改。

用户自己保存的镜像设置优先于编译默认值，包括显式清空；升级后的实际设置也需在真机验收。

## 3. 双渠道行为审查

| 场景 | 当前实现 | 证据/结论 |
| --- | --- | --- |
| AUTO、Gitee 未配置 | 只访问 GitHub | 已实现、策略测试覆盖 |
| AUTO、已配置且 Gitee 有合法发行 | 优先 Gitee | 已实现、策略测试覆盖 |
| Gitee 网络超时、中断、HTTP 服务错误 | AUTO 查询 GitHub | 已实现、测试覆盖 |
| Gitee 下载网络失败 | AUTO 向 GitHub 获取同一制品后重新下载 | 要求包名、版本、Tag、文件名、大小、SHA-256 一致 |
| 手动 Gitee | 不自动切换 | 已实现、测试覆盖 |
| 手动 GitHub | 不自动切换 | 已实现、测试覆盖 |
| 哈希、证书、元数据等安全错误 | 停止，不换源 | 合理的安全边界，不能为可用性改成忽略 |
| Gitee HTTP 200 但无 Android 发行 | 返回 null，AUTO 不查 GitHub | 可用性缺口，不能统称“失败都会回落” |
| Gitee 版本落后 | 不再查询 GitHub；可能显示当前最新或拒绝降级 | 即使 GitHub 已有更高版本，也可能无法发现 |
| 两平台同版本、同 APK/元数据 | 采用同协议；本地比较工具可强制校验四文件 | 当前远端没有 APK，不能宣称真实双平台已一致 |

代码位置：`ReleaseSources.kt` 第 97–111 行。AUTO 成功获得 null 或旧版本时，并没有抛出 NETWORK/SERVICE 异常，因此不会进入回落分支。

建议在获准的后续修复中补齐空列表回落，并明确镜像滞后时的版本查询规则，例如 Gitee 不能提供比已安装版本更高的有效版本时再查询 GitHub。不得因此放宽哈希、包名、签名和同制品要求。修复前，必须依赖可靠同步流程保持镜像及时更新；不能把网络回落当成版本同步。

## 4. 完整更新链路：实现与实证分开判断

| 环节 | 当前代码 | 自动化与真实验证情况 |
| --- | --- | --- |
| 版本信息读取 | Release API → android-release.json → SHA256SUMS | 解析/分页/异常有测试；真实 API 只有空 Android 列表 |
| 新版本识别 | 比较 versionCode，拒绝降级和同 code 不同 versionName | 策略测试通过；无真实远端更新包 |
| 更新日志 | 使用同次 Release body，在页面显示 | 数据读取有测试，真机页面未验收 |
| APK 下载 | 独立网络客户端，私有 partial 临时文件 | 本地服务器下载/取消/中断测试通过，线上 APK 未测 |
| 下载进度 | 字节数、总量、百分比和实际来源 | 下载器进度有测试，真机 UI 未验收 |
| SHA-256 | 下载后和安装前均核对 | 模拟数据测试通过；旧正式包本机真实哈希核验通过 |
| 包名 | 系统归档 API 读取后与本地信任身份比较 | 适配/策略模拟通过，真实更新包安装未测 |
| versionCode/versionName | 归档值需与元数据一致，且 code 高于已安装 | 有模拟测试，未做真机跨版本更新 |
| 正式证书 | 当前唯一签名证书 SHA-256 必须匹配内置指纹 | 适配模拟与桌面真实签名测试通过，更新安装未实测 |
| FileProvider | 不导出，仅暴露 cache/updates/ready，使用 content URI 和只读授权 | XML/目录/权限策略有测试；正向 URI 创建在 Windows 测试中注入替代，原生路径未真机验证 |
| 未知来源安装授权 | 查询 canRequestPackageInstalls，跳转本 App 设置页，返回再判断 | 适配和 Intent 有测试；实际授权页面及返回流程未真机验收 |
| 系统安装器 | 再验 APK 后调用 ACTION_VIEW 和正确 MIME，系统要求用户确认 | Intent 构造有测试；没有实际打开并完成安装 |

客户端使用系统归档 API 核对签名身份，Android 系统安装器执行最终平台验签。不能把桌面 apksigner 的三轮检查描述成手机客户端自己执行。

现有测试未发现直接驱动 UpdateActivity/UpdateViewModel 完整页面、授权返回和安装流程的端到端用例；测试覆盖的是策略、来源、下载器及 Android 适配组件。当前 ADB 可用，但连接设备数为 0。本轮没有安装、卸载或操作手机。

参考：[Android 安装来源授权](https://developer.android.com/reference/android/content/pm/PackageManager#canRequestPackageInstalls())、[FileProvider](https://developer.android.com/reference/androidx/core/content/FileProvider)。

### 旧正式版无法自动完成首次迁移

本轮对原正式 APK 实际编译清单进行读取，确认：

```text
0.3.0 / code 4
UpdateActivity：不存在
FileProvider：不存在
REQUEST_INSTALL_PACKAGES：不存在
```

因此原正式 0.3.0 用户不能靠这个旧包的应用内入口发现 0.4.0。首个含更新功能的版本需要手动下载安装；同包名、同正式证书且更高 code 时应走覆盖安装，并在真机验证数据保留，不应为验收卸载正在使用的正式版。

之后，已安装具备更新功能的版本才可在更新页手动点击“检查更新”发现后续版本。当前设计没有后台推送、启动自动检查或静默安装。

## 5. 0.4.0 / code 5 兼容性

### 生产工具与协议兼容

使用临时版本文件调用真实 `read_version()`，结果通过：

```text
versionName = 0.4.0
versionCode = 5
Tag = android-v0.4.0
APK = SUSE-CampusLogin-Android-v0.4.0-release.apk
```

Gradle 版本范围、客户端稳定版格式、schemaVersion 1 元数据、文件名规则和比较逻辑均支持该组合。5 大于旧正式 4。本轮没有修改项目版本或构建候选 APK，未来实际 APK 大小和 SHA-256 只能来自那次真实构建，不能沿用 0.3.0 的数值。

### 两处版本耦合需要先修复

1. `AndroidUpdateTest.kt:47` 把真实安装包版本固定断言为 `InstalledVersion("0.3.0", 4)`。改为 0.4.0/5 后，该断言会与新构建冲突；此测试覆盖 API 29/34/36。正式发行脚本会运行 Release 单元测试，因此不能只改版本就宣称流程可通过。应让断言取受控的当前构建版本，同时保留业务用例中独立的旧版/新版合成数据。
2. `test_android_release_preflight.py:361` 的 CLI 测试使用固定 0.3.0 测试包，却调用读取真实项目版本的 CLI。以候选 0.4.0/5 替代版本读取后，已隔离复现 `Release version or Tag differs from expected configuration`。应给测试注入匹配的测试版本，而非依赖工作区的正式版本。

不是所有出现“0.3.0”的测试都需要替换：用于模拟“旧版 4 → 新版 5”的独立数据仍应保留，不能全局搜索替换。

当前项目仍为 0.3.0/4，现有套件通过；候选版本实验的一项预期错误单独记录，不能与当前回归结果混淆。

## 6. 持续更新机制：现状与建议设计

### 现状

仓库目前只有既有 macOS/Windows CI 工作流，没有 Android 正式发布或 GitHub→Gitee 发行镜像工作流。应用内也不会替维护者上传文件。以下动作均不足以让用户收到新版本：

- 只修改代码或提交 GitHub。
- 只创建 Git Tag。
- 只创建没有完整附件的 Release。
- 只在 GitHub 发布，却假设 Gitee 自动保持相同版本。

Release 列表不包含仅存在的 Git Tag；客户端还会过滤预发布/草稿、校验元数据和附件。依据：[GitHub Release 列表说明](https://docs.github.com/en/rest/releases/releases#list-releases)。

### 建议目标：本机一次构建签名，GitHub 发布后自动镜像

这是一项后续实施设计，本轮没有创建工作流、Secrets 或同步脚本。

1. 每次正式发行更新 versionName 并递增 versionCode，审阅并提交完整源码。
2. 本机现有发行脚本一次构建并正式签名，生成唯一的四文件发行包，预检查通过后冻结。正式私钥留在发行机。
3. GitHub 使用匹配的 Android Tag，完整附带四个文件和更新日志，设置 `make_latest=false`，再发布稳定 Release。
4. 后续获准建立独立镜像任务，监听 GitHub `release.published`，仅处理稳定 Android Tag，读取四文件并检查版本、证书、SHA-256 和元数据。该任务不重新构建、不重新签名，不需要 Android 私钥。
5. 使用单独授权的 Gitee API 访问令牌执行镜像。令牌仅放受保护的 CI 机密环境，不进入源码、APK或日志；本轮没有创建该令牌或机密配置。
6. 在 Gitee 以同一个稳定 Tag 建立暂标为 prerelease 的发行，复制同一四文件及日志。完成上传后通过匿名接口回读并比较，最后将 prerelease 改为 false，避免客户端读到只上传了一部分附件的正式发行。
7. 若同 Tag 已存在且文件全部一致，重复执行应跳过；若存在差异则停止，不能覆盖旧正式发行。同步失败明确报告失败，不把 GitHub 发布成功当成双平台成功。

Gitee 官方定义提供创建和更新 Release 的 prerelease 字段，因此上述“先预发布态、完整后转稳定”具备接口设计依据；完整上传和状态转换仍需后续实际演练。

同步任务不处理只提交代码的事件，不改 Git origin，不自动签名，也不触碰 Windows/macOS 的 latest 入口。工作流完成并通过真实验收后，维护者的日常流程才能简化为“修改/提交代码 → 完成一次正式构建与 GitHub Release → 镜像任务同步 → 用户应用内检查更新”。同步仍需要监测成功状态，两个平台之间没有跨站点原子发布保证。

## 7. 下一步正式构建与双平台发布步骤

以下是待维护者确认后的步骤，本轮均未实施。

### A. 修复和冻结候选配置

1. 修复上述版本耦合测试；明确并补齐空镜像及版本滞后的查询策略，增加相应测试，保留安全错误停止规则。
2. 将默认 Gitee 设置为实际路径 `TheMingverse/suse-campus-login`，将版本改为 0.4.0/5；包名、正式证书不变。
3. 审阅当前未跟踪 Android 源码、工具、测试和文档，纳入完整源码提交；私钥、密码和本地账号文件不得进入提交。本轮没有自动提交或推送。
4. 在目标配置下重新运行 core/App Debug/App Release 测试、lint 和协议检查；不能沿用 0.3.0 的通过记录充当 0.4.0 的结果。

### B. 本机正式构建，冻结唯一发行包

由维护者按 `docs/android-signing.md` 在本机提供既有正式签名输入，密码使用隐藏输入，不发送到聊天。正式发行脚本只生成本地产物，不进行远程发布：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\android_release.py --tag android-v0.4.0
.\.venv\Scripts\python.exe -B -X utf8 tools\android_verify.py --release-dir release\android\android-v0.4.0 --tag android-v0.4.0
```

成功后冻结：

```text
release/android/android-v0.4.0/
  SUSE-CampusLogin-Android-v0.4.0-release.apk
  android-release.json
  SHA256SUMS.txt
  verification.json
```

只使用这一份 APK 分发两平台，不能按渠道重新构建或签名。若之后再修改源码/配置或重做候选，应明确作废并保留原候选、重新规划发行身份；不可覆盖已有正式目录。

### C. 6D 与首次发布门槛

- 在测试手机验收更新页面、三档设置及持久化、前后台/锁屏/旋转、下载取消、拒绝和允许安装授权、真实 FileProvider 与系统安装器、覆盖安装后数据保留及校园网回归。
- 完整升级测试需要“带更新入口的低版本测试基线 → 更高版本真实签名 APK”。旧 6A 0.3.0 没入口，不能作为自动更新发起端；0.4.0/5 也不能给自己提供同 code 更新。缺少基线时应先另行准备不公开的受控低版本测试基线，而不是伪造版本比较或卸载日常正式版。
- 在没有任何远端 Android 附件、又禁止上传的前提下，本轮无法验证真实公开下载闭环。发布前可完成真机本地安装及受控测试；真实平台下载验收需要另行授权的分发演练或首次上线后的验收窗口。不得把其中任一步写成已经完成。
- 6D 完成且维护者另行确认之前，不进行首次公开发行。

### D. 获准后双平台分发及验收

1. 若镜像工作流届时尚未完成，先使用人工镜像流程，将同一四文件原样放到两边；人工方式能完成一次发行，但不等于未来只发 GitHub 就会自动同步。
2. 两端使用 `android-v0.4.0`、一致的版本信息、APK 文件名和元数据。GitHub 设置 `make_latest=false`；Gitee 先暂标 prerelease，传齐后再转稳定。两端发布不是原子操作，过渡期必须如实显示未完成。
3. 分别不登录下载四文件到两个独立目录，检查全部跳转均为 HTTPS，拒绝登录页、验证页或错误 HTML 冒充 APK。
4. 运行：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\android_release_parity.py --github 'D:\下载\github-android-v0.4.0' --gitee 'D:\下载\gitee-android-v0.4.0'
```

5. 要求 PASS/退出码 0，并与被冻结的本地正式包再次比较；不能只验证两边相同却都传错了文件。
6. 真机验证两种手动渠道、AUTO 优先、网络失败备用、真实下载进度/校验及系统安装。再确认 0.4.0 是新版用户可继续更新的起点，原 0.3.0 用户通过手动安装完成首次迁移。

## 8. 本轮验证结果和证据

| 验证 | 结果与限制 |
| --- | --- |
| Python 完整回归 | 本轮实际执行 238 项，0 失败/错误/跳过，包含显式启用的 8 项真实 SDK 签名集成 |
| Gradle 测试/lint 检查 | BUILD SUCCESSFUL，当前源未变，测试任务 UP-TO-DATE；复核已有 Debug/Release 各 178 项、更新相关各 76 项结果，不称为本轮重新执行 356 项 |
| lint | 两变体均 0 错误、27 条警告 |
| 旧正式包本机 SDK 复核 | PASS；默认/V2/V3、哈希、包信息、ZIP/对齐与历史报告一致 |
| 0.4.0 版本解析实验 | 真实解析器通过，项目版本文件未改 |
| 版本耦合隔离实验 | 预期复现 1 个 Python 测试错误，独立于 238 项当前回归；Android 旧版本断言由源码直接确认，未构建 0.4.0 |
| 真机 | ADB 可用、连接设备 0，未执行 6D |
| 远端 | 仅匿名 GET；无上传、无 Release/Tag/源码写入 |
| 本地产物保护 | 正式目录四文件哈希未变；版本、身份、镜像配置及 origin 未变 |

证据文件：

- `build/android/final-release-review-summary.json`：结论和待解决事项。
- `build/android/final-review-network.json`：真实匿名请求及远端发行列表。
- `build/android/final-review-gitee-api-spec.json`：本轮取得的 Gitee 官方接口定义。
- `build/android/final-review-local-apk.json`：旧正式包真实验签和更新组件检查。
- `build/android/final-review-version-compatibility.json`：0.4.0 解析与隔离迁移问题。
- `build/android/final-review-python-tests.json`：当前版本完整 Python 回归结果。

审查到此结束，等待维护者确认下一步修复、候选配置、正式构建和 6D 安排。
