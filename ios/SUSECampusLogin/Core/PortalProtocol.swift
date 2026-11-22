import Foundation

/// Pure protocol rules shared with `campus_login/portal.py` and
/// `android/core/.../Protocol.kt`. No I/O here, so every rule is unit-testable.
enum PortalProtocol {
    static let host = "10.23.2.4"
    static let ssids = ["SUSE", "SUSE_Hostel"]

    struct Probe: Equatable, Sendable {
        let url: String
        let expected: String
    }

    static let probes = [
        Probe(url: "http://www.msftconnecttest.com/connecttest.txt", expected: "Microsoft Connect Test"),
        Probe(url: "http://detectportal.firefox.com/success.txt", expected: "success")
    ]

    static var homeURL: URL {
        URL(string: "http://\(host)/eportal/index.jsp")!
    }

    static func portalURL(query: String) -> URL? {
        URL(string: "http://\(host)/eportal/index.jsp?\(query)")
    }

    static func isTrustedPortal(_ url: URL) -> Bool {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return false }
        guard components.scheme?.lowercased() == "http" else { return false }
        guard components.host == host else { return false }
        if let port = components.port, port != 80, port != 8080 { return false }
        guard components.user == nil, components.password == nil else { return false }
        guard components.fragment == nil else { return false }
        return components.path.lowercased() == "/eportal/index.jsp"
    }

    /// Returns the opaque `?wlanuserip=...&wlanacname=...&mac=...` query verbatim.
    static func connectionQuery(from url: URL) throws -> String {
        guard isTrustedPortal(url) else { throw Failure.manual }
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let query = components.percentEncodedQuery else {
            throw Failure.manual
        }
        guard query.count <= 16000 else { throw Failure.manual }
        let parts = query.split(separator: "&", omittingEmptySubsequences: false)
        for key in ["wlanuserip", "wlanacname", "mac"] {
            let present = parts.contains { part in
                part.hasPrefix(key + "=") && part.count > key.count + 1
            }
            guard present else { throw Failure.manual }
        }
        return query
    }

    static func interFaceURL(portal: URL) -> URL? {
        URL(string: "InterFace.do", relativeTo: portal)?.absoluteURL
    }

    static func pageInfoURL(portal: URL) -> URL? {
        guard let base = interFaceURL(portal: portal)?.absoluteString else { return nil }
        return URL(string: base + "?method=pageInfo")
    }

    static func servicesURL(portal: URL, query: String) -> URL? {
        guard let base = interFaceURL(portal: portal)?.absoluteString else { return nil }
        return URL(string: base + "?method=getServices&queryString=" + encodeComponent(query))
    }

    static func loginURL(portal: URL) -> URL? {
        guard let base = interFaceURL(portal: portal)?.absoluteString else { return nil }
        return URL(string: base + "?method=login")
    }

    /// JavaScript `encodeURIComponent`, including its treatment of `!'()*`.
    static func encodeComponent(_ value: String) -> String {
        var result = ""
        result.reserveCapacity(value.utf8.count)
        for byte in value.utf8 {
            if isUnreserved(byte) {
                result.unicodeScalars.append(Unicode.Scalar(byte))
            } else {
                result += "%"
                result += String(format: "%02X", Int(byte))
            }
        }
        return result
    }

    private static func isUnreserved(_ byte: UInt8) -> Bool {
        if byte >= 0x30, byte <= 0x39 { return true }
        if byte >= 0x41, byte <= 0x5A { return true }
        if byte >= 0x61, byte <= 0x7A { return true }
        switch byte {
        case 0x2D, 0x5F, 0x2E, 0x21, 0x7E, 0x2A, 0x27, 0x28, 0x29: return true
        default: return false
        }
    }

    static func form(_ fields: [(String, String)], double: Bool = false) -> Data {
        let parts = fields.map { key, value -> String in
            let encoded = encodeComponent(value)
            return key + "=" + (double ? encodeComponent(encoded) : encoded)
        }
        return Data(parts.joined(separator: "&").utf8)
    }

    static func text(_ value: Any?) -> String {
        if let string = value as? String { return string }
        if let number = value as? NSNumber {
            // JSON booleans arrive as NSNumber. `objCType` is "c" only for the
            // boolean singleton, so plain numbers keep their numeric spelling,
            // which is what Python's str() would produce.
            if String(cString: number.objCType) == "c" {
                return number.boolValue ? "true" : "false"
            }
            return number.stringValue
        }
        return ""
    }

    private static func isTruthy(_ value: Any?) -> Bool {
        text(value).lowercased() == "true"
    }

    /// `str(value).lower()` with the school page's default of "false" for a
    /// missing key.
    private static func flag(_ value: Any?) -> String {
        guard let value else { return "false" }
        return text(value).lowercased()
    }

    static func isValidServiceName(_ value: String) -> Bool {
        guard !value.isEmpty, value.count <= 200 else { return false }
        guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        for scalar in value.unicodeScalars {
            switch scalar.properties.generalCategory {
            case .control, .format, .surrogate, .privateUse, .unassigned:
                return false
            default:
                continue
            }
        }
        return true
    }

    static func parseServices(_ data: [String: Any]) throws -> [ServiceOption] {
        guard let raw = data["serviceJson"] else { throw Failure.service }
        var items: [Any]
        if let string = raw as? String {
            guard let decoded = try? JSONSerialization.jsonObject(with: Data(string.utf8)),
                  let array = decoded as? [Any] else { throw Failure.service }
            items = array
        } else if let array = raw as? [Any] {
            items = array
        } else {
            throw Failure.service
        }
        guard !items.isEmpty else { throw Failure.service }

        var order: [String] = []
        var grouped: [String: (signature: String?, option: ServiceOption)] = [:]

        for item in items {
            guard let dictionary = item as? [String: Any],
                  let name = dictionary["serviceName"] as? String,
                  isValidServiceName(name) else {
                throw Failure.service
            }
            var signature: String? = canonicalJSON(dictionary)
            // A missing key means "false" in the school's page; only an
            // explicit non-"false" value hides the service.
            let hidden = flag(dictionary["aceNotShow"])
            let extra = flag(dictionary["domainName"])
            var available = hidden == "false" && extra == "false"
            var reason = available ? "" : "需要官方页面处理"

            // A conflicting duplicate stays unusable forever, even if a third
            // entry happens to match one of the earlier configurations again.
            if let previous = grouped[name], previous.signature != signature {
                available = false
                reason = "同名服务配置存在冲突"
                signature = nil
            }
            grouped[name] = (signature, ServiceOption(name: name, available: available, reason: reason))
            if !order.contains(name) { order.append(name) }
        }
        return order.compactMap { grouped[$0]?.option }
    }

    /// A stable key for "same name, different configuration" detection.
    static func canonicalJSON(_ object: Any) -> String {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys, .withoutEscapingSlashes]
              ),
              let text = String(data: data, encoding: .utf8) else {
            return ""
        }
        return text
    }

    static func requireService(_ options: [ServiceOption], _ name: String) throws -> ServiceOption {
        let matches = options.filter { $0.name == name }
        guard matches.count == 1, matches[0].available else { throw Failure.service }
        return matches[0]
    }

    static func loginFields(configuration: Configuration, query: String, info: [String: Any]) throws -> [(String, String)] {
        if !text(info["validCodeUrl"]).isEmpty { throw Failure.manual }
        if isTruthy(info["isCheckSmsAuth"]) { throw Failure.manual }
        if isTruthy(info["isToCasPage"]) { throw Failure.manual }
        if !text(info["prefixValue"]).isEmpty { throw Failure.manual }

        var password = configuration.password
        if isTruthy(info["passwordEncrypt"]) {
            password = try RsaPassword.encrypt(
                password: configuration.password,
                mac: macValue(in: query),
                exponentHex: text(info["publicKeyExponent"]),
                modulusHex: text(info["publicKeyModulus"])
            )
        }
        return [
            ("userId", configuration.username.trimmingCharacters(in: .whitespaces)),
            ("password", password),
            ("service", configuration.service),
            ("queryString", query),
            ("operatorPwd", ""),
            ("operatorUserId", ""),
            ("validcode", ""),
            ("passwordEncrypt", isTruthy(info["passwordEncrypt"]) ? "true" : "false")
        ]
    }

    static func macValue(in query: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: "(?:^|&)mac=([^&]+)") else { return "111111111" }
        let range = NSRange(query.startIndex ..< query.endIndex, in: query)
        guard let match = regex.firstMatch(in: query, options: [], range: range),
              let capture = Range(match.range(at: 1), in: query) else {
            return "111111111"
        }
        return String(query[capture])
    }

    static func classifyLogin(_ data: [String: Any]) throws {
        let message = unescapeHTML(stripTags(text(data["message"])))
        if text(data["result"]) == "success" {
            if message.contains("PWD_COMPLEX_OFFLINE_WEB") { throw Failure.manual }
            return
        }
        if matches("验证码|短信|captcha|valid.?code|verify.?code", in: message) { throw Failure.manual }
        if matches("密码|口令|用户不存在|账号不存在|帐号不存在|认证失败|password|credential|user.*not.*exist", in: message) {
            throw Failure.credentials
        }
        if matches("欠费|停机|冻结|禁用|到期|过期|在线.*(数|上限)|终端.*(数|上限)|已.*在线|already.*online|limit", in: message) {
            throw Failure.manual
        }
        if matches("超时|繁忙|稍后|timeout|busy|暂时|服务器.*(失败|异常|错误)", in: message) {
            throw Failure.temporary
        }
        throw Failure.manual
    }

    static func matches(_ pattern: String, in text: String) -> Bool {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { return false }
        let range = NSRange(text.startIndex ..< text.endIndex, in: text)
        return regex.firstMatch(in: text, options: [], range: range) != nil
    }

    static func stripTags(_ text: String) -> String {
        text.replacingOccurrences(of: "<[^>]*>", with: "", options: .regularExpression)
    }

    static func unescapeHTML(_ text: String) -> String {
        guard text.contains("&") else { return text }
        var result = ""
        result.reserveCapacity(text.count)
        var index = text.startIndex
        while index < text.endIndex {
            guard text[index] == "&",
                  let semicolon = text[index...].firstIndex(of: ";"),
                  text.distance(from: index, to: semicolon) <= 10 else {
                result.append(text[index])
                index = text.index(after: index)
                continue
            }
            let entity = String(text[text.index(after: index) ..< semicolon])
            if let replacement = decodeEntity(entity) {
                result.append(contentsOf: replacement)
                index = text.index(after: semicolon)
            } else {
                result.append(text[index])
                index = text.index(after: index)
            }
        }
        return result
    }

    private static func decodeEntity(_ entity: String) -> String? {
        switch entity.lowercased() {
        case "lt": return "<"
        case "gt": return ">"
        case "amp": return "&"
        case "quot": return "\""
        case "apos": return "'"
        case "nbsp": return " "
        default: break
        }
        guard entity.hasPrefix("#") else { return nil }
        let body = String(entity.dropFirst())
        let value: UInt32?
        if body.lowercased().hasPrefix("x") {
            value = UInt32(String(body.dropFirst()), radix: 16)
        } else {
            value = UInt32(body, radix: 10)
        }
        guard let scalarValue = value, let scalar = Unicode.Scalar(scalarValue) else { return nil }
        return String(Character(scalar))
    }
}
