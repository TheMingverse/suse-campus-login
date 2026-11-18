package io.github.themingverse.susecampus.core

import java.math.BigInteger
import java.net.URI
import java.nio.charset.CodingErrorAction
import kotlinx.serialization.json.*
import org.jsoup.parser.Parser

object Protocol {
    const val HOST = "10.23.2.4"
    val ssids = setOf("SUSE", "SUSE_Hostel")
    val probes = listOf(
        "http://www.msftconnecttest.com/connecttest.txt" to "Microsoft Connect Test",
        "http://detectportal.firefox.com/success.txt" to "success",
    )

    fun trustedPortal(url: String): Boolean = runCatching {
        val uri = URI(url)
        uri.scheme == "http" && uri.host == HOST && uri.port in setOf(-1, 80, 8080) &&
            uri.rawUserInfo == null && uri.rawFragment == null && uri.rawPath.equals("/eportal/index.jsp", true)
    }.getOrDefault(false)

    fun connectionQuery(url: String): String {
        if (!trustedPortal(url)) throw PortalException(Failure.MANUAL)
        val query = URI(url).rawQuery.orEmpty()
        if (query.length > 16000 || listOf("wlanuserip", "wlanacname", "mac").any {
                !Regex("(?:^|&)$it=[^&]+").containsMatchIn(query)
            }) throw PortalException(Failure.MANUAL)
        return query
    }

    /** encodeURIComponent, not HTML form encoding: spaces are %20 and !'()* stay literal. */
    fun component(value: String): String {
        val bytes = try {
            Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                .encode(java.nio.CharBuffer.wrap(value)).let { b -> ByteArray(b.remaining()).also(b::get) }
        } catch (_: Exception) { throw PortalException(Failure.MANUAL) }
        val safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()"
        return buildString {
            for (byte in bytes) {
                val n = byte.toInt() and 255
                if (n.toChar() in safe) append(n.toChar()) else {
                    append('%'); append("0123456789ABCDEF"[n ushr 4]); append("0123456789ABCDEF"[n and 15])
                }
            }
        }
    }

    fun form(fields: Map<String, String>, double: Boolean = false): ByteArray = fields.entries.joinToString("&") {
        "${it.key}=${if (double) component(component(it.value)) else component(it.value)}"
    }.toByteArray(Charsets.US_ASCII)

    /** School security.js format, deliberately preserving JS 32-bit carries and UTF-16 code units. */
    fun rsaPassword(password: String, mac: String, exponent: String, modulus: String): String {
        val (e, n) = try {
            if (exponent.length > 1024 || modulus.length > 1024 ||
                !exponent.matches(Regex("[0-9a-fA-F]+")) || !modulus.matches(Regex("[0-9a-fA-F]+"))) error("key")
            BigInteger(exponent, 16) to BigInteger(modulus, 16)
        } catch (_: Exception) { throw PortalException(Failure.MANUAL) }
        if (n.bitLength() !in 512..4096 || e <= BigInteger.ONE || e >= n) throw PortalException(Failure.MANUAL)
        val chunk = 2 * ((n.bitLength() - 1) / 16)
        // Kotlin String.reversed() can preserve surrogate pairs: reverse individual Char units explicitly.
        val original = password + ">" + mac
        val units = original.indices.reversed().map { original[it].code }.toMutableList()
        while (units.size % chunk != 0) units.add(0)
        fun multiply(x: List<Long>, y: List<Long>): BigInteger {
            val product = LongArray(x.size + y.size)
            y.forEachIndexed { i, b ->
                var carry = 0L
                x.forEachIndexed { j, a ->
                    val value = product[i + j] + a * b + carry
                    product[i + j] = value and 0xffff
                    carry = (value and 0xffffffffL) ushr 16
                }
                product[i + x.size] = carry
            }
            return product.indices.fold(BigInteger.ZERO) { result, i -> result + BigInteger.valueOf(product[i]).shiftLeft(16 * i) }
        }
        return units.chunked(chunk).joinToString(" ") { block ->
            val digits = block.chunked(2).map { it[0].toLong() + (it[1].toLong() shl 8) }.dropLastWhile { it == 0L }.ifEmpty { listOf(0L) }
            val initial = if (e.testBit(0)) multiply(listOf(1L), digits).mod(n) else BigInteger.ONE
            val squared = multiply(digits, digits).mod(n)
            val value = initial.multiply(squared.modPow(e.shiftRight(1), n)).mod(n).toString(16)
            value.padStart((value.length + 3) / 4 * 4, '0')
        }
    }

    fun json(body: ByteArray): JsonObject = try {
        val decoded = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .decode(java.nio.ByteBuffer.wrap(body)).toString().removePrefix("\uFEFF")
        Json.parseToJsonElement(decoded) as? JsonObject ?: throw PortalException(Failure.MANUAL)
    } catch (_: Exception) { throw PortalException(Failure.MANUAL) }

