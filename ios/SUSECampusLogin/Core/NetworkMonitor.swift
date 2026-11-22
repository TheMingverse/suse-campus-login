import Foundation
import Network

/// Whether the device currently has a Wi-Fi path. iOS cannot reveal the SSID
/// without location permission, so the app only checks that Wi-Fi is up and
/// keeps every request on Wi-Fi (`allowsCellularAccess = false`).
protocol WiFiAvailability: Sendable {
    var isOnWiFi: Bool { get }
}

final class NetworkMonitor: WiFiAvailability, @unchecked Sendable {
    static let shared = NetworkMonitor()

    private let monitor: NWPathMonitor
    private let lock = NSLock()
    private var satisfied = false
    private let queue = DispatchQueue(label: "io.github.themingverse.susecampuslogin.wifi")

    init() {
        monitor = NWPathMonitor(requiredInterfaceType: .wifi)
        monitor.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            self.lock.lock()
            self.satisfied = path.status == .satisfied
            self.lock.unlock()
        }
        monitor.start(queue: queue)
    }

    deinit {
        monitor.cancel()
    }

    var isOnWiFi: Bool {
        lock.lock()
        defer { lock.unlock() }
        return satisfied
    }
}
