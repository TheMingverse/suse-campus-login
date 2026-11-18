# Android Release 三层验签与失败诊断修复报告

日期：2026-11-17。

## 结论

已修复 V2/V3 验签误判，保留默认验证，并分别在 API 24–27、API 28–32 验证 V2 和 V3。每一层都要求工具退出码为 0、证书指纹匹配，专项检查还必须明确报告对应方案为 true。正式目录生成前再次审核三层证据，不接受只根据退出码或单一方案成功放行。

已加入签名后立即计算哈希、失败 APK 隔离保留、三次验签原始输出与退出码记录、工具版本和证书记录、密码遮挡，以及诊断写入失败时保留原临时 APK 的保护。

本轮没有运行正式发行命令，没有读取、导出或复制维护者的正式私钥，没有索取密码，没有生成测试密钥或执行真实重新签名，也没有上传、创建远程 Release、提交或推送。应用仍为 **0.3.0 / code 4 / minSdk 29**，包名和已登记的正式证书指纹均未修改。

## 修改文件

| 文件 | 修改内容 |
| --- | --- |
| `tools/android_artifacts.py` | 解析签名方案状态；默认、V2、V3 三次独立核验；收集失败输出、部分超时输出及工具信息 |
| `tools/android_release.py` | 签名后立即哈希；失败保留及密码遮挡；导出前重新审核验签证据；成功清理和诊断导出失败保护 |
| `tools/android_signature_fixtures.py` | 下载或离线校验固定版本的 AOSP 公开预签名 APK，只允许 APK，不获取密钥 |
| `tests/test_android_release.py` | 更新原有测试以适应三层验签证据，保留原 32 项覆盖 |
| `tests/test_android_signature_policy.py` | 新增 14 项策略、诊断保留、遮挡和清理测试 |
| `tests/test_android_signature_integration.py` | 新增 8 项真实 SDK 验签集成测试，显式启用 |
| `tests/android_signature_fixtures.json` | 固定官方样例源码提交、文件 SHA-256 和公开测试证书指纹 |
| `docs/android-signing.md` | 补充三层验证、失败诊断目录和后续操作 |
| `docs/android-release-architecture.md` | 更新验签与诊断契约 |
| `docs/android-development.md` | 增加集成测试准备和运行命令 |
| 本报告 | 本轮结果、证据和下一步命令 |

原有工作区仍有上阶段未提交内容，本轮没有通过 reset/clean 清理或重建仓库状态。Windows/macOS 生产代码、原有打包脚本、工作流及主 README 未修改。

## 原误判与本机工具实测

原逻辑要求一次默认 `apksigner verify --verbose --print-certs` 同时打印 V2=true 和 V3=true。但 SDK 验证器按模拟的 Android 版本范围选择验证方案：从 API 29 开始并发现 V3 时，会跳过 V2。此时 V2=false 表示该轮没有验证 V2，不能据此认定 APK 不具备有效 V2。

本轮先用 Build Tools **35.0.0 / apksigner 0.9** 对官方预签名样例执行实际命令，再修改代码。相同文件的结果如下：

| 命令范围 | 退出码 | V2 状态 | V3 状态 |
| --- | --- | --- | --- |
| `verify --verbose --print-certs --min-sdk-version 29` | 0 | false | true |
| `verify --verbose --print-certs --min-sdk-version 24 --max-sdk-version 27` | 0 | true | false |
| `verify --verbose --print-certs --min-sdk-version 28 --max-sdk-version 32` | 0 | false | true |

修改后，正式 APK 默认检查仍按其实际清单的最低版本运行；另外两次专项检查负责分别证明 V2、V3 有效。没有修改应用清单的最低版本，也没有改成“V2 或 V3 任选其一”。

原始探测输出保存于 `build/android-signature-tests/sdk35-before-fix.json`。新流程的真实验证输出、状态和退出码保存在 `build/android-signature-tests/integration-results.json`。

## 失败诊断与交付保护

签名工具成功返回后，下一步立即计算签名 APK SHA-256。后续验证把这个值作为期望哈希，检查与交付复制均继续核对。三个验证即使某一层失败，通常仍会执行其余两层，完整记录结果；发生取消则保存已经取得的证据。

签名后验证或交付失败时，仅将 APK 和公开诊断信息保存到：

```text
build/android-diagnostics/android-v0.3.0-<唯一随机名>/
  signed-failed.apk
  diagnostics.json
  default.stdout.txt
  default.stderr.txt
  v2.stdout.txt
  v2.stderr.txt
  v3.stdout.txt
  v3.stderr.txt
```

报告包含失败阶段和原因、签名后立即计算的哈希、保留文件实际哈希、文件是否发生变化、预期与观察到的证书指纹、Build Tools/apksigner 版本与工具 JAR 哈希，以及每次验证的退出码、方案状态和输出。

原始输出仅来自不接收私钥或密码的 `verify` 命令；仍会遮挡意外出现的已知密码。诊断不保存签名输入对象、密钥路径、密钥库内容、私钥文件或环境变量转储。目录位于 Git 忽略的 build 下，没有上传或同步逻辑；不能将其中失败 APK 当作正式发行包。

诊断导出失败时，保留原临时工作目录中的 APK，并在终端提示路径，防止再次丢失唯一签名产物。正常保留完成后清理原临时目录；成功交付后也清理临时目录，不留下多余签名副本。递归清理前验证目标确实是本次在指定缓存目录中分配的唯一临时目录。

正式发行目录仍只有在完整检查通过后才整体导出。元数据生成时再次检查三份验签输出及正式指纹，不能通过手动设置报告中的 `releaseReady=true` 跳过这些要求。

