# Android 第六阶段发行与更新架构

## 6A：已确定的构建接口

Android 与 Windows/macOS 分别维护版本。`android/version.properties` 是 Android `versionName`、`versionCode` 的唯一配置来源；当前为 `0.3.0 / 4`。稳定版 Tag 为 `android-v0.3.0`，以后使用 `android-v<versionName>`，预发布名称只允许 `alpha.N`、`beta.N`、`rc.N`。每次对外发行的新 APK 都递增 versionCode，包括预发布转正式版，不复用旧 code，不依赖 Actions 运行次数。

官方来源为 `TheMingverse/suse-campus-login`。本地 origin 保持原值；用户已确认旧地址来自 GitHub 用户名变更，本轮不连接远程仓库验证或修改。

构建链为：版本检查 → 无密钥 Gradle 构建与质量检查 → APK 中间产物检查 → 官方工具签名 → 实际包与证书指纹核验 → 原子导出。Gradle 不保存正式签名配置。APK 由 AGP 完成对齐，脚本在签名前、签名后使用 `zipalign -c -P 16 4` 检查；签名后不再改 APK。

`android/release-identity.json` 只存包名、官方仓库、预先信任的公开证书 SHA-256，维护者已完成指纹登记。正式签名方案为 PKCS12、RSA 3072、v2/v3，不在本轮实现证书轮换或 Google Play 托管。

正式导出目录只有一份 APK，外加 `SHA256SUMS.txt`、`android-release.json` 和 `verification.json`。GitHub/Gitee 应复制同一份 APK，不能按下载渠道改变包名、编译渠道参数或重新签名。

正式验签必须完成三次独立检查：默认 `verify --verbose --print-certs`、V2 的 `--min-sdk-version 24 --max-sdk-version 27`、V3 的 `--min-sdk-version 28 --max-sdk-version 32`。每次退出码必须为 0、证书必须匹配登记指纹；默认检查要实际验证现代签名方案，V2/V3 专项输出分别必须为 true。默认 API 29+ 检查可能跳过 V2，不能要求默认输出同时报告两项为 true；也不能把默认检查删除。

签名工具成功后立即记录 APK SHA-256，并在核验与导出时继续核对。签名后的失败会将 APK 和三次验签诊断保存在本地 `build/android-diagnostics`；该目录属于忽略输出，不纳入发行目录、缓存上传或镜像同步。正式版本信息生成前会再次检查三次验签证据，成功后清理临时目录。诊断写入失败时优先保留原临时 APK，终端明确提示位置。

### 版本信息格式

仅在正式签名与检查通过后生成 `android-release.json`，格式如下。占位内容仅用于说明，不能直接发布：

```json
{
  "schemaVersion": 1,
  "platform": "android",
  "applicationId": "io.github.themingverse.susecampus",
  "versionName": "0.3.0",
  "versionCode": 4,
  "minSdk": 29,
  "tag": "android-v0.3.0",
  "fileName": "SUSE-CampusLogin-Android-v0.3.0-release.apk",
  "size": 0,
  "sha256": "<最终APK文件SHA-256>",
  "signingCertificateSha256": "<登记并核验通过的证书SHA-256>",
  "githubRepository": "TheMingverse/suse-campus-login",
  "source": {
    "gitCommit": "<构建时HEAD>",
    "workingTreeDirty": true,
    "sourceIncludesUncommittedChanges": true
  }
}
```

`size` 是最终文件的字节数。文件 SHA-256 证明文件内容是否一致；证书指纹用于确认发行身份。镜像中的版本信息不能自行改变信任身份。`source` 记录构建来源，当前未提交成果使 dirty 标记为 true；首次公开发布必须先确保发行 Tag 对应的提交包含完整源码。

版本信息不包含本机密钥路径、密码、校园网账号或本机 Gradle/JDK 路径。6A 不添加下载 URL 占位配置，不生成虚假的 Gitee 地址，不实现 App 更新模块。

## 6B：App 多渠道更新，已实现

更新设置提供 `AUTO / GITEE / GITHUB` 三种选择，默认 AUTO；与账号密文分别保存。AUTO 优先国内源，仅连接失败、超时或 HTTP 服务不可用时尝试 GitHub；未配置 Gitee 时使用 GitHub。元数据非法、哈希或证书不符等安全错误立即停止，不能静默换源。显式指定渠道保持选择，错误后由用户决定切换。空发行列表显示暂时无法判断；镜像版本落后会明确拒绝降级，不声称两边最新版本已一致。

按职责拆分，位于 Android app 的 `update` 包，不改变认证 core：

| 模块 | 职责 |
| --- | --- |
| 更新设置 | 保存渠道选择，提供当前安装版本和发行身份 |
| GitHub/Gitee 版本源 | 获取公开发行列表及对应版本信息，屏蔽平台接口差异 |
| 更新检查协调器 | 选择源、解释失败与回退、按 versionCode 比较可升级版本 |
| 下载与校验器 | 私有临时文件、大小和哈希核对、APK 身份与版本核对 |
| 系统安装适配器 | 按用户点击请求必要安装授权，用受限 URI 交给系统安装器 |

