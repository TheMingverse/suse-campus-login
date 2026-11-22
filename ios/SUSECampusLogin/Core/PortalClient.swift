import Foundation

/// Extracts a trusted campus portal URL from a captive-portal style redirect.
enum RedirectParser {
    static func portalURL(from reply: HttpReply) -> URL? {
        var candidates: [String] = []
        if let location = reply.headers["location"] { candidates.append(location) }
        if let refresh = reply.headers["refresh"], let target = refreshTarget(refresh) {
            candidates.append(target)
        }
        let body = String(decoding: reply.body.prefix(200_000), as: UTF8.self)
        candidates.append(contentsOf: scriptTargets(in: body))
        if let meta = metaRefreshTarget(in: body) { candidates.append(meta) }

        for candidate in candidates {
            guard let url = resolve(candidate, against: reply.url) else { continue }
            guard PortalProtocol.isTrustedPortal(url) else { continue }
            guard (try? PortalProtocol.connectionQuery(from: url)) != nil else { continue }
            return url
        }
        return nil
    }

    static func refreshTarget(_ value: String) -> String? {
        guard let range = value.range(of: "url=", options: .caseInsensitive) else { return nil }
        return String(value[range.upperBound...])
            .trimmingCharacters(in: CharacterSet(charactersIn: "'\""))
    }

    static func resolve(_ raw: String, against base: URL) -> URL? {
        let cleaned = PortalProtocol.unescapeHTML(raw.trimmingCharacters(in: .whitespacesAndNewlines))
        guard !cleaned.isEmpty else { return nil }
        if let absolute = URL(string: cleaned), absolute.scheme != nil { return absolute }
        return URL(string: cleaned, relativeTo: base)?.absoluteURL
    }

    static func scriptTargets(in body: String) -> [String] {
        let patterns = [
            "location\\.href\\s*=\\s*[\"']([^\"']+)[\"']",
            "location\\.replace\\s*\\(\\s*[\"']([^\"']+)[\"']",
            "window\\.location\\s*=\\s*[\"']([^\"']+)[\"']"
        ]
        var results: [String] = []
        for pattern in patterns {
            guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { continue }
            let range = NSRange(body.startIndex ..< body.endIndex, in: body)
            for match in regex.matches(in: body, options: [], range: range) {
                guard let capture = Range(match.range(at: 1), in: body) else { continue }
                results.append(String(body[capture]))
            }
        }
        return results
    }

    static func metaRefreshTarget(in body: String) -> String? {
        let pattern = "<meta[^>]+http-equiv\\s*=\\s*[\"']?refresh[\"']?[^>]*"
            + "content\\s*=\\s*[\"']([^\"']+)[\"']"
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { return nil }
        let range = NSRange(body.startIndex ..< body.endIndex, in: body)
        guard let match = regex.firstMatch(in: body, options: [], range: range),
              let capture = Range(match.range(at: 1), in: body) else { return nil }
        return refreshTarget(String(body[capture])) ?? String(body[capture])
    }
}

/// Runs the captive portal probes in order, mirroring `NetworkProbe`.
struct NetworkProbe {
    let transport: HttpTransport

    init(transport: HttpTransport) {
        self.transport = transport
    }

    func run() async -> ProbeState {
        var portal: URL?
        var responded = false
        var sawFailure = false
        for probe in PortalProtocol.probes {
            guard let url = URL(string: probe.url) else { continue }
            do {
                let reply = try await transport.send(
                    HttpRequest(url: url, method: .get, body: nil, timeout: 8)
                )
                if reply.status == 200,
                   let text = String(data: reply.body, encoding: .utf8),
                   text.trimmingCharacters(in: .whitespacesAndNewlines) == probe.expected {
                    return .online
                }
                if (200 ..< 400).contains(reply.status) {
                    responded = true
                    if let found = RedirectParser.portalURL(from: reply) {
                        portal = found
                    }
                }
            } catch {
                sawFailure = true
            }
        }
        if let portal { return .portal(portal) }
        if responded { return .unsupported }
        return sawFailure ? .temporary : .unknown
    }
}

final class PortalClient: @unchecked Sendable {
    struct Prepared {
        let id = UUID()
        let portal: URL
        let query: String
        let info: [String: Any]
        let services: [ServiceOption]
    }

    private let transport: HttpTransport
    private var prepared: Prepared?
    private var preparedUsed = false

    init(transport: HttpTransport) {
        self.transport = transport
    }

    func prepare(portal: URL) async throws -> Prepared {
        let query = try PortalProtocol.connectionQuery(from: portal)
        guard let pageInfo = PortalProtocol.pageInfoURL(portal: portal) else { throw Failure.manual }
        let info = try await post(pageInfo, body: PortalProtocol.form([("queryString", query)]))

        guard let servicesURL = PortalProtocol.servicesURL(portal: portal, query: query) else {
            throw Failure.manual
        }
        let catalog = try await post(servicesURL, body: Data())
        let services = try PortalProtocol.parseServices(catalog)

        let prepared = Prepared(portal: portal, query: query, info: info, services: services)
        self.prepared = prepared
        self.preparedUsed = false
        return prepared
    }

    func authenticate(portal: URL, configuration: Configuration, prepared: Prepared?) async throws {
        let query = try PortalProtocol.connectionQuery(from: portal)
        let current: Prepared
        if let prepared {
            guard let stored = self.prepared, stored.id == prepared.id, !preparedUsed else {
                throw Failure.manual
            }
            current = prepared
        } else {
            current = try await prepare(portal: portal)
        }
        preparedUsed = true
        self.prepared = nil

        _ = try PortalProtocol.requireService(current.services, configuration.service)
        let fields = try PortalProtocol.loginFields(
            configuration: configuration,
            query: query,
            info: current.info
        )
        guard let loginURL = PortalProtocol.loginURL(portal: portal) else { throw Failure.manual }
        let outcome = try await post(loginURL, body: PortalProtocol.form(fields, double: true))
        try PortalProtocol.classifyLogin(outcome)
    }

    private func post(_ url: URL, body: Data) async throws -> [String: Any] {
        let reply: HttpReply
        do {
            reply = try await transport.send(HttpRequest(url: url, method: .post, body: body, timeout: 12))
        } catch let failure as Failure {
            throw failure
        } catch {
            throw Failure.temporary
        }
        // A redirect means the request never reached the portal API; `requests`
        // treats that as a value error (manual) and so does this transport.
        if (300 ..< 400).contains(reply.status) { throw Failure.manual }
        guard (200 ..< 300).contains(reply.status) else { throw Failure.temporary }
        guard reply.body.count <= 200_000 else { throw Failure.manual }
        let data = reply.body
        var start = data.startIndex
        if data.count >= 3, data[data.startIndex] == 0xEF, data[data.startIndex + 1] == 0xBB, data[data.startIndex + 2] == 0xBF {
            start = data.index(data.startIndex, offsetBy: 3)
        }
        let payload = data[start...]
        guard let object = try? JSONSerialization.jsonObject(with: Data(payload)) else {
            throw Failure.manual
        }
        guard let dictionary = object as? [String: Any] else { throw Failure.manual }
        return dictionary
    }
}
