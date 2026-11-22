import Foundation

/// Minimal unsigned big integer: little-endian 32-bit limbs, always normalized
/// (no most-significant zero limb). Only the operations the login protocol needs.
struct BigUInt: Equatable, Comparable {
    private(set) var limbs: [UInt32]

    init(limbs: [UInt32]) {
        var trimmed = limbs
        while trimmed.count > 1 && trimmed[trimmed.count - 1] == 0 { trimmed.removeLast() }
        if trimmed.isEmpty { trimmed = [0] }
        self.limbs = trimmed
    }

    init(_ value: UInt64) {
        self.init(limbs: [UInt32(truncatingIfNeeded: value),
                          UInt32(truncatingIfNeeded: value >> 32)])
    }

    init?(hex: String) {
        let cleaned = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty, cleaned.count <= 2048 else { return nil }
        var digits: [UInt8] = []
        digits.reserveCapacity(cleaned.count)
        for scalar in cleaned.unicodeScalars {
            guard let digit = BigUInt.hexDigit(scalar) else { return nil }
            digits.append(digit)
        }
        var limbs: [UInt32] = []
        limbs.reserveCapacity((digits.count + 7) / 8)
        var index = digits.count
        while index > 0 {
            var word: UInt32 = 0
            var shift: UInt32 = 0
            var taken = 0
            while index > 0 && taken < 8 {
                index -= 1
                word |= UInt32(digits[index]) << shift
                shift += 4
                taken += 1
            }
            limbs.append(word)
        }
        self.init(limbs: limbs)
    }

    private static func hexDigit(_ scalar: Unicode.Scalar) -> UInt8? {
        switch scalar {
        case "0" ... "9": return UInt8(scalar.value - 0x30)
        case "a" ... "f": return UInt8(scalar.value - 0x61 + 10)
        case "A" ... "F": return UInt8(scalar.value - 0x41 + 10)
        default: return nil
        }
    }

    var isZero: Bool { limbs.count == 1 && limbs[0] == 0 }

    var hexString: String {
        let top = limbs.count - 1
        var result = String(limbs[top], radix: 16)
        var index = top - 1
        while index >= 0 {
            let text = String(limbs[index], radix: 16)
            result += String(repeating: "0", count: 8 - text.count) + text
            index -= 1
        }
        return result
    }

    var bitCount: Int {
        var bits = 0
        var value = limbs[limbs.count - 1]
        while value > 0 {
            bits += 1
            value >>= 1
        }
        return (limbs.count - 1) * 32 + bits
    }

    func bit(at index: Int) -> Bool {
        guard index >= 0 else { return false }
        let word = index / 32
        guard word < limbs.count else { return false }
        return (limbs[word] >> UInt32(index % 32)) & 1 == 1
    }

    static func < (lhs: BigUInt, rhs: BigUInt) -> Bool {
        if lhs.limbs.count != rhs.limbs.count { return lhs.limbs.count < rhs.limbs.count }
        var index = lhs.limbs.count - 1
        while index >= 0 {
            if lhs.limbs[index] != rhs.limbs[index] {
                return lhs.limbs[index] < rhs.limbs[index]
            }
            index -= 1
        }
        return false
    }

    /// `self - other`, which the callers only use when `self >= other`.
    func subtracting(_ other: BigUInt) -> BigUInt {
        var result = [UInt32](repeating: 0, count: limbs.count)
        var borrow: Int64 = 0
        for index in 0 ..< limbs.count {
            let rhs = index < other.limbs.count ? Int64(other.limbs[index]) : 0
            var value = Int64(limbs[index]) - rhs - borrow
            if value < 0 {
                value += 0x1_0000_0000
                borrow = 1
            } else {
                borrow = 0
            }
            result[index] = UInt32(truncatingIfNeeded: value)
        }
        return BigUInt(limbs: result)
    }

    func multiplied(by other: BigUInt) -> BigUInt {
        var result = [UInt32](repeating: 0, count: limbs.count + other.limbs.count)
        for i in 0 ..< limbs.count {
            var carry: UInt64 = 0
            let left = UInt64(limbs[i])
            for j in 0 ..< other.limbs.count {
                let value = UInt64(result[i + j]) + left * UInt64(other.limbs[j]) + carry
                result[i + j] = UInt32(truncatingIfNeeded: value)
                carry = value >> 32
            }
            var position = i + other.limbs.count
            while carry != 0 && position < result.count {
                let value = UInt64(result[position]) + carry
                result[position] = UInt32(truncatingIfNeeded: value)
                carry = value >> 32
                position += 1
            }
        }
        return BigUInt(limbs: result)
    }

