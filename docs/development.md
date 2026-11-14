# 开发与维护 / Development and maintenance

[中文首页](../README.md) | [English homepage](../README.en.md)

本页保留开发命令、实现说明和验证边界。使用方法见项目首页。

## 中文

## 已有功能和保护

| 版本 | 主要改进 |
| --- | --- |
| 1.1.0 | 宿舍网线和 USB 转网口支持；有线优先；不同网卡分别检测、认证和复核。 |
| 1.1.1 | 多无线接口容错；单个接口失败不影响其他正常校园连接；排除虚拟有线网卡。 |
| 1.1.2 | Windows 系统通知、可保存的通知开关和去重；日常检测与短暂重试不弹通知。 |
| 1.1.3 | 学校实时运营商服务列表、只读刷新、精确匹配和新名称保存兼容。 |

- 登录前要求实时列表中存在名称完全相同且唯一可用的服务。学校改名后由你重新选择并保存，不按“移动”等关键词猜选，也不默认跳到第一项。
- 相同配置的重复项合并；同名冲突、隐藏或需要额外信息的服务不自动使用。连接、地址或设置变化后，旧结果失效。
- 已在线时可能无法取得新的认证跳转，程序保留原选择并提示暂时无法更新列表；无需为了刷新专门断网或注销。
- 每条连接使用独立且绑定网卡与源 IPv4 的会话。有线优先，有线状态不明确才继续检查校园 Wi-Fi；认证失败不跨网卡持续提交密码。
- 只有可信学校认证地址和完整的本次连接参数允许认证；未知页面、超时、其他 Wi-Fi 或不完整参数不会触发登录。
- 当前确认的认证主机为 `10.23.2.4`，页面路径 `/eportal/index.jsp`。沿用学校 `pageInfo → getServices → login`、密码加密和编码兼容流程。
- 正常联网检查通常每 15 秒执行；临时失败按 5／15／30 秒重试，之后等五分钟。账号认证未通过后停止自动提交，保存设置后才解除。
- 不自动断网、不修改路由、不注销另一条连接。已知“校园网”服务仅开放校内资源时不宣称互联网可用；陌生新服务认证被接受但联网复核失败时暂停重复提交并要求人工确认。
- 成功通知以联网复核为准；同一故障去重。通知显示、时长和声音由 Windows 管理。

## 隐私与验证边界

每个人填写自己的账号。设置保存在 `%LOCALAPPDATA%\SUSECampusLogin`，不在程序文件夹中；账号以普通文字保存，密码由 Windows DPAPI 在本机保护。DPAPI 是保存保护，不能代替网络传输加密；学校认证页面使用 HTTP 和原有旧式密码格式。

日志仅记录固定状态码，不记录账号、密码、完整认证网址或设备参数值，轮转后总量约 384 KB；通知使用固定文案，不展示服务器原始回复。不要分享个人设置目录、密码或未遮挡账号的截图。公开示例截图及测试使用空白或合成数据；源码提交使用 GitHub 隐私邮箱。

**2026 年 11 月 11 日的 135 项自动测试全部通过**，包含原有 90 项与新增 45 项服务适配测试；另完成五个合成界面场景检查。ZIP 完整性、AMD64 架构、校验值和隔离解压启动检查通过，旧版本地包保持不变。

截至 2026-11-11，旧版宿舍 Wi-Fi 曾由使用者确认真实登录成功；1.1.3 认证测试使用合成数据，其他场景的现场记录尚待补充。2026-11-14 用户新增教室网络和网线可用的反馈，见下方补充。真实新名称登录、热点／多网卡、睡眠唤醒及另一台电脑等场景仍需分别核实。详见[验证记录](验证记录.md)。

## 开发与项目结构

