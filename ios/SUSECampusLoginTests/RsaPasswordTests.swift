import XCTest
@testable import SUSECampusLogin

enum TestFixture {
    static func json(_ name: String) throws -> Any {
        guard let url = Bundle(for: BundleToken.self).url(forResource: name, withExtension: "json") else {
            throw Failure.manual
        }
        let data = try Data(contentsOf: url)
        return try JSONSerialization.jsonObject(with: data)
    }

    static func dictionary(_ name: String) throws -> [String: Any] {
        guard let root = try json(name) as? [String: Any] else { throw Failure.manual }
        return root
    }
}

private final class BundleToken {}

final class RsaPasswordTests: XCTestCase {
    func testMatchesRepositoryVectors() throws {
        let root = try TestFixture.dictionary("rsa_vectors")
        let modulus = try XCTUnwrap(root["modulus"] as? String)
        let exponent = try XCTUnwrap(root["exponent"] as? String)
        let mac = try XCTUnwrap(root["mac"] as? String)
        let vectors = try XCTUnwrap(root["vectors"] as? [[String: Any]])
        XCTAssertEqual(vectors.count, 5)

        for vector in vectors {
            let password = try XCTUnwrap(vector["password"] as? String)
            let expected = try XCTUnwrap(vector["expected"] as? String)
            let actual = try RsaPassword.encrypt(
                password: password,
                mac: mac,
                exponentHex: exponent,
                modulusHex: modulus
            )
            XCTAssertEqual(
                actual,
                expected,
                "password length \(password.utf16.count) must match security.js"
            )
        }
    }

    func testLongPasswordProducesTwoBlocks() throws {
        let root = try TestFixture.dictionary("rsa_vectors")
        let actual = try RsaPassword.encrypt(
            password: String(repeating: "a", count: 160),
            mac: try XCTUnwrap(root["mac"] as? String),
            exponentHex: try XCTUnwrap(root["exponent"] as? String),
            modulusHex: try XCTUnwrap(root["modulus"] as? String)
        )
        XCTAssertEqual(actual.split(separator: " ").count, 2)
    }

    func testRejectsMalformedKeyMaterial() {
        XCTAssertThrowsError(try RsaPassword.encrypt(password: "a", mac: "ab", exponentHex: "zz", modulusHex: "00")) { error in
            XCTAssertEqual(error as? Failure, .manual)
        }
    }

    func testBigUIntModularExponentiation() {
        // Expected values computed with Python's pow(base, exponent, modulus).
        let cases: [(base: String, exponent: String, modulus: String, expected: String)] = [
            ("1234abcd", "10001", "f7e1a2c3", "baa9ced3"),
            ("deadbeef", "10001", "f7e1a2c3", "2786dc48"),
            ("1234abcd", "3", "f7e1a2c3", "b1332816"),
            ("1234567890abcdef", "10001", "ffffffffffffffc5", "a8beb3bcfd18e4f5"),
        ]
        for item in cases {
            let base = BigUInt(hex: item.base)!
            let exponent = BigUInt(hex: item.exponent)!
            let modulus = BigUInt(hex: item.modulus)!
            XCTAssertEqual(
                base.power(exponent, modulus: modulus).hexString,
                item.expected,
                "\(item.base)^\(item.exponent) mod \(item.modulus)"
            )
        }
    }

    func testBigUIntRemainderHandlesValuesAboveTheModulus() {
        // The password blocks are wider than the modulus, so the reduction has
        // to work on a dividend larger than the divisor.
        let dividend = BigUInt(hex: "ffffffffffffffffffffffff")!
        let divisor = BigUInt(hex: "f7e1a2c3")!
        XCTAssertEqual(dividend.remainder(dividingBy: divisor).hexString, "c87cb248")
    }
}
