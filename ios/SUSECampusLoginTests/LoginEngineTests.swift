import XCTest
@testable import SUSECampusLogin

final class StubTransport: HttpTransport, @unchecked Sendable {
    typealias Handler = (HttpRequest) throws -> HttpReply

    private let lock = NSLock()
    private var log: [HttpRequest] = []
    private let handler: Handler

    init(handler: @escaping Handler) {
        self.handler = handler
    }

    var requests: [HttpRequest] {
        lock.lock()
        defer { lock.unlock() }
        return log
    }

    func send(_ request: HttpRequest) async throws -> HttpReply {
        lock.lock()
        log.append(request)
        lock.unlock()
        return try handler(request)
    }
}

final class MemoryStore: ConfigurationStore, @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Configuration

    init(_ configuration: Configuration = .empty) {
        var start = configuration
        if start.revision < 1 { start.revision = 1 }
        stored = start
    }

    func load() throws -> Configuration {
        lock.lock()
        defer { lock.unlock() }
        return stored
    }

    func save(_ configuration: Configuration) throws {
        lock.lock()
        defer { lock.unlock() }
        var next = configuration
        next.revision = max(next.revision + 1, 1)
        stored = next
    }

    func setBlock(_ block: Block?, revision: Int64) throws {
        lock.lock()
        defer { lock.unlock() }
        guard stored.revision == revision else { throw Failure.changed }
        stored.block = block
        stored.revision = revision + 1
    }

    var current: Configuration {
        lock.lock()
        defer { lock.unlock() }
        return stored
    }
}

struct StubWiFi: WiFiAvailability {
    var isOnWiFi: Bool = true
}

/// Pretends to be a campus network: captive-portal probes first, then the
/// `InterFace.do` endpoints the client expects.
final class PortalNetwork {
    static let portal = URL(
        string: "http://10.23.2.4/eportal/index.jsp?wlanuserip=10.0.0.7&wlanacname=yb-ac&mac=ab%3Acd"
    )!

    static var redirectBody: String {
        "<html><script>window.location.replace(\"\(portal.absoluteString)\");</script></html>"
    }

    private(set) var probeCallCount = 0
    var probeBodies: [String]
    var loginResponse: String
    var pageInfoResponse: String
    var catalogResponse: String

    init(
        probeBodies: [String],
        loginResponse: String = #"{"result":"success"}"#,
        pageInfoResponse: String = #"{"passwordEncrypt":false}"#,
        catalogResponse: String = #"{"serviceJson":[{"serviceName":"校园网"}]}"#
    ) {
        self.probeBodies = probeBodies
        self.loginResponse = loginResponse
        self.pageInfoResponse = pageInfoResponse
        self.catalogResponse = catalogResponse
    }

    func reply(to request: HttpRequest) -> HttpReply {
        let target = request.url.absoluteString
        if target.contains("msftconnecttest") || target.contains("detectportal") {
            guard !probeBodies.isEmpty else {
                return HttpReply(status: 500, headers: [:], body: Data(), url: request.url)
            }
            let index = min(probeCallCount, probeBodies.count - 1)
            probeCallCount += 1
            return text(probeBodies[index], for: request)
        }
        if target.contains("method=pageInfo") {
            return text(pageInfoResponse, for: request)
        }
        if target.contains("method=getServices") {
            return text(catalogResponse, for: request)
        }
        if target.contains("method=login") {
            return text(loginResponse, for: request)
        }
        return HttpReply(status: 404, headers: [:], body: Data(), url: request.url)
    }

    private func text(_ body: String, for request: HttpRequest) -> HttpReply {
        HttpReply(status: 200, headers: [:], body: Data(body.utf8), url: request.url)
    }
}

final class LoginEngineTests: XCTestCase {
    private func configuration(block: Block? = nil) -> Configuration {
        Configuration(
            username: "20240001",
            password: "correct horse",
            service: "校园网",
            autoLogin: true,
            block: block,
            revision: 1
        )
    }

    /// Two portal probes, then two probe answers that say "internet works".
    private var portalThenOnline: [String] {
        [PortalNetwork.redirectBody, PortalNetwork.redirectBody, "Microsoft Connect Test", "Microsoft Connect Test"]
    }

    /// Stays behind the captive portal, so the post-login probe cannot confirm.
    private var portalOnly: [String] {
        [PortalNetwork.redirectBody, PortalNetwork.redirectBody]
    }

