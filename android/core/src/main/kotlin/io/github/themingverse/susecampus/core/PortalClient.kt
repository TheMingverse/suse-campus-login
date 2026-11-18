package io.github.themingverse.susecampus.core

import java.net.URI
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import org.jsoup.parser.Parser

class PreparedLogin internal constructor(
    internal val owner: PortalClient, internal val url: String,
    internal val info: kotlinx.serialization.json.JsonObject, val services: List<ServiceOption>,
) {
    internal var used = false
    override fun toString() = "PreparedLogin([redacted])"
}

class PortalClient(private val transport: HttpTransport, private val guard: () -> Unit) {
    private var preparation: PreparedLogin? = null

    private suspend fun post(url: String, body: ByteArray): kotlinx.serialization.json.JsonObject {
        currentCoroutineContext().ensureActive(); guard()
        val reply = transport.execute(HttpRequest(url, "POST", body))
        currentCoroutineContext().ensureActive(); guard()
        if (reply.code in 300..399 || reply.body.size > 200000) throw PortalException(Failure.MANUAL)
        if (reply.code !in 200..299) throw PortalException(Failure.TEMPORARY)
        return Protocol.json(reply.body)
    }

    suspend fun prepare(url: String): PreparedLogin {
        preparation = null
        val query = Protocol.connectionQuery(url)
        val base = URI(url).resolve("InterFace.do").toASCIIString()
        val info = post("$base?method=pageInfo", Protocol.form(mapOf("queryString" to query)))
        val services = post("$base?method=getServices&queryString=${Protocol.component(query)}", byteArrayOf())
        return PreparedLogin(this, url, info, Protocol.parseServices(services)).also { preparation = it }
    }

    suspend fun authenticate(url: String, config: Configuration, prepared: PreparedLogin) {
        val query = Protocol.connectionQuery(url)
        guard()
        if (prepared !== preparation || prepared.owner !== this || prepared.url != url || prepared.used)
            throw PortalException(Failure.MANUAL)
        prepared.used = true; preparation = null
        Protocol.requireService(prepared.services, config.service)
        val fields = Protocol.loginFields(config, query, prepared.info)
        val base = URI(url).resolve("InterFace.do").toASCIIString()
        Protocol.classifyLogin(post("$base?method=login", Protocol.form(fields, double = true)))
    }
}

object RedirectParser {
    fun portal(reply: HttpReply): String? {
        val candidates = mutableListOf(reply.header("Location"), reply.header("Refresh"))
        val text = reply.body.toString(Charsets.UTF_8)
        listOf(
            """(?:window\.|top\.|self\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']""",
            """location\.replace\(\s*["']([^"']+)["']""",
            """<meta\b[^>]*http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*["'][^"']*?url\s*=\s*([^"'>]+)""",
        ).forEach { pattern -> Regex(pattern, RegexOption.IGNORE_CASE).findAll(text).forEach { candidates.add(it.groupValues[1]) } }
        for (raw in candidates) {
            var candidate = raw.trim(' ', '\t', '\r', '\n', '"', '\'')
            if (Regex("^0\\s*;", RegexOption.IGNORE_CASE).containsMatchIn(candidate))
                candidate = candidate.split(Regex("url\\s*=", RegexOption.IGNORE_CASE), limit = 2).last()
            val url = runCatching { URI(reply.url).resolve(Parser.unescapeEntities(candidate, false)).toASCIIString() }.getOrNull() ?: continue
            if (Protocol.trustedPortal(url)) return url
        }
        return null
    }
}

class NetworkProbe(private val transport: HttpTransport, private val guard: () -> Unit) {
    suspend fun check(): ProbeResult {
        var detected: ProbeResult? = null
        for ((url, expected) in Protocol.probes) {
            currentCoroutineContext().ensureActive(); guard()
            try {
                val reply = transport.execute(HttpRequest(url, probe = true))
                currentCoroutineContext().ensureActive(); guard()
                if (reply.code == 200 && reply.body.toString(Charsets.UTF_8).trim(' ', '\t', '\r', '\n', '\u000B', '\u000C') == expected)
                    return ProbeResult(ProbeState.ONLINE)
                if (reply.code in setOf(200, 301, 302, 303, 307, 308)) {
                    val portal = RedirectParser.portal(reply) ?: continue
                    try {
                        Protocol.connectionQuery(portal)
                        detected = ProbeResult(ProbeState.PORTAL, portal)
                    } catch (_: PortalException) {
                        if (detected == null) detected = ProbeResult(ProbeState.UNSUPPORTED)
                    }
                }
            } catch (error: PortalException) {
                guard()
                if (error.kind != Failure.TEMPORARY) throw error
            }
        }
        return detected ?: ProbeResult(ProbeState.UNKNOWN)
    }
}