## 自动化测试与实际结果

| 检查 | 实际结果 |
| --- | --- |
| 原有 Python/Windows 专项回归 | **135 项通过**，0 失败/错误/跳过 |
| 完整 Python 回归，显式启用真实 SDK 测试 | **189 项通过**，0 失败/错误/跳过 |
| 其中发行相关测试 | 原有 32 + 新增单元 14 + 真实集成 8 = **54 项** |
| Android Debug JVM 测试 | **102 项通过** |
| Android Release JVM 测试 | **102 项通过** |
| Debug / Release lint | 各 **0 错误、24 条警告** |
| Python/Kotlin 协议样例 | 检查通过 |
| Debug APK、设备测试 APK | 构建成功，现有核验通过 |
| 既有未签名 Release | 只读取核验，版本、安全配置、完整性等检查通过 |
| Git 空白检查 | 通过；仍有既有 LF/CRLF 提示 |

Android 构建使用 `--rerun-tasks`，输出 `BUILD SUCCESSFUL in 2m 27s`、`124 actionable tasks: 124 executed`。两种变体各 102 项由共享 core 43 项加 App 59 项组成，不应计作 204 项不同逻辑测试。24 条 lint 警告与原有基线一致，没有为了消除警告升级依赖或改业务代码。

新增单元测试覆盖：默认 V2=false 不误拒、只有 V2/只有 V3 拒绝、三层逐一检查指纹、默认失败不被专项成功覆盖、缺失/重复状态拒绝、损坏签名、超时部分输出、失败 APK 和原始输出保留、哈希变化、密码遮挡、诊断写入失败保护、成功临时文件清理、缺少三层证据不能导出。

### 真实集成测试

使用 Android 官方 AOSP `platform/tools/apksig` 公开预签名样例，固定源码提交：

```text
184702d9d18877edf9e5296c4e191cf0aa2b5fbb
```

只下载 5 个 APK，SHA-256 固定在测试清单中，没有下载密钥、生成新密钥、对样例重新签名或安装样例。测试使用清单中的公开测试证书指纹，不修改正式身份配置。部分样例清单最低版本较旧；复现 API 29 行为时，仅在测试包装的真实命令中指定 29，SDK 输出本身来自真实工具，没有模拟。

| 真实场景 | 默认/V2/V3 退出码 | 策略结果 |
| --- | --- | --- |
| V2+V3 正常 | 0 / 0 / 0 | 接受 |
| API 29 默认跳过 V2 | 0 / 0 / 0 | 默认 V2=false，专项 V2=true，正确接受 |
| 只有 V2 | 0 / 0 / 0 | V3=false，拒绝；证明没有只看退出码 |
| 只有 V3 | 0 / 1 / 0 | V2 验证失败，拒绝 |
| 损坏的真实签名 | 1 / 1 / 1 | 拒绝 |
| 证书指纹不符 | 0 / 0 / 0 | 三层都拒绝 |
| 默认失败，但两项专项成功 | 1 / 0 / 0 | 拒绝，未删除默认要求 |
| 失败产物保留 | 0 / 0 / 0，V3=false | 真实输出及 APK 正确保留，哈希一致 |

最后一项用“复制已有公开签名样例”替代签名动作，之后调用真实验签器并测试保留流程。它验证了失败处理，不声称调用过维护者私钥。临时测试发行目录、诊断目录在断言完成后清理；可复核的真实输出留在上述集成结果 JSON。

主要命令：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\android_build.py :core:test :app:testDebugUnitTest :app:testReleaseUnitTest :app:lintDebug :app:lintRelease :app:assembleDebug :app:assembleDebugAndroidTest -- --rerun-tasks
.\.venv\Scripts\python.exe -B -X utf8 tools\android_signature_fixtures.py --check
$env:SUSE_ANDROID_SIGNATURE_INTEGRATION = '1'
# 完整回归完成后已移除这个临时环境变量。
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -B -X utf8 tools\android_protocol_vectors.py --check
.\.venv\Scripts\python.exe -B -X utf8 tools\android_verify.py
.\.venv\Scripts\python.exe -B -X utf8 tools\android_verify.py --variant release --allow-unsigned --apk build/android-delivery/SUSE-CampusLogin-Android-v0.3.0-unsigned.apk
git diff --check
```

原有 135 项另按原先 7 个测试文件单独运行，结果保存在 `build/android-signature-tests/original-python-windows.json`。本轮没有调用 `:app:assembleRelease` 或正式发行命令。

## 尚未验证与下一步

当前没有已知阻塞这次修复的自动测试问题。维护者正式密钥的真实签名重试和手机安装尚未执行，这是本轮明确保留的操作边界。之前失败时被清理的签名包不能恢复，本轮测试不替代那份 APK 的追溯核验。

集成测试默认关闭，普通环境不具备 SDK 时不会自动下载依赖。只有显式启用并准备样例后，才能将真实集成测试计为通过；本轮已实际启用执行。真机安装和校园网现场回归仍需后续验收。

在维护者本人已经设置原有密钥路径和别名的终端中，下一步正式构建命令保持：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\android_release.py --tag android-v0.3.0
```

无需重新生成密钥或修改已登记指纹。脚本如需密码，将在维护者本机隐藏输入；不需要向 AI 提供密码。通过后检查正式报告中的三项 `signatureChecks` 均为 passed，专项 V2/V3 分别为 true，且三次证书指纹均为已登记身份。若失败，按终端提示查看本地隔离诊断目录，不上传其中 APK。