    fun validServiceName(name: String) = name.codePointCount(0, name.length) in 1..200 && name.isNotBlank() &&
        name.codePoints().noneMatch { Character.getType(it) in setOf(
            Character.CONTROL.toInt(), Character.FORMAT.toInt(), Character.SURROGATE.toInt(),
            Character.PRIVATE_USE.toInt(), Character.UNASSIGNED.toInt()) }

    fun parseServices(data: JsonObject): List<ServiceOption> = try {
        val raw = data["serviceJson"]
        val array = (if (raw is JsonPrimitive && raw.isString) Json.parseToJsonElement(raw.content) else raw) as? JsonArray
            ?: throw PortalException(Failure.SERVICE)
        if (array.isEmpty()) throw PortalException(Failure.SERVICE)
        fun canonical(value: JsonElement): JsonElement = when (value) {
            is JsonObject -> JsonObject(value.toSortedMap().mapValues { canonical(it.value) })
            is JsonArray -> JsonArray(value.map(::canonical))
            else -> value
        }
        val groups = linkedMapOf<String, Pair<JsonElement?, ServiceOption>>()
        for (element in array) {
            val item = element as? JsonObject ?: throw PortalException(Failure.SERVICE)
            val primitive = item["serviceName"] as? JsonPrimitive ?: throw PortalException(Failure.SERVICE)
            val name = primitive.content
            if (!primitive.isString || !validServiceName(name)) throw PortalException(Failure.SERVICE)
            var available = listOf("aceNotShow", "domainName").all { item[it] == null || item[it].toString().trim('"').lowercase() == "false" }
            var reason = if (available) "" else "需要官方页面处理"
            var signature: JsonElement? = canonical(item)
            if (groups.containsKey(name) && groups[name]!!.first != signature) {
                available = false; reason = "同名服务配置存在冲突"; signature = null
            }
            groups[name] = signature to ServiceOption(name, available, reason)
        }
        groups.values.map { it.second }
    } catch (_: Exception) { throw PortalException(Failure.SERVICE) }

    fun requireService(options: List<ServiceOption>, name: String) {
        if (options.count { it.name == name && it.available } != 1) throw PortalException(Failure.SERVICE)
    }

    private fun flag(info: JsonObject, name: String): Boolean {
        val value = info[name] ?: return false
        return when ((value as? JsonPrimitive)?.content?.lowercase()) {
            "true" -> true
            "false" -> false
            else -> throw PortalException(Failure.MANUAL)
        }
    }

    fun loginFields(configuration: Configuration, query: String, info: JsonObject): Map<String, String> {
        fun populated(key: String) = info[key]?.let { it !is JsonNull && it.toString().trim('"').isNotEmpty() } ?: false
        if (populated("validCodeUrl") || populated("prefixValue") || flag(info, "isCheckSmsAuth") || flag(info, "isToCasPage"))
            throw PortalException(Failure.MANUAL)
        val encrypted = flag(info, "passwordEncrypt")
        val mac = Regex("(?:^|&)mac=([^&]+)").find(query)?.groupValues?.get(1) ?: throw PortalException(Failure.MANUAL)
        val password = if (encrypted) rsaPassword(configuration.password, mac,
            info["publicKeyExponent"]?.jsonPrimitive?.content.orEmpty(), info["publicKeyModulus"]?.jsonPrimitive?.content.orEmpty()) else configuration.password
        return linkedMapOf("userId" to configuration.username.trim(), "password" to password,
            "service" to configuration.service, "queryString" to query, "operatorPwd" to "", "operatorUserId" to "",
            "validcode" to "", "passwordEncrypt" to encrypted.toString())
    }

    fun classifyLogin(data: JsonObject) {
        val message = Parser.unescapeEntities(Regex("<[^>]*>").replace((data["message"] as? JsonPrimitive)?.content.orEmpty(), ""), false)
        if ((data["result"] as? JsonPrimitive)?.content == "success") {
            if ("PWD_COMPLEX_OFFLINE_WEB" in message) throw PortalException(Failure.MANUAL)
            return
        }
        fun contains(pattern: String) = Regex(pattern, RegexOption.IGNORE_CASE).containsMatchIn(message)
        val kind = when {
            contains("验证码|短信|captcha|valid.?code|verify.?code") -> Failure.MANUAL
            contains("密码|口令|用户不存在|账号不存在|帐号不存在|认证失败|password|credential|user.*not.*exist") -> Failure.CREDENTIALS
            contains("欠费|停机|冻结|禁用|到期|过期|在线.*(数|上限)|终端.*(数|上限)|已.*在线|already.*online|limit") -> Failure.MANUAL
            contains("超时|繁忙|稍后|timeout|busy|暂时|服务器.*(失败|异常|错误)") -> Failure.TEMPORARY
            else -> Failure.MANUAL
        }
        throw PortalException(kind)
    }
}
