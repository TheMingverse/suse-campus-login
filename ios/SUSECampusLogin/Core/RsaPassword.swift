import Foundation

/// The school's `security.js` password format: reversed UTF-16 units, 16-bit
/// limbs, raw RSA blocks over an oversized chunk. This is a legacy wire format,
/// not PKCS#1/OAEP, and it is intentionally not interchangeable with either.
enum RsaPassword {
    static func encrypt(password: String, mac: String, exponentHex: String, modulusHex: String) throws -> String {
        guard let exponent = BigUInt(hex: exponentHex), let modulus = BigUInt(hex: modulusHex) else {
            throw Failure.manual
        }
        let bits = modulus.bitCount
        guard bits >= 512, bits <= 4096, exponent > BigUInt(1), exponent < modulus else {
            throw Failure.manual
        }
        let chunk = 2 * ((bits - 1) / 16)
        guard chunk > 1 else { throw Failure.manual }

        var units = Array((password + ">" + mac).utf16).map { UInt32($0) }
        units.reverse()
        while units.count % chunk != 0 { units.append(0) }

        var results: [String] = []
        results.reserveCapacity(units.count / chunk)
        var offset = 0
        while offset < units.count {
            var digits = [UInt32]()
            digits.reserveCapacity(chunk / 2)
            var index = 0
            while index < chunk {
                digits.append(units[offset + index] + (units[offset + index + 1] << 8))
                index += 2
            }

            let initial: BigUInt
            if (exponent.limbs[0] & 1) == 1 {
                initial = LegacyMultiply.product([1], digits).remainder(dividingBy: modulus)
            } else {
                initial = BigUInt(1)
            }
            let squared = LegacyMultiply.product(digits, digits).remainder(dividingBy: modulus)
            let powered = squared.power(exponent.halved, modulus: modulus)
            var hex = initial.multiplied(by: powered).remainder(dividingBy: modulus).hexString
            while hex.count % 4 != 0 { hex = "0" + hex }
            results.append(hex)
            offset += chunk
        }
        return results.joined(separator: " ")
    }
}