GitHub 发现版本时分页读取 Release 列表，仅保留 `android-v*`、非草稿、非预发布、含合法 Android 版本信息和 APK 的条目，再按合法 versionCode 比较；不能取列表第一项，也不能使用 `/releases/latest`。Gitee 通过其公开发行接口提供相同能力，不要求客户端携带 Token。公开元数据不可达时如实报告，不把网络失败说成“已经最新版”。

下载安装前展示版本、文件大小和来源，用户确认才下载。下载后核对实际字节数、SHA-256、实际包名、versionCode、versionName、最低 SDK，以及归档签名证书与已安装正式版的身份一致。版本信息中的证书指纹仅作一致性检查，不用来替换 App 的本地信任身份。归档证书解析不等于完整 APK 密码学签名验证；最终由系统安装器验证 APK 签名后安装，不能静默安装或绕过系统确认。

使用独立的正常 HTTPS 客户端，不复用认证客户端的 Cookie、Wi-Fi 绑定或受限学校 HTTP 规则，不读取账号、不切换网络。不在打开 App、点击小组件或磁贴时发更新请求。更新页前台操作结束或离开后取消请求，不引入 WorkManager、后台下载服务、定时任务或常驻监听。缓存文件可在下次用户操作时清理，不增加后台清理任务。

下载中间文件位于私有 cache 的 `updates/partial`；完成检查后才移至 `updates/ready`，不导出的 FileProvider 仅暴露后者。只在点击安装时检查并引导系统的“允许此来源安装应用”；不请求外部存储、通知、无障碍或设备管理权限。

公开协议保持 schemaVersion 1：`tag` 对应页面的发行 Tag，Release API 的 `body` 提供日志，同次发行的附件提供下载 URL，文件名/大小须与 manifest 一致，SHA256SUMS.txt 与 manifest 必须一致。verification.json 仍是维护者发行审核证据，不作为客户端可由服务器自行声明的信任根。

`android/update-sources.json` 的 `giteeRepository` 默认 null，维护者取得真实镜像信息后可设置默认“所有者/仓库名”；用户在更新页保存的配置优先，显式清空保留为空。GitHub 和正式证书始终从单独的发行身份配置编译，远程不能改写。下载过程中自动换源只接受版本、Tag、文件名、大小、哈希完全相同的备用发行；否则停止并要求重新检查。

## 6C：Actions 与镜像同步，待另行启动

新增独立 Android 工作流，不改原 macOS/Windows 工作流。普通 PR/分支检查只测试和无密钥构建，来自不受信任贡献的代码不接触签名密钥。发行由受信任的 `android-v*` Tag 触发，校验版本、完整已提交源码，运行测试、构建、签名及同一组发行检查。

第三方 Action 固定可审计的提交。签名 Secrets 仅在受保护的发行任务注入临时环境，工作目录外恢复私钥，任务结束清理，禁止上传含密钥的缓存或工件。普通任务仅有只读权限，发布任务才有必要的仓库内容写权限。

先准备包含 APK、校验值和版本信息的 GitHub Release 草稿，完整核验后发布。Android 创建和更新 Release 时都指定 `make_latest=false`，保护现有 Windows README 的 `/releases/latest` 入口；不为了保持 Windows 最新入口而把稳定 Android 版冒充预发布。现有工作流没有 Android 发行流程，6A 不添加对应 YAML。

Gitee 只作为 APK 下载镜像，不创建第二条主代码维护线。启动 6C 后先核对当前官方上传接口、附件大小限制、匿名下载条件及实际账号权限。若接口满足要求，实现单向同步；否则使用可核验的人工上传步骤，不声称已实现自动同步。

镜像复制 GitHub 已核验的原始 APK 与版本信息，先上传 APK，再确认下载字节数及 SHA-256，最后公布可用版本信息。两边重新下载 APK 后，哈希必须相同。镜像失败单独报告，可以重试；不撤销已有效的 GitHub 发行、不重新构建 APK、不把失败镜像标记为可用。App 中不包含同步用 Token。

## 6D：真机与首次公开发布，待另行启动

现场验证包括：旧 Debug 首次迁移；正式版用同一签名和更高 code 覆盖升级；三种更新渠道；镜像落后、断网、未认证校园 Wi-Fi、下载中断；错误哈希、错误包名和签名；用户拒绝安装授权或取消安装；Android 10 至当前支持版本的系统安装流程。

同时回归真实校园网认证、小组件、磁贴、前后台交接和锁屏取消。自动更新的失败与耗时不能影响认证。当前没有新的真机证据，历史小米认证成功不代表新版更新流程已通过。

README 中为各平台提供独立入口，Android 明确官方与国内下载链接、适用版本和首次 Debug 迁移步骤。确认 Tag 对应完整源码、两边 APK 哈希和签名一致、真机验收记录齐全后，由用户单独确认首次公开发布。

官方依据：[Android 版本管理](https://developer.android.com/studio/publish/versioning)、[GitHub Releases API](https://docs.github.com/en/rest/releases/releases)、[GitHub Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)、[Gitee API 文档入口](https://gitee.com/api/v5/swagger)。
