import Foundation
import SwiftUI

/// Observable bridge between SwiftUI, App Intents and the login actor. The
/// service owns the persisted configuration so every screen sees one source of
/// truth for the sticky block flag.
@MainActor
final class LoginService: ObservableObject {
    static let shared = LoginService()

    @Published private(set) var configuration: Configuration
    @Published private(set) var stage: Stage = .idle
    @Published private(set) var message: String = "尚未检测网络"
    @Published private(set) var services: [ServiceOption] = []
    @Published private(set) var isBusy = false

    private let store: ConfigurationStore
    private let engine: LoginEngine
    private var bootstrapped = false

    init(
        store: ConfigurationStore = KeychainConfigurationStore.shared,
        transport: HttpTransport = URLSessionTransport(),
        wifi: WiFiAvailability = NetworkMonitor.shared
    ) {
        self.store = store
        self.configuration = (try? store.load()) ?? .empty
        self.engine = LoginEngine(store: store, transport: transport, wifi: wifi)
    }

    var portalHomeURL: URL { PortalProtocol.homeURL }

    var canLogin: Bool { configuration.complete }

    func bootstrap() async {
        guard !bootstrapped else { return }
        bootstrapped = true
        if stage == .idle {
            await perform(refreshOnly: false)
        }
    }

    func login() async {
        await perform(refreshOnly: false)
    }

    func refreshServices() async {
        await perform(refreshOnly: true)
    }

    /// Entry point used by App Intents and Shortcuts automations.
    func performLogin() async -> String {
        await perform(refreshOnly: false)
        return message
    }

    @discardableResult
    func perform(refreshOnly: Bool) async -> LoginReport {
        guard !isBusy else { return currentReport() }
        isBusy = true
        defer { isBusy = false }

        let report = await engine.login(refreshOnly: refreshOnly)
        configuration = report.configuration
        stage = report.stage
        message = report.message
        if !report.services.isEmpty {
            services = report.services
            autoselectServiceIfNeeded()
        }
        return report
    }

    private func currentReport() -> LoginReport {
        LoginReport(stage: stage, message: message, services: services, configuration: configuration)
    }

    private func autoselectServiceIfNeeded() {
        guard configuration.service.isEmpty,
              let candidate = services.first(where: { $0.available }) else { return }
        var next = configuration
        next.service = candidate.name
        try? store.save(next)
        configuration = (try? store.load()) ?? next
    }

    func save(username: String, password: String, service: String, autoLogin: Bool) throws {
        var next = configuration
        next.username = username.trimmingCharacters(in: .whitespaces)
        next.password = password
        next.service = service
        next.autoLogin = autoLogin
        next.block = nil
        try store.save(next)
        configuration = (try? store.load()) ?? next
        stage = .idle
        message = "设置已保存"
    }

    func selectService(_ name: String) throws {
        var next = configuration
        next.service = name
        next.block = nil
        try store.save(next)
        configuration = (try? store.load()) ?? next
    }

    /// Clears a sticky block so the next manual attempt is allowed again.
    func clearBlock() {
        try? store.setBlock(nil, revision: configuration.revision)
        configuration = (try? store.load()) ?? configuration
        stage = .idle
        message = "已清除暂停状态，可以重新登录"
    }
}