    var halved: BigUInt {
        var result = [UInt32](repeating: 0, count: limbs.count)
        var carry: UInt32 = 0
        var index = limbs.count - 1
        while index >= 0 {
            result[index] = (limbs[index] >> 1) | (carry << 31)
            carry = limbs[index] & 1
            index -= 1
        }
        return BigUInt(limbs: result)
    }

    /// Bitwise long-division remainder. Accepts a value larger than the modulus,
    /// which the school's oversized message blocks require.
    func remainder(dividingBy modulus: BigUInt) -> BigUInt {
        if modulus.isZero || self < modulus { return modulus.isZero ? BigUInt(0) : self }
        let width = modulus.limbs.count
        var buffer = [UInt32](repeating: 0, count: width + 1)
        var index = bitCount - 1
        while index >= 0 {
            var carry: UInt64 = 0
            for position in 0 ... width {
                let value = (UInt64(buffer[position]) << 1) | carry
                buffer[position] = UInt32(truncatingIfNeeded: value)
                carry = value >> 32
            }
            if bit(at: index) { buffer[0] |= 1 }
            if buffer[width] != 0 || BigUInt.compareLimbs(buffer, modulus, width) >= 0 {
                BigUInt.subtractLimbs(&buffer, modulus, width + 1)
            }
            index -= 1
        }
        return BigUInt(limbs: Array(buffer[0 ..< width]))
    }

    func power(_ exponent: BigUInt, modulus: BigUInt) -> BigUInt {
        guard !modulus.isZero else { return BigUInt(0) }
        var result = BigUInt(1).remainder(dividingBy: modulus)
        let base = remainder(dividingBy: modulus)
        var index = exponent.bitCount - 1
        while index >= 0 {
            result = result.multiplied(by: result).remainder(dividingBy: modulus)
            if exponent.bit(at: index) {
                result = result.multiplied(by: base).remainder(dividingBy: modulus)
            }
            index -= 1
        }
        return result
    }

    private static func compareLimbs(_ lhs: [UInt32], _ rhs: BigUInt, _ width: Int) -> Int {
        var index = width
        while index >= 0 {
            let left = index < lhs.count ? lhs[index] : 0
            let right = index < rhs.limbs.count ? rhs.limbs[index] : 0
            if left != right { return left < right ? -1 : 1 }
            index -= 1
        }
        return 0
    }

    private static func subtractLimbs(_ target: inout [UInt32], _ rhs: BigUInt, _ width: Int) {
        var borrow: Int64 = 0
        for index in 0 ..< width {
            let right = index < rhs.limbs.count ? Int64(rhs.limbs[index]) : 0
            var value = Int64(target[index]) - right - borrow
            if value < 0 {
                value += 0x1_0000_0000
                borrow = 1
            } else {
                borrow = 0
            }
            target[index] = UInt32(truncatingIfNeeded: value)
        }
    }
}

/// Reproduces `security.js` legacy multiplication: 16-bit limbs plus carries
/// truncated to 32 bits (`>>> 16`). Identical to schoolbook multiplication while
/// every UTF-16 unit stays below 0x100, and deliberately lossy above that.
enum LegacyMultiply {
    static func product(_ x: [UInt32], _ y: [UInt32]) -> BigUInt {
        guard !x.isEmpty, !y.isEmpty else { return BigUInt(0) }
        var left = x
        var right = y
        while left.count > 1 && left[left.count - 1] == 0 { left.removeLast() }
        while right.count > 1 && right[right.count - 1] == 0 { right.removeLast() }
        var limbs = [UInt32](repeating: 0, count: left.count + right.count)
        for i in 0 ..< right.count {
            var carry: UInt64 = 0
            let multiplier = UInt64(right[i])
            for j in 0 ..< left.count {
                let value = UInt64(limbs[i + j]) + UInt64(left[j]) * multiplier + carry
                limbs[i + j] = UInt32(truncatingIfNeeded: value & 0xFFFF)
                carry = (value & 0xFFFF_FFFF) >> 16
            }
            limbs[i + left.count] = UInt32(truncatingIfNeeded: carry)
        }
        var packed = [UInt32](repeating: 0, count: (limbs.count + 1) / 2)
        var index = 0
        while index < limbs.count {
            var word = limbs[index]
            if index + 1 < limbs.count { word |= limbs[index + 1] << 16 }
            packed[index / 2] = word
            index += 2
        }
        return BigUInt(limbs: packed)
    }
}