开发使用 Windows 64 位 Python 3.13，当前构建环境为 Python 3.13.7。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py
```

- 只读诊断：`.\.venv\Scripts\python.exe -X utf8 main.py --diagnose`。
- 空白示例：`.\.venv\Scripts\python.exe main.py --ui-check`，不读个人设置、不登录、不保存，8 秒后退出。
- 示例窗口截图：`.\.venv\Scripts\python.exe tools\verify_ui.py --service-cases`，会更新文档截图，额外合成图片写入 `build/`。
- 模拟通知演示：`.\.venv\Scripts\python.exe -X utf8 tools\demo_notifications.py --auto`，不读个人设置、不访问网络。
- 构建：运行 `./build.ps1`，或安装构建依赖后运行 `.\.venv\Scripts\python.exe -X utf8 tools\package_release.py`；依赖快照见 [requirements-lock.txt](../requirements-lock.txt)。
- 本机发布验证：`.\.venv\Scripts\python.exe -X utf8 tools\verify_release.py`。**该脚本依赖本机保留的历史程序包及 `.cache` 校验基线，公开源码不包含这些文件。** 新下载的源码可以运行单元测试和构建当前版本，但缺少旧文件时不能完成全部历史对比。

| 模块 | 用途 |
| --- | --- |
| `adapters.py`、`windows.py`、`transport.py` | Windows 网卡识别、本机密码保护、自启动、单实例与网卡绑定请求。 |
| `network.py`、`portal.py`、`engine.py` | 联网与可信跳转检测、服务列表、认证复核、重试与取消。 |
| `models.py`、`storage.py`、`gui.py`、`notifications.py` | 数据结构、本机设置与日志、中文设置窗口、托盘与通知。 |
| `tests/`、`tools/`、`docs/` | 自动回归测试、打包验证工具及使用文档。 |

后续开发候选为动态检测频率、国内专用备用测网地址，1.1.3 尚未实现；实际网络环境验收仍应优先推进。

本项目非学校官方客户端，不绕过学校账号、计费和设备限制。第三方组件说明见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)；完整 ZIP 中保留依赖许可证及 pystray 源码。本次公开发布不新增项目许可证。

## 用户现场反馈补充 · 2026-11-14

用户在本次对话中反馈教室网络和网线可以使用。该反馈对应用户实际使用过的环境；没有提供具体教学楼、网卡型号或逐项认证记录。历史验证记录按原日期保留，自贡校区及其他电脑的兼容情况仍需分别核实。

## English

## Features and safeguards

| Version | Improvements |
| --- | --- |
| 1.1.0 | Ethernet and USB Ethernet support; wired priority; separate checks, authentication and verification per adapter. |
| 1.1.1 | Wireless interface fault isolation; multiple campus Wi-Fi adapters handled independently; virtual Ethernet adapters excluded. |
| 1.1.2 | Windows notifications, a persistent notification switch, and duplicate suppression. Routine checks and temporary retries remain silent. |
| 1.1.3 | Live campus service lists, read-only refresh, exact service matching, and persistent support for new service names. |

- A service must exactly match a unique, available entry in the current list. Renamed services require you to choose and save again; the app never guesses by operator keywords or silently selects the first entry.
- Identical duplicate entries are merged; conflicting, hidden, or extra-information services are not used automatically. Old results are invalidated when connections, addresses or settings change.
- If you are already online, the app may be unable to obtain a fresh authentication redirect. It retains your selection and reports that the list cannot currently be updated. Do not disconnect or log out just to refresh it.
- Each connection uses an independent session bound to its adapter and source IPv4 address. Wired checks take priority; an uncertain wired result may fall back to campus Wi-Fi. A failed authentication does not trigger credential submissions across other adapters.
- Only a recognized campus authentication host and path with complete current connection parameters allow authentication. Unknown pages, timeouts, unrelated Wi-Fi and incomplete redirects do not trigger credential submission.
- The current confirmed portal host is `10.23.2.4`, under `/eportal/index.jsp`. Authentication follows `pageInfo → getServices → login`, retaining the campus page's existing password encoding and encryption compatibility.
- Normal internet checks are scheduled every 15 seconds. Temporary failures retry after 5, 15 and 30 seconds, followed by a five-minute wait. Credential rejection stops automatic submissions until settings are saved.
- The app does not disconnect networks, change routes or log out another connection. The recognized campus-only service does not imply internet access. If a new service is accepted but internet verification fails, the app requests manual confirmation instead of repeatedly submitting credentials.
- Success notifications require connectivity verification. Repeated failures are suppressed; notification delivery, duration and sound are controlled by Windows.

## Privacy and verification limits

Each user enters their own account. Settings are stored in `%LOCALAPPDATA%\SUSECampusLogin`, outside the application folder. The username is stored as text; the password is protected locally by Windows DPAPI. DPAPI protects saved data and is not a replacement for transport encryption: the campus portal uses HTTP and its existing legacy password format.

Logs contain fixed state codes, not credentials, complete authentication URLs or device parameter values, and rotate to approximately 384 KB total. Notifications use fixed messages rather than raw server responses. Do not share your personal settings directory, password or unredacted account screenshots. Example images and tests use empty or synthetic data. Source commits use a GitHub privacy email.

**135 automated tests passed** on November 11, 2026: 90 existing tests and 45 service-related additions. Five additional synthetic UI layout scenarios were checked. ZIP integrity, AMD64 architecture, checksums and isolated extracted-application startup passed. Historical local releases were preserved.

As of November 11, 2026, an older dormitory Wi-Fi version had been confirmed working by the user; version 1.1.3 authentication tests used synthetic data. On November 14 the user additionally reported working classroom networking and Ethernet, as recorded below. Real renamed-service login, hotspot/multiple-adapter combinations, sleep/resume and other PCs still require separate checks. See the [detailed verification record — Chinese](验证记录.md).

## Development and project structure

Development uses 64-bit Python 3.13 on Windows; the current build environment uses Python 3.13.7.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py
```

