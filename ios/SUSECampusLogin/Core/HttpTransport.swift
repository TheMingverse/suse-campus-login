import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

struct HttpRequest: Sendable {
    enum Method: String, Sendable {
        case get = "GET"
        case post = "POST"
    }

    var url: URL
    var method: Method = .get
    var body: Data?
    var timeout: TimeInterval = 12
}

struct HttpReply: Sendable {
    var status: Int
    var headers: [String: String]
    var body: Data
    var url: URL
}

protocol HttpTransport: Sendable {
    func send(_ request: HttpRequest) async throws -> HttpReply
}

/// Wi-Fi-only transport. iOS cannot read the SSID of the current network without
/// location permission, so the app forces every request onto Wi-Fi instead and
/// lets the portal probe decide whether the campus network is reachable.
final class URLSessionTransport: NSObject, HttpTransport, URLSessionTaskDelegate, @unchecked Sendable {
    private var session: URLSession!

    init(timeout: TimeInterval = 12) {
        super.init()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.allowsCellularAccess = false
        configuration.waitsForConnectivity = false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = timeout
        configuration.timeoutIntervalForResource = timeout + 4
        configuration.httpShouldSetCookies = true
        configuration.connectionProxyDictionary = [:]
        session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }

    deinit {
        session.invalidateAndCancel()
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }

    func send(_ request: HttpRequest) async throws -> HttpReply {
        var urlRequest = URLRequest(url: request.url)
        urlRequest.httpMethod = request.method.rawValue
        urlRequest.timeoutInterval = request.timeout
        urlRequest.cachePolicy = .reloadIgnoringLocalCacheData
        urlRequest.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        urlRequest.setValue("no-cache", forHTTPHeaderField: "Pragma")
        if let body = request.body {
            urlRequest.httpBody = body
            urlRequest.setValue(
                "application/x-www-form-urlencoded; charset=UTF-8",
                forHTTPHeaderField: "Content-Type"
            )
        }
        do {
            let (data, response) = try await session.data(for: urlRequest)
            guard let http = response as? HTTPURLResponse else { throw Failure.temporary }
            var headers: [String: String] = [:]
            for (key, value) in http.allHeaderFields {
                if let key = key as? String, let value = value as? String {
                    headers[key.lowercased()] = value
                }
            }
            return HttpReply(
                status: http.statusCode,
                headers: headers,
                body: data,
                url: http.url ?? request.url
            )
        } catch let failure as Failure {
            throw failure
        } catch {
            throw Failure.temporary
        }
    }
}
