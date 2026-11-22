# iOS 版

用 SwiftUI 写的 iPhone 客户端，协议与 `campus_login/`、`android/core/` 完全一致：探测门户、读取服务列表、按学校要求加密密码、提交登录、再探测一次确认能上网。

## 目录结构

```
ios/
├── project.yml                     # XcodeGen 工程描述（不提交 .xcodeproj）
├── SUSECampusLogin/
│   ├── App/                        # @main 入口
│   ├── Core/                       # 纯逻辑，与 Android core 一一对应
│   │   ├── Models.swift            # Failure / Block / Stage / Configuration
│   │   ├── PortalProtocol.swift    # 门户地址、编码、服务列表、登录结果分类
│   │   ├── PortalClient.swift      # pageInfo / getServices / login
│   │   ├── HttpTransport.swift     # 只走 Wi-Fi 的 URLSession 封装
│   │   ├── BigUInt.swift           # 大整数与 security.js 的 legacy 乘法
│   │   ├── RsaPassword.swift       # 学校的 RSA 密码格式
│   │   ├── LoginEngine.swift       # 一次登录的有限状态机
│   │   ├── KeychainConfigurationStore.swift
│   │   └── NetworkMonitor.swift    # Wi-Fi 是否有路（iOS 读不到 SSID）
│   ├── Service/LoginService.swift  # @MainActor 状态，供 UI 与快捷指令共用
│   ├── UI/                         # ContentView / SettingsView / CatalogView
│   ├── Intents/                    # App Intent + 快捷指令短语
│   └── Resources/                  # Info.plist、Assets.xcassets
└── SUSECampusLoginTests/
    ├── Fixtures/                   # 与 tests/、android/core 共用同一份夹具
    ├── RsaPasswordTests.swift
    ├── PortalProtocolTests.swift
    └── LoginEngineTests.swift
```

## 和 Android 版的差别

| 点 | Android | iOS |
| --- | --- | --- |
| 判断在校内 Wi-Fi | 读 SSID，要求是 `SUSE` 或 `SUSE_Hostel` | 读不到 SSID，改为「所有请求只走 Wi-Fi」+ 门户探测；首次触发本地网络权限 |
| 明文 HTTP | 只允许 `10.23.2.4` 的门户 | 同上，并在 `Info.plist` 放开 ATS |
| 凭据存储 | AndroidKeyStore + AES-256-GCM | Keychain（`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`），由系统加密 |
| 快捷入口 | 控制中心磁贴、桌面小组件 | App Intent（快捷指令、操作按钮、控制中心） |
| 后台轮询 | 无（打开时检查） | 无（打开时或点快捷指令时检查） |

不引入 Widget 和 App Group：免费个人开发者账号没有 App Group 能力，加上后签名会失败。v0.1 先用 App Intent 覆盖「快捷入口」这个需求。

## 生成工程并运行

需要 macOS + Xcode 16 或更新版本，[XcodeGen](https://github.com/yonaskolb/XcodeGen)：`brew install xcodegen`。

```bash
cd ios
xcodegen generate
open SUSECampusLogin.xcodeproj
```

`.xcodeproj` 是生成物，不提交；改工程设置在 `project.yml` 里改。

真机安装：在 Xcode 的 Signing & Capabilities 里选择自己的 Team，改一个唯一的 Bundle Identifier（免费账号不能用别人的标识），然后运行。免费账号的签名 7 天过期，续签重跑即可。

## 测试

```bash
cd ios
xcodegen generate
xcodebuild test -project SUSECampusLogin.xcodeproj -scheme SUSECampusLogin \
  -destination 'platform=iOS Simulator,name=iPhone 16'
```

`SUSECampusLoginTests/Fixtures/` 里的 `rsa_vectors.json` 和 `python_protocol.json` 直接来自 `tests/` 与 `android/core/src/test/fixtures/`，协议一旦改动，三端会同时被同一组向量发现。`LoginEngineTests` 用假的 HTTP 传输层覆盖：已经能上网、没有 Wi-Fi、登录成功、密码错误后停止重试、只刷新服务列表、配置不全、认证通过但外网仍不通。

## CI 与安装

`.github/workflows/ios.yml` 有两个 job：

- `ios`：在 `macos-15` 上生成工程并跑测试。
- `ipa`：构建一个**未签名**的 `.ipa`，作为 artifact 上传。自签工具（SideStore、AltStore、Sideloadly 等）会用自己的证书重新签名后安装；免费 Apple ID 也能装。

首次登录时系统会提示「允许访问本地网络设备」，必须允许，否则探测不到门户。

## 已知限制

- iOS 不允许 App 判断当前 Wi-Fi 的 SSID（除非申请定位权限），所以连错 Wi-Fi 时只能报「不在校园网范围内」。
- 没有常驻后台：iOS 会在切后台后挂起进程，因此沿用「打开或点快捷指令时检查」的策略，而不是 Android/Mac 那样的轮询。
- 需要 iOS 17 及以上（用到了 `ContentUnavailableView`、`symbolEffect`）。