    func testOnlineNetworkSkipsPortal() async {
        let network = PortalNetwork(probeBodies: ["Microsoft Connect Test"])
        let transport = StubTransport(handler: network.reply)
        let engine = LoginEngine(store: MemoryStore(configuration()), transport: transport, wifi: StubWiFi())

        let report = await engine.login()
        XCTAssertEqual(report.stage, .online)
        XCTAssertEqual(transport.requests.count, 1)
    }

    func testWiFiRequirementIsReported() async {
        let network = PortalNetwork(probeBodies: ["Microsoft Connect Test"])
        let transport = StubTransport(handler: network.reply)
        let engine = LoginEngine(
            store: MemoryStore(configuration()),
            transport: transport,
            wifi: StubWiFi(isOnWiFi: false)
        )

        let report = await engine.login()
        XCTAssertEqual(report.stage, .failed)
        XCTAssertEqual(report.message, Failure.noWiFi.message)
        XCTAssertTrue(transport.requests.isEmpty)
    }

    func testSuccessfulLoginClearsBlock() async {
        let network = PortalNetwork(probeBodies: portalThenOnline)
        let transport = StubTransport(handler: network.reply)
        let store = MemoryStore(configuration())
        let engine = LoginEngine(store: store, transport: transport, wifi: StubWiFi())

        let report = await engine.login()
        XCTAssertEqual(report.stage, .online)
        XCTAssertNil(report.configuration.block)
        XCTAssertNil(store.current.block)

        let loginRequest = transport.requests.first { $0.url.absoluteString.contains("method=login") }
        let body = String(decoding: loginRequest?.body ?? Data(), as: UTF8.self)
        XCTAssertTrue(body.contains("queryString=wlanuserip%253D"), body)
        XCTAssertTrue(body.contains("passwordEncrypt=false"), body)
        XCTAssertTrue(body.hasPrefix("userId=20240001&"), body)
    }

    func testCredentialFailureIsSticky() async {
        let network = PortalNetwork(
            probeBodies: portalOnly,
            loginResponse: #"{"result":"fail","message":"密码错误"}"#
        )
        let transport = StubTransport(handler: network.reply)
        let store = MemoryStore(configuration())
        let engine = LoginEngine(store: store, transport: transport, wifi: StubWiFi())

        let first = await engine.login()
        XCTAssertEqual(first.stage, .blocked)
        XCTAssertEqual(first.configuration.block, .credentials)
        XCTAssertEqual(store.current.block, .credentials)

        let portalRequests = { transport.requests.filter { $0.url.absoluteString.contains("InterFace.do") }.count }
        let portalRequestsAfterFirst = portalRequests()
        XCTAssertGreaterThan(portalRequestsAfterFirst, 0)

        let second = await engine.login()
        XCTAssertEqual(second.stage, .blocked)
        XCTAssertEqual(store.current.block, .credentials)
        // A blocked attempt still probes once, but must never call the portal again.
        XCTAssertEqual(portalRequests(), portalRequestsAfterFirst)
    }

    func testRefreshOnlyReturnsCatalog() async {
        let network = PortalNetwork(probeBodies: portalOnly)
        let transport = StubTransport(handler: network.reply)
        let engine = LoginEngine(store: MemoryStore(.empty), transport: transport, wifi: StubWiFi())

        let report = await engine.login(refreshOnly: true)
        XCTAssertEqual(report.stage, .catalog)
        XCTAssertEqual(report.services.map { $0.name }, ["校园网"])
    }

    func testMissingConfigurationAsksForSetup() async {
        let network = PortalNetwork(probeBodies: portalOnly)
        let transport = StubTransport(handler: network.reply)
        let engine = LoginEngine(store: MemoryStore(.empty), transport: transport, wifi: StubWiFi())

        let report = await engine.login()
        XCTAssertEqual(report.stage, .setup)
    }

    func testUnverifiedBlockWhenOuterNetworkStaysDown() async {
        let network = PortalNetwork(probeBodies: portalOnly)
        let transport = StubTransport(handler: network.reply)
        let store = MemoryStore(configuration())
        let engine = LoginEngine(store: store, transport: transport, wifi: StubWiFi())

        let report = await engine.login()
        XCTAssertEqual(report.stage, .blocked)
        XCTAssertEqual(report.configuration.block, .unverified)
        XCTAssertEqual(store.current.block, .unverified)
    }
}
