import Foundation
import Security

/// Keychain-backed configuration store. Mirrors the Android store's revision
/// counter so that a stale in-flight login cannot silently overwrite newer
/// settings: `setBlock` only succeeds for the revision it was loaded with.
struct KeychainConfigurationStore: ConfigurationStore {
    static let shared = KeychainConfigurationStore(
        service: "io.github.themingverse.susecampuslogin",
        account: "configuration"
    )

    let service: String
    let account: String

    private struct Stored: Codable {
        var version: Int
        var username: String
        var password: String
        var service: String
        var autoLogin: Bool
        var block: Block?
        var revision: Int64

        init(configuration: Configuration) {
            version = 1
            username = configuration.username
            password = configuration.password
            service = configuration.service
            autoLogin = configuration.autoLogin
            block = configuration.block
            revision = configuration.revision
        }

        var configuration: Configuration {
            Configuration(
                username: username,
                password: password,
                service: service,
                autoLogin: autoLogin,
                block: block,
                revision: revision
            )
        }
    }

    func load() throws -> Configuration {
        guard let data = try read() else { return .empty }
        guard let stored = try? JSONDecoder().decode(Stored.self, from: data) else {
            return .empty
        }
        return stored.configuration
    }

    func save(_ configuration: Configuration) throws {
        var next = configuration
        next.revision = Self.nextRevision(after: configuration.revision)
        try write(JSONEncoder().encode(Stored(configuration: next)))
    }

    func setBlock(_ block: Block?, revision: Int64) throws {
        var configuration = try load()
        guard configuration.revision == revision else { throw Failure.changed }
        configuration.block = block
        configuration.revision = Self.nextRevision(after: revision)
        try write(JSONEncoder().encode(Stored(configuration: configuration)))
    }

    static func nextRevision(after revision: Int64) -> Int64 {
        let now = Int64(Date().timeIntervalSince1970 * 1000)
        return max(now, revision + 1)
    }

    private func read() throws -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = item as? Data else { throw Failure.manual }
        return data
    }

    private func write(_ data: Data) throws {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var create = query
            create[kSecValueData as String] = data
            create[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            let added = SecItemAdd(create as CFDictionary, nil)
            guard added == errSecSuccess else { throw Failure.manual }
            return
        }
        guard status == errSecSuccess else { throw Failure.manual }
    }
}
