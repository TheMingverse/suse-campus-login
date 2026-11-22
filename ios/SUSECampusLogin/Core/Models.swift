import Foundation

/// The failure classes shared with `android/core` and `campus_login`.
enum Failure: String, Error, Equatable, Sendable {
    case manual
    case credentials
    case temporary
    case service
    case noWiFi
    case outside
    case permission
    case ambiguous
    case changed

    var message: String {
        switch self {
        case .manual:
            return "无法识别认证页面，请使用学校登录页面。"
        case .credentials:
            return "账号或密码错误，请修改并保存后重试。"
        case .temporary:
            return "暂时无法连接校园网认证服务器，稍后重试。"
        case .service:
            return "原上网服务不存在或无法自动使用，请重新选择并保存。"
        case .noWiFi:
            return "未连接 Wi-Fi，请先连接 SUSE 或 SUSE_Hostel。"
        case .outside:
            return "当前不在校园网范围内，请连接校园 Wi-Fi。"
        case .permission:
            return "系统拒绝了网络访问权限，请到设置中允许。"
        case .ambiguous:
            return "当前网络状态不明确，请稍后重试。"
        case .changed:
            return "设置已被其他操作修改，请重试。"
        }
    }
}

/// Sticky reason that stops unattended retries, mirroring `Block`.
enum Block: String, Codable, Equatable, Sendable {
    case credentials
    case manual
    case unverified

    var message: String {
        switch self {
        case .credentials:
            return Failure.credentials.message
        case .manual:
            return "已暂停自动登录，请检查设置或使用学校登录页面。"
        case .unverified:
            return "校内网认证已通过，暂未确认外网连接。"
        }
    }
}

enum Stage: String, Equatable, Sendable {
    case idle
    case checking
    case preparing
    case authenticating
    case verifying
    case online
    case catalog
    case setup
    case blocked
    case failed
    case cancelled
    case busy
}

struct ServiceOption: Equatable, Identifiable, Sendable {
    let name: String
    let available: Bool
    let reason: String

    init(name: String, available: Bool = true, reason: String = "") {
        self.name = name
        self.available = available
        self.reason = reason
    }

    var id: String { name }
}

/// Mirrors `Configuration` in `android/core`.
struct Configuration: Equatable, Sendable {
    var username: String
    var password: String
    var service: String
    var autoLogin: Bool
    var block: Block?
    var revision: Int64

    static let empty = Configuration(
        username: "", password: "", service: "", autoLogin: true, block: nil, revision: 0
    )

    var complete: Bool {
        !username.trimmingCharacters(in: .whitespaces).isEmpty
            && !password.isEmpty
            && !service.isEmpty
    }
}

protocol ConfigurationStore: Sendable {
    func load() throws -> Configuration
    func save(_ configuration: Configuration) throws
    func setBlock(_ block: Block?, revision: Int64) throws
}

/// Result of one login attempt; the UI renders `stage` plus `message`.
struct LoginReport: Equatable, Sendable {
    var stage: Stage
    var message: String
    var services: [ServiceOption]
    var configuration: Configuration

    static func failed(_ failure: Failure, configuration: Configuration) -> LoginReport {
        LoginReport(
            stage: .failed,
            message: failure.message,
            services: [],
            configuration: configuration
        )
    }
}

enum ProbeState: Equatable, Sendable {
    case online
    case portal(URL)
    case unsupported
    case unknown
    case temporary
}
