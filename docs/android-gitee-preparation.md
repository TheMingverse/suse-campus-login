# Gitee 镜像仓库准备记录

日期：2026 年 11 月 17 日（北京时间）。这是 6C-1 交付后、维护者另行要求继续执行的仓库准备工作，不修改 6C-1 报告的历史结论。

## 已完成

- 维护者在专用 Edge 浏览器窗口中亲自登录，核对账号为 `TheMingverse`。
- 使用该浏览器创建公开仓库：[TheMingverse/suse-campus-login](https://gitee.com/TheMingverse/suse-campus-login)。
- 仓库简介：SUSE Campus Login 国内发行镜像。主代码仓库：https://github.com/TheMingverse/suse-campus-login
- 初始化 README，并通过 Gitee 网页编辑整理中英文 `README.md`、`README.en.md`。两份文档只介绍镜像用途、链接 GitHub 主仓库/发行页，并说明当前镜像尚无安装包。
- GitHub 继续作为主代码仓库，Gitee 用于国内发行镜像；没有导入或同步项目源码。

Gitee 创建的默认分支为 `master`。本轮没有修改默认分支，也没有把本地仓库关联或切换到该分支。

网页编辑期间出现 Gitee 滑块安全验证，由维护者本人完成。没有索取密码或验证码、生成访问令牌、添加 SSH 密钥或导出浏览器登录凭据。后续浏览器会话过期时仍需维护者重新登录。

## 真实匿名访问核查

以下检查使用不附带登录信息的独立 HTTP 请求；不是依靠已登录浏览器判断公开可用。

| 检查 | 结果 |
| --- | --- |
| 仓库主页 | HTTP 200 |
| 仓库 API | HTTP 200，owner 为 `TheMingverse`，public=true，private=false |
| Release 列表 API | HTTP 200，返回空数组 `[]` |
| 与现有客户端相同的分页/排序查询 | HTTP 200，`per_page=100&page=1&direction=desc`，返回空数组 |
| Tag 列表 | HTTP 200，返回空数组 |
| 根目录内容列表 | HTTP 200，仅包含两份 README |
| 两份 README | HTTP 200，解码后核对实际内容，确认没有初始化模板的占位文字 |
| 匿名 Git 读取 | 禁用凭据助手后执行 `git ls-remote --heads`，退出码 0，读取到 `refs/heads/master` |

Release 查询地址：

```text
https://gitee.com/api/v5/repos/TheMingverse/suse-campus-login/releases?per_page=100&page=1&direction=desc
```

空数组表示目前没有发行版；不能据此宣称 App 已有镜像更新、双平台已同步或真实 APK 下载已通过。

远端网页操作产生三次提交：初始化、中文 README 整理、英文 README 整理。最新提交为 `86505c7bb51f7d7439dfbb939450093227e81a7a`。这些是 Gitee 网页保存说明文件产生的记录；本轮没有执行本地 `git push` 或向 GitHub 写入。

## 应用配置与本地产物

`android/update-sources.json` 继续保持：

```json
{"giteeRepository": null}
```

当前还没有可用正式镜像发行包，因此先不改变应用默认 AUTO 渠道的行为。以后默认启用时使用 `TheMingverse/suse-campus-login`；编译默认值需要进入后续获准构建的 APK，不会自动改变用户已经安装的版本。

以下内容已复核未变：

- 本地 origin：`https://github.com/tsiskjsjs532-hash/suse-campus-login.git`。
- versionName `0.3.0`、versionCode `4`、Tag `android-v0.3.0`。
- 现有正式发行目录四个文件的 SHA-256，与 6C-1 证据记录全部一致。
- 正式 APK SHA-256：`d85d496f66680a57d2219342176e17ffb0ce2f74fe6ebf3c2115314cd4d5038a`。

## 验收边界与下一步

**仓库创建、浏览器连接、公开访问及空发行列表检查已经完成。** 尚未验证真实发行附件列表、附件下载、CDN 跳转、应用更新安装或远程双平台一致性；当前没有 Release，也没有 Tag。

下一步应完成 6D 真机验收，并由维护者确定后续版本及首次公开发行。获准后，使用同一份正式签名构建、相同 Tag 和四文件发行包进行双平台分发，分别匿名下载后运行已有 `android_release_parity.py`。有真实可用发行包并完成验证后，再启用应用默认镜像配置。

本轮没有上传 APK、创建发行版/Tag、改 origin、Git push、读取正式私钥、创建 Secrets 或自动发布工作流，也没有升级版本、修改或删除既有正式产物。

本轮没有修改应用或发行工具代码，因此未重新运行 6C-1 的完整自动化套件；验证内容是上述真实仓库访问、网页内容检查和本地文件哈希核对。

详细机器可读证据保存在 `build/android/gitee-repository-preparation.json`，只含公开仓库信息和本地检查结果。