- Read-only diagnosis: `.\.venv\Scripts\python.exe -X utf8 main.py --diagnose`.
- Blank example window: `.\.venv\Scripts\python.exe main.py --ui-check`; does not load personal settings, sign in or save settings, and exits after eight seconds.
- Example window capture: `.\.venv\Scripts\python.exe tools\verify_ui.py --service-cases`; updates the documentation screenshot and writes additional synthetic images under `build/`.
- Synthetic notification demo: `.\.venv\Scripts\python.exe -X utf8 tools\demo_notifications.py --auto`; no personal settings or network access.
- Build: `./build.ps1`, or `.\.venv\Scripts\python.exe -X utf8 tools\package_release.py` after installing the build dependencies. Dependencies are pinned in [requirements-lock.txt](../requirements-lock.txt).
- Local release verification: `.\.venv\Scripts\python.exe -X utf8 tools\verify_release.py`. **This script requires the locally retained historical packages and `.cache` checksum baselines, which are not included in this public source repository.** A fresh clone can run the unit tests and build the current application, but cannot perform the complete historical comparison without those files.

| Module | Purpose |
| --- | --- |
| `adapters.py`, `windows.py`, `transport.py` | Windows adapter discovery, local password protection, startup, single-instance behavior and interface-bound requests. |
| `network.py`, `portal.py`, `engine.py` | Connectivity and trusted-redirect detection, service lists, authentication, verification, retries and cancellation. |
| `models.py`, `storage.py`, `gui.py`, `notifications.py` | Data types, local settings and logs, Chinese settings window, tray and notifications. |
| `tests/`, `tools/`, `docs/` | Automated regression tests, packaging/verification tools and instructions. |

The next development candidates are adaptive check intervals and a dedicated domestic backup connectivity endpoint. Neither is implemented in 1.1.3. Field verification remains a priority.

This is not an official university client and does not bypass account, billing or device limits. Third-party notices remain in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md); the full ZIP contains the bundled license texts and pystray source. No new project license is added by this publication.

## Field feedback update · 2026-11-14

The user reported that classroom networking and Ethernet work in their own environment. No specific classroom, adapter model or step-by-step authentication record was supplied. Historical records retain their original dates; Zigong campus and other PCs still require separate checks.
