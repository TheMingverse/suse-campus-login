package io.github.themingverse.susecampus.core

import java.io.File
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ProtocolTest {
    private val query = "wlanuserip=fresh-user&wlanacname=fresh-ac&mac=ab%3Acd&ssid=fresh-ssid"
    private val url = "http://10.23.2.4/eportal/index.jsp?$query"
    private fun json(text: String) = Json.parseToJsonElement(text).jsonObject
    private fun fails(kind: Failure, block: () -> Unit) {
        try { block(); fail("Expected safe rejection") } catch (error: PortalException) { assertEquals(kind, error.kind) }
    }

    @Test fun schoolJavascriptRsaVectors() {
        val vectors = javaClass.getResourceAsStream("/rsa_vectors.json")!!.use { Json.parseToJsonElement(it.reader().readText()).jsonObject }
        for (item in vectors.getValue("vectors").jsonArray) {
            val value = item.jsonObject
            assertEquals(value.getValue("expected").jsonPrimitive.content, Protocol.rsaPassword(value.getValue("password").jsonPrimitive.content,
                vectors.getValue("mac").jsonPrimitive.content, vectors.getValue("exponent").jsonPrimitive.content, vectors.getValue("modulus").jsonPrimitive.content))
        }
    }

    @Test fun pythonWireCatalogAndClassificationParity() {
        val fixture = Json.parseToJsonElement(File(System.getProperty("fixtureDir"), "python_protocol.json").readText()).jsonObject
        fixture.getValue("components").jsonArray.forEach { element ->
            val value = element.jsonObject
            assertEquals(value.getValue("expected").jsonPrimitive.content, Protocol.component(value.getValue("input").jsonPrimitive.content))
        }
        fixture.getValue("forms").jsonArray.forEach { element ->
            val value = element.jsonObject
            val fields = value.getValue("fields").jsonObject.mapValues { it.value.jsonPrimitive.content }
            assertEquals(value.getValue("expected").jsonPrimitive.content,
                Protocol.form(fields, value.getValue("double").jsonPrimitive.boolean).toString(Charsets.US_ASCII))
        }
        fixture.getValue("catalogs").jsonArray.forEach { element ->
            val value = element.jsonObject
            val actual = Protocol.parseServices(value.getValue("payload").jsonObject)
            val expected = value.getValue("expected").jsonArray
            assertEquals(expected.size, actual.size)
            actual.zip(expected).forEach { (option, expectedOption) ->
                assertEquals(expectedOption.jsonObject.getValue("name").jsonPrimitive.content, option.name)
                assertEquals(expectedOption.jsonObject.getValue("available").jsonPrimitive.boolean, option.available)
            }
        }
        fixture.getValue("outcomes").jsonArray.forEach { element ->
            val value = element.jsonObject
            val actual = try { Protocol.classifyLogin(value.getValue("data").jsonObject); "success" }
                catch (error: PortalException) { error.kind.name.lowercase() }
            assertEquals(value.getValue("expected").jsonPrimitive.content, actual)
        }
        assertEquals(query, Protocol.connectionQuery(fixture.getValue("portal").jsonPrimitive.content))
    }

    @Test fun untrustedAndMalformedPortalsAreRejected() {
        for (bad in listOf(url.replace("10.23.2.4", "10.23.2.4.evil"), url.replace("10.23.2.4", "10.23.2.4@evil"),
            url.replace("http:", "https:"), url.replace("10.23.2.4", "10.23.2.4:9999"),
            url.replace("index.jsp", "other.jsp"), "$url#fragment", "http://10.23.2.4/eportal/index.jsp"))
            fails(Failure.MANUAL) { Protocol.connectionQuery(bad) }
        assertEquals(query, Protocol.connectionQuery(url))
        fails(Failure.MANUAL) { Protocol.connectionQuery("$url&padding=${"x".repeat(16000)}") }
    }

    @Test fun onlyRedirectsAreEvidence() {
        fun reply(body: String = "", headers: Map<String, String> = emptyMap()) = HttpReply(200, Protocol.probes[0].first, headers, body.toByteArray())
        assertEquals(url, RedirectParser.portal(reply(headers = mapOf("Location" to url))))
        assertEquals(url, RedirectParser.portal(reply("<script>location.href='${url.replace("&", "&amp;")}'</script>")))
        assertEquals(url, RedirectParser.portal(reply("<meta http-equiv='refresh' content='0;url=$url'>")))
        assertEquals(url, RedirectParser.portal(reply(headers = mapOf("Refresh" to "0; url=$url"))))
        assertNull(RedirectParser.portal(reply("<a href='$url'>ordinary link</a>")))
        assertNull(RedirectParser.portal(reply(headers = mapOf("Location" to url.replace("10.23.2.4", "evil.example")))))
    }

    @Test fun malformedOrAmbiguousServicesFailClosed() {
        for (payload in listOf("{}", "{\"serviceJson\":[]}", "{\"serviceJson\":\"bad\"}", "{\"serviceJson\":[null]}",
            "{\"serviceJson\":[{\"serviceName\":123}]}")) fails(Failure.SERVICE) { Protocol.parseServices(json(payload)) }
        val list = Protocol.parseServices(json("""{"serviceJson":[{"serviceName":"A","id":1},{"serviceName":"A","id":2},{"serviceName":"A","id":2}]}"""))
        assertFalse(list.single().available)
        fails(Failure.SERVICE) { Protocol.requireService(list, "A") }
        fails(Failure.SERVICE) { Protocol.requireService(listOf(ServiceOption(" 新服务", true)), "新服务") }
        assertEquals("新服务", Protocol.parseServices(json("""{"serviceJson":"[{\"serviceName\":\"新服务\"}]"}""")).single().name)
        listOf("", " ", "a\u0000", "a\n", "a\u200b", "a".repeat(201)).forEach { assertFalse(Protocol.validServiceName(it)) }
    }

    @Test fun unknownAuthenticationFlagsStopBeforeCredentials() {
        for (info in listOf("""{"validCodeUrl":"/captcha"}""", """{"prefixValue":"x"}""",
            """{"isCheckSmsAuth":"true"}""", """{"isToCasPage":true}""", """{"passwordEncrypt":"unknown"}""",
            """{"passwordEncrypt":true,"publicKeyExponent":"10001","publicKeyModulus":"bad"}"""))
            fails(Failure.MANUAL) { Protocol.loginFields(Configuration("student", "synthetic", "A"), query, json(info)) }
        fails(Failure.MANUAL) { Protocol.component("\uD800") }
    }

    @Test fun preparationIsSingleUseAndBoundToOwnerAndUrl() = runTest {
        val transport = FakeTransport(listOf("{}", """{"serviceJson":[{"serviceName":"A"}]}""", """{"result":"success"}"""))
        val first = PortalClient(transport) {}
        val second = PortalClient(transport) {}
        val prepared = first.prepare(url)
        try { second.authenticate(url, Configuration("student", "synthetic", "A"), prepared); fail() } catch (_: PortalException) { }
        first.authenticate(url, Configuration("student", "synthetic", "A"), prepared)
        try { first.authenticate(url, Configuration("student", "synthetic", "A"), prepared); fail() } catch (_: PortalException) { }
        assertEquals(3, transport.calls.size)
        assertFalse(transport.calls.take(2).any { it.body.toString(Charsets.US_ASCII).contains("synthetic") })
    }

    @Test fun redactedObjectsAndMessages() {
        assertFalse(Configuration("private-user", "secret", "A").toString().contains("secret"))
        assertFalse(HttpRequest("http://secret.example", body = "password".toByteArray()).toString().contains("password"))
        val failure = try { Protocol.classifyLogin(json("""{"result":"fail","message":"private-user secret 密码错误"}""")); null }
            catch (error: PortalException) { error }
        assertEquals(Failure.CREDENTIALS, failure!!.kind)
        assertFalse(failure.toString().contains("secret"))
    }
}

internal class FakeTransport(replies: List<String>) : HttpTransport {
    private val queue = ArrayDeque(replies)
    val calls = mutableListOf<HttpRequest>()
    var closed = false
    override suspend fun execute(request: HttpRequest): HttpReply {
        calls.add(request)
        return HttpReply(200, request.url, emptyMap(), queue.removeFirst().toByteArray())
    }
    override fun close() { closed = true }
}
