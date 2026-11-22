import Foundation

/// One bounded login attempt, never a polling loop: iOS has no background
/// service that could keep retrying, so Shortcuts automations drive repeat
/// attempts instead.
actor LoginEngine {
    private let store: ConfigurationStore
    private let transport: HttpTransport
    private let wifi: WiFiAvailability
    private var running = false

    init(
        store: ConfigurationStore,
        transport: HttpTransport = URLSessionTransport(),
        wifi: WiFiAvailability = NetworkMonitor.shared
    ) {
        self.store = store
        self.transport = transport
        self.wifi = wifi
    }

    func login(refreshOnly: Bool = false) async -> LoginReport {
        var configuration = (try? store.load()) ?? .empty

        if running {
            return LoginReport(
                stage: .busy,
                message: "正在登录，请稍候。",
                services: [],
                configuration: configuration
            )
        }
        running = true
        defer { running = false }

        guard wifi.isOnWiFi else {
            return LoginReport.failed(.noWiFi, configuration: configuration)
        }

        let probe = await NetworkProbe(transport: transport).run()
        let portal: URL
        switch probe {
        case .online:
            return LoginReport(
                stage: .online,
                message: "当前网络已经可以访问外网，无需登录。",
                services: [],
                configuration: configuration
            )
        case let .portal(url):
            portal = url
        case .unsupported:
            return LoginReport(
                stage: .failed,
                message: "无法识别认证页面，请使用学校登录页面。",
                services: [],
                configuration: configuration
            )
        case .temporary:
            return LoginReport.failed(.temporary, configuration: configuration)
        case .unknown:
            return LoginReport(
                stage: .failed,
                message: "未检测到校园网认证页面，请确认已连接 SUSE 或 SUSE_Hostel。",
                services: [],
                configuration: configuration
            )
        }

        if !refreshOnly, let block = configuration.block, block == .credentials || configuration.autoLogin {
            return LoginReport(
                stage: .blocked,
                message: block.message,
                services: [],
                configuration: configuration
            )
        }

        let client = PortalClient(transport: transport)
        let prepared: PortalClient.Prepared
        do {
            prepared = try await client.prepare(portal: portal)
        } catch let failure as Failure {
            return LoginReport(
                stage: .failed,
                message: failure.message,
                services: [],
                configuration: configuration
            )
        } catch {
            return LoginReport.failed(.manual, configuration: configuration)
        }

        if refreshOnly {
            return LoginReport(
                stage: .catalog,
                message: "已刷新上网服务列表，请选择后保存。",
                services: prepared.services,
                configuration: configuration
            )
        }

        guard configuration.complete else {
            return LoginReport(
                stage: .setup,
                message: "请先填写账号、密码，并选择上网服务。",
                services: prepared.services,
                configuration: configuration
            )
        }

        do {
            _ = try PortalProtocol.requireService(prepared.services, configuration.service)
        } catch let failure as Failure {
            return LoginReport(
                stage: .failed,
                message: failure.message,
                services: prepared.services,
                configuration: configuration
            )
        } catch {
            return LoginReport(
                stage: .failed,
                message: Failure.service.message,
                services: prepared.services,
                configuration: configuration
            )
        }

        configuration = await markBlock(.unverified, configuration: configuration)
        guard configuration.block == .unverified else {
            return LoginReport(
                stage: .failed,
                message: Failure.changed.message,
                services: prepared.services,
                configuration: configuration
            )
        }

        do {
            try await client.authenticate(portal: portal, configuration: configuration, prepared: prepared)
        } catch let failure as Failure {
            let block: Block
            switch failure {
            case .credentials:
                block = .credentials
            case .manual, .service:
                block = .manual
            default:
                block = .unverified
            }
            let updated = await markBlock(block, configuration: configuration)
            return LoginReport(
                stage: .blocked,
                message: block.message,
                services: prepared.services,
                configuration: updated
            )
        } catch {
            let updated = await markBlock(.unverified, configuration: configuration)
            return LoginReport(
                stage: .blocked,
                message: Block.unverified.message,
                services: prepared.services,
                configuration: updated
            )
        }

        let verified = await NetworkProbe(transport: transport).run()
        if verified == .online {
            let updated = await markBlock(nil, configuration: configuration)
            return LoginReport(
                stage: .online,
                message: "已连接校园网，可以正常上网。",
                services: prepared.services,
                configuration: updated
            )
        }
        let updated = await markBlock(.unverified, configuration: configuration)
        return LoginReport(
            stage: .blocked,
            message: configuration.service == "校园网"
                ? "校内网认证已通过，暂未确认外网连接。"
                : Block.unverified.message,
            services: prepared.services,
            configuration: updated
        )
    }

    /// Persists a block reason and re-reads the configuration so later writes
    /// carry the newer revision instead of failing the CAS check.
    private func markBlock(_ block: Block?, configuration: Configuration) async -> Configuration {
        do {
            try store.setBlock(block, revision: configuration.revision)
            var updated = (try? store.load()) ?? configuration
            updated.block = block
            return updated
        } catch {
            return configuration
        }
    }
}
