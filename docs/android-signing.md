# Android 正式签名与首次迁移

当前准备版本为 **0.4.0 / versionCode 5**，Tag 为 `android-v0.4.0`。本指南中的建钥、备份和签名输入由维护者本人执行。已有正式密钥和登记指纹时，跳过第 1–3 节，使用原密钥执行第 4 节，不能重新建钥替换。无需将私钥或密码发送给 AI。

## 先理解两种密钥

发行密钥保存在电脑，用于给 APK 签名，相当于软件发行者的身份证。以后每次正式升级都需要保留同一身份。这里发布的是自行签名的 APK，不经过 Google Play 的密钥托管；丢失密钥或密码后，不能靠重新生成文件恢复原身份。

手机里的 Android Keystore 密钥则用来加密校园网账号，不能导出。它与电脑上的发行密钥不是同一把钥匙。

## 1. 本人创建发行密钥

在项目根目录打开 PowerShell。下面仅设置当前终端使用的路径，不修改系统环境变量。若使用其他 JDK 17，请更换第一行。

```powershell
$campusJdk = 'D:\pycharm下载版\PyCharm 2023.3.5\jbr'
$campusKeyDirectory = Join-Path $env:USERPROFILE '.suse-campus-signing'
$campusKeyFile = Join-Path $campusKeyDirectory 'android-release.p12'
New-Item -ItemType Directory -Path $campusKeyDirectory -Force | Out-Null
if (Test-Path -LiteralPath $campusKeyFile) { throw '密钥文件已存在，请先核实，不要重新生成或覆盖。' }
& "$campusJdk\bin\keytool.exe" -genkeypair -v `
  -keystore $campusKeyFile -storetype PKCS12 `
  -alias suse-campus-android -keyalg RSA -keysize 3072 -validity 10000
if ($LASTEXITCODE -ne 0) { throw '密钥创建未成功，请检查 keytool 提示。' }
```

按提示设置强密码，建议使用密码管理器生成并保存，至少 16 个随机字符；输入时屏幕不显示字符是正常现象。PKCS12 的密钥密码与容器密码使用同一个密码。不要把密码补写为命令行参数。

证书信息会包含在公开 APK 中。可使用项目维护者称谓填写姓名/组织，不填写身份证号、住址、校园网账号等个人资料。其他无必要字段可以保留默认值。

密钥位于用户目录下的 `.suse-campus-signing`，不能放进项目、项目 `.cache` 或用户的构建缓存目录。仓库忽略规则只是补充保护，不是保存密钥的地方。

## 2. 本人备份并验证

1. 将 `android-release.p12` 复制到至少两个独立位置，例如两个离线设备的加密容器。不要把未加密私钥传到聊天、仓库或公开网盘。
2. 密码存入密码管理器，与密钥文件分开保存。另记别名 `suse-campus-android`、PKCS12 格式和备份位置。
3. 使用其中一份备份运行下面的检查，把路径替换成备份文件路径。命令会提示输入密码。

```powershell
& "$campusJdk\bin\keytool.exe" -list -v -storetype PKCS12 `
  -keystore 'E:\请替换为实际备份位置\android-release.p12' -alias suse-campus-android
```

确认能打开、条目为 `PrivateKeyEntry`、RSA 3072 位、有效期正确，并记录证书指纹中 **SHA256** 一栏。原件与备份应显示同一证书指纹。能成功列出条目验证了备份文件及密码可读取；真正的签名能力仍以第 4 步成功为准。

## 3. 登记公开证书指纹

在 `android/release-identity.json` 中，将 `signingCertificateSha256` 的 `null` 改为第 2 步得到的证书 SHA256 字符串。例如值的格式为 64 个十六进制字符，含冒号分隔也可以。**不要照抄示例指纹，也不要使用 Debug 证书指纹。**

这个指纹和证书属于可公开信息；它们不会让别人获得签名能力。私钥和密码始终留在项目外。正式脚本会同时核对实际 APK 签名和已登记指纹，不能根据待检查 APK 自动修改信任配置。

保持包名 `io.github.themingverse.susecampus` 和仓库 `TheMingverse/suse-campus-login` 不变。本轮不修改 Git `origin`。

## 4. 本人执行本地正式签名

配置当前 PowerShell 的密钥路径和别名，然后运行发行入口。脚本会隐藏输入地询问密码，不需要将密码写入环境变量或文件。

```powershell
$env:SUSE_ANDROID_KEYSTORE_PATH = $campusKeyFile
$env:SUSE_ANDROID_KEY_ALIAS = 'suse-campus-android'
try {
  .\.venv\Scripts\python.exe -X utf8 tools\android_release.py --tag android-v0.4.0
  if ($LASTEXITCODE -ne 0) { throw '发行构建未通过，请按脚本提示检查。' }
} finally {
  Remove-Item Env:\SUSE_ANDROID_KEYSTORE_PATH -ErrorAction SilentlyContinue
  Remove-Item Env:\SUSE_ANDROID_KEY_ALIAS -ErrorAction SilentlyContinue
}
```

脚本会执行核心测试、Release 单元测试和 lint，构建未签名包，用官方 `apksigner` 签名，立即记录签名包 SHA-256，再检查实际 APK 的包名、版本、签名身份、权限和安全资源。签名采用三层验证：默认版本范围验证、API 24–27 的 V2 验证、API 28–32 的 V3 验证。每层都检查退出码、具体方案状态和已登记的证书指纹；任何一层失败都不导出正式发行目录。

默认工具输出中的某个方案为 `false`，可能表示该版本范围未验证它，不能单独判定签名缺失。脚本使用两次专项验证分别确认 V2、V3 真正有效，不删除任何一种要求，也不修改应用最低 Android 版本。

签名后发生验证或交付失败时，文件会保留在唯一的本地诊断目录：

```text
build/android-diagnostics/android-v0.4.0-<随机名>/
  signed-failed.apk
  diagnostics.json
  default.stdout.txt / default.stderr.txt
  v2.stdout.txt / v2.stderr.txt
  v3.stdout.txt / v3.stderr.txt
