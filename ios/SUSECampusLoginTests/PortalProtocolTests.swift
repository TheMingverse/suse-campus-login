import XCTest
@testable import SUSECampusLogin

final class PortalProtocolTests: XCTestCase {
    func testComponentEncodingMatchesJavaScript() throws {
        let root = try TestFixture.dictionary("python_protocol")
        let items = try XCTUnwrap(root["components"] as? [[String: Any]])
        XCTAssertFalse(items.isEmpty)
        for item in items {
            let input = try XCTUnwrap(item["input"] as? String)
            let expected = try XCTUnwrap(item["expected"] as? String)
            XCTAssertEqual(PortalProtocol.encodeComponent(input), expected, input)
        }
    }

    func testFormEncodingMatchesPython() throws {
        let root = try TestFixture.dictionary("python_protocol")
        let forms = try XCTUnwrap(root["forms"] as? [[String: Any]])
        for form in forms {
            let fields = try XCTUnwrap(form["fields"] as? [String: Any])
            let double = try XCTUnwrap(form["double"] as? Bool)
            let expected = try XCTUnwrap(form["expected"] as? String)
            let ordered: [(String, String)] = ["userId", "password", "queryString", "service"].map { key in
                (key, (fields[key] as? String) ?? "")
            }
            let encoded = PortalProtocol.form(ordered, double: double)
            XCTAssertEqual(String(decoding: encoded, as: UTF8.self), expected)
        }
    }

    func testConnectionQueryRoundTrip() throws {
        let root = try TestFixture.dictionary("python_protocol")
        let query = try XCTUnwrap(root["query"] as? String)
        let portalString = try XCTUnwrap(root["portal"] as? String)
        let portal = try XCTUnwrap(URL(string: portalString))

        XCTAssertTrue(PortalProtocol.isTrustedPortal(portal))
        XCTAssertEqual(try PortalProtocol.connectionQuery(from: portal), query)
        XCTAssertEqual(PortalProtocol.portalURL(query: query)?.absoluteString, portalString)
        XCTAssertEqual(
            PortalProtocol.pageInfoURL(portal: portal)?.absoluteString,
            "http://10.23.2.4/eportal/InterFace.do?method=pageInfo"
        )
        XCTAssertEqual(
            PortalProtocol.loginURL(portal: portal)?.absoluteString,
            "http://10.23.2.4/eportal/InterFace.do?method=login"
        )
        XCTAssertEqual(
            PortalProtocol.servicesURL(portal: portal, query: query)?.absoluteString,
            "http://10.23.2.4/eportal/InterFace.do?method=getServices&queryString="
                + PortalProtocol.encodeComponent(query)
        )
    }

    func testRejectsUntrustedPortals() {
        let untrusted = [
            "https://10.23.2.4/eportal/index.jsp?wlanuserip=a&wlanacname=b&mac=c",
            "http://10.23.2.5/eportal/index.jsp?wlanuserip=a&wlanacname=b&mac=c",
            "http://10.23.2.4:1080/eportal/index.jsp?wlanuserip=a&wlanacname=b&mac=c",
            "http://10.23.2.4/eportal/other.jsp?wlanuserip=a&wlanacname=b&mac=c",
            "http://user@10.23.2.4/eportal/index.jsp?wlanuserip=a&wlanacname=b&mac=c"
        ]
        for text in untrusted {
            let url = URL(string: text)
            XCTAssertFalse(url.map(PortalProtocol.isTrustedPortal) ?? true, text)
        }
        let partial = URL(string: "http://10.23.2.4/eportal/index.jsp?wlanuserip=a&mac=c")!
        XCTAssertThrowsError(try PortalProtocol.connectionQuery(from: partial))
    }

    func testCatalogParsing() throws {
        let root = try TestFixture.dictionary("python_protocol")
        let catalogs = try XCTUnwrap(root["catalogs"] as? [[String: Any]])
        for catalog in catalogs {
            let payload = try XCTUnwrap(catalog["payload"] as? [String: Any])
            let expected = try XCTUnwrap(catalog["expected"] as? [[String: Any]])
            let options = try PortalProtocol.parseServices(payload)
            XCTAssertEqual(options.count, expected.count)
            for (option, item) in zip(options, expected) {
                XCTAssertEqual(option.name, item["name"] as? String)
                XCTAssertEqual(option.available, item["available"] as? Bool)
            }
        }
    }

    func testLoginOutcomeClassification() throws {
        let root = try TestFixture.dictionary("python_protocol")
        let outcomes = try XCTUnwrap(root["outcomes"] as? [[String: Any]])
        for outcome in outcomes {
            let data = try XCTUnwrap(outcome["data"] as? [String: Any])
            let expected = try XCTUnwrap(outcome["expected"] as? String)
            switch expected {
            case "success":
                XCTAssertNoThrow(try PortalProtocol.classifyLogin(data))
            case "credentials":
                assertFailure(data, equals: .credentials)
            case "manual":
                assertFailure(data, equals: .manual)
            case "temporary":
                assertFailure(data, equals: .temporary)
            default:
                XCTFail("unexpected outcome \(expected)")
            }
        }
    }

    private func assertFailure(_ data: [String: Any], equals expected: Failure) {
        XCTAssertThrowsError(try PortalProtocol.classifyLogin(data)) { error in
            XCTAssertEqual(error as? Failure, expected)
        }
    }

    func testLoginFieldsOrderAndTrimming() throws {
        let configuration = Configuration(
            username: " 20240001 ",
            password: "pw",
            service: "校园网",
            autoLogin: true,
            block: nil,
            revision: 1
        )
        let fields = try PortalProtocol.loginFields(
            configuration: configuration,
            query: "wlanuserip=a&wlanacname=b&mac=ab%3Acd",
            info: [:]
        )
        XCTAssertEqual(
            fields.map { $0.0 },
            ["userId", "password", "service", "queryString", "operatorPwd", "operatorUserId", "validcode", "passwordEncrypt"]
        )
        XCTAssertEqual(fields[0].1, "20240001")
        XCTAssertEqual(fields[7].1, "false")
    }

    func testCaptchaInterruptsLogin() {
        let configuration = Configuration(
            username: "u", password: "p", service: "s", autoLogin: true, block: nil, revision: 1
        )
        XCTAssertThrowsError(
            try PortalProtocol.loginFields(
                configuration: configuration,
                query: "mac=ab",
                info: ["validCodeUrl": "/captcha.png"]
            )
        ) { error in
            XCTAssertEqual(error as? Failure, .manual)
        }
    }

    func testRedirectParserFindsPortalFromScript() {
        let portal = "http://10.23.2.4/eportal/index.jsp?wlanuserip=1&wlanacname=ac&mac=ab%3Acd"
        let reply = HttpReply(
            status: 200,
            headers: [:],
            body: Data("<script>location.href = \"\(portal)\";</script>".utf8),
            url: URL(string: "http://www.msftconnecttest.com/connecttest.txt")!
        )
        XCTAssertEqual(RedirectParser.portalURL(from: reply)?.absoluteString, portal)
    }

    func testRedirectParserIgnoresForeignHost() {
        let reply = HttpReply(
            status: 302,
            headers: ["location": "http://10.23.2.4.evil.com/eportal/index.jsp?wlanuserip=1&wlanacname=ac&mac=ab"],
            body: Data(),
            url: URL(string: "http://www.msftconnecttest.com/connecttest.txt")!
        )
        XCTAssertNil(RedirectParser.portalURL(from: reply))
    }
}