```

报告包含失败阶段、原因、签名后立即记录的哈希、保留文件哈希、预期与观察到的证书指纹、工具版本，以及各次验签退出码和输出。验签输出来自不需要密钥的 `verify` 命令；已知密码如意外出现在文本中会被遮挡。不保存签名输入、私钥文件或密钥库内容。

这些文件处于被 Git 忽略的 `build` 目录，不会由脚本自动上传。`signed-failed.apk` 是诊断用文件，不能作为已通过检查的正式版分发。诊断导出本身失败时，脚本会保留原临时 APK 并在终端提示路径；不要仅根据最后一条失败信息认定 APK 已被删除。成功发行后，临时工作目录会清理。

通过后的本地交付目录为：

```text
release/android/android-v0.4.0/
  SUSE-CampusLogin-Android-v0.4.0-release.apk
  SHA256SUMS.txt
  android-release.json
  verification.json
```

目录已存在时脚本会停止，不覆盖已有发行包。需要再次实验时，先由维护者自行核对和保管原目录，不直接删除旧发行物。

还可独立复核最终文件：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_verify.py --release-dir release/android/android-v0.4.0 --tag android-v0.4.0
Get-FileHash -Algorithm SHA256 -LiteralPath 'release/android/android-v0.4.0/SUSE-CampusLogin-Android-v0.4.0-release.apk'
```

本地构建不等于公开发布。第一次公开发布留待 6D 真机验收后单独确认；当前工作区尚有未提交的 Android 源码，报告会如实标记，不能把 HEAD 当成全部发行源码。

## 无密钥时如何检查构建

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_release.py --unsigned --tag android-v0.4.0
.\.venv\Scripts\python.exe -X utf8 tools\android_verify.py --variant release --allow-unsigned
```

输出到 `build/android-delivery/SUSE-CampusLogin-Android-v0.4.0-unsigned.apk`。这是**不可直接安装的构建中间产物**，没有正式签名，不生成更新版本信息或正式 `SHA256SUMS.txt`。检查报告里的 `signatureVerified` 和 `releaseReady` 都为 `false`。

## Debug 首次迁移到正式版

同一包名的 APK 必须具有相同的签名身份，才能覆盖升级。现有 Debug 使用调试身份，与新发行密钥不同；提高版本号也不能绕过这个限制。

迁移前先确认记得账号、密码和运营商。正式签名包准备就绪并核验通过后，再卸载 Debug、安装正式版、重新输入账号并选择服务，随后重新添加桌面小组件和控制中心磁贴。**目前只有未签名包时，不要先卸载正在使用的 Debug。**

卸载会删除该安装的账号文件与 Keystore 密钥。即使复制 `account.enc`，新安装也不能解密；本项目不提供明文导出或绕过系统隔离的迁移功能。后续正式版保持同一签名、更高 `versionCode` 和兼容数据格式，即可覆盖升级并保留配置。

## 供后续自动化使用的接口

发行脚本支持 `SUSE_ANDROID_KEYSTORE_PATH`、`SUSE_ANDROID_KEY_ALIAS`、`SUSE_ANDROID_STORE_PASSWORD`、`SUSE_ANDROID_KEY_PASSWORD`。最后一项未设置时使用容器密码。非交互环境必须通过受保护的环境变量提供密码；不得使用明文参数或提交签名配置。

这些值不会传入 Gradle 子进程，密码仅传给签名工具。脚本不输出原始签名错误内容。当前阶段不创建 GitHub Secrets、不上传密钥，也不编写 Actions 工作流。

官方依据：[应用签名](https://developer.android.com/studio/publish/app-signing)、[apksigner](https://developer.android.com/tools/apksigner)、[zipalign](https://developer.android.com/tools/zipalign)、[Android Keystore](https://developer.android.com/privacy-and-security/keystore)。
