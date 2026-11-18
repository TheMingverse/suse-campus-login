package io.github.themingverse.susecampus.core

import java.net.*
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import javax.net.SocketFactory
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.Test

class BoundHttpTransportTest {
    private val login = "http://10.23.2.4/eportal/InterFace.do?method=login"
    private val info = "http://10.23.2.4/eportal/InterFace.do?method=pageInfo"

    /** Test-only sockets physically connect to loopback, while production URL/Host/cookie rules remain unchanged. */
    private class LoopbackFactory(private val server: MockWebServer) : SocketFactory() {
        val creates = AtomicInteger()
        override fun createSocket(): Socket {
            creates.incrementAndGet()
            return object : Socket() {
                override fun connect(endpoint: SocketAddress, timeout: Int) {
                    super.connect(InetSocketAddress(InetAddress.getLoopbackAddress(), server.port), timeout)
                }
            }
        }
        override fun createSocket(host: String, port: Int): Socket = error("Unbound overload forbidden")
        override fun createSocket(host: String, port: Int, local: InetAddress, localPort: Int): Socket = error("Unbound overload forbidden")
        override fun createSocket(host: InetAddress, port: Int): Socket = error("Unbound overload forbidden")
        override fun createSocket(host: InetAddress, port: Int, local: InetAddress, localPort: Int): Socket = error("Unbound overload forbidden")
    }

    @Test fun onlyExplicitHostsPathsMethodsAndPurposesAreAllowed() {
        assertTrue(RequestPolicy.allows(HttpRequest(login, "POST")))
        assertTrue(RequestPolicy.allows(HttpRequest(Protocol.probes[0].first, probe = true)))
        for (request in listOf(HttpRequest(login, "GET"), HttpRequest(login, "POST", probe = true),
            HttpRequest(Protocol.probes[0].first, "POST", "credentials".toByteArray(), true),
            HttpRequest(login.replace("10.23.2.4", "evil.example"), "POST"),
            HttpRequest(login.replace("10.23.2.4", "10.23.2.4:9999"), "POST"),
            HttpRequest("$login&extra=1", "POST"), HttpRequest("http://www.msftconnecttest.com/other", probe = true)))
            assertFalse(RequestPolicy.allows(request))
    }

    @Test fun wifiSocketFactoryAndDnsAreUsedEvenWithAnUnusableDefaultPath() = runBlocking {
        MockWebServer().use { server ->
            server.start()
            val sockets = LoopbackFactory(server)
            val resolutions = mutableListOf<String>()
            val base = OkHttpClient.Builder().socketFactory(sockets).dns(object : Dns {
                override fun lookup(hostname: String): List<InetAddress> {
                    resolutions.add(hostname); return listOf(InetAddress.getLoopbackAddress())
                }
            }).build()
            BoundHttpTransport(base).use { transport ->
                server.enqueue(MockResponse().setBody("Microsoft Connect Test"))
                assertEquals(200, transport.execute(HttpRequest(Protocol.probes[0].first, probe = true)).code)
                assertEquals(listOf("www.msftconnecttest.com"), resolutions)
                assertEquals(1, sockets.creates.get())
                assertEquals("www.msftconnecttest.com", server.takeRequest().getHeader("Host"))
            }
        }
    }

    @Test fun cookiesStayWithinPortalAndAreDestroyedBetweenTasks() = runBlocking {
        MockWebServer().use { server ->
            server.start()
            fun transport() = BoundHttpTransport(OkHttpClient.Builder().socketFactory(LoopbackFactory(server)).build())
            transport().use { http ->
                server.enqueue(MockResponse().setBody("{}").addHeader("Set-Cookie", "synthetic-session=value; Path=/eportal"))
                http.execute(HttpRequest(info, "POST")); assertNull(server.takeRequest().getHeader("Cookie"))
                server.enqueue(MockResponse().setBody("{}"))
                http.execute(HttpRequest(login, "POST")); assertEquals("synthetic-session=value", server.takeRequest().getHeader("Cookie"))
                server.enqueue(MockResponse().setBody("success").addHeader("Set-Cookie", "probe-cookie=discard; Path=/"))
                http.execute(HttpRequest(Protocol.probes[1].first, probe = true)); assertNull(server.takeRequest().getHeader("Cookie"))
                server.enqueue(MockResponse().setBody("Microsoft Connect Test"))
                http.execute(HttpRequest(Protocol.probes[0].first, probe = true)); assertNull(server.takeRequest().getHeader("Cookie"))
            }
            transport().use { http ->
                server.enqueue(MockResponse().setBody("{}"))
                http.execute(HttpRequest(info, "POST")); assertNull(server.takeRequest().getHeader("Cookie"))
            }
        }
    }

    @Test fun credentialRedirectIsNeverFollowed() = runBlocking {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", "http://evil.example/collect"))
            BoundHttpTransport(OkHttpClient.Builder().socketFactory(LoopbackFactory(server)).build()).use { http ->
                assertEquals(302, http.execute(HttpRequest(login, "POST", "test-only".toByteArray())).code)
                assertEquals(1, server.requestCount)
            }
        }
    }

    @Test fun failedWifiSocketNeverFallsBackToDefaultNetwork() = runBlocking {
        val unavailable = object : SocketFactory() {
            override fun createSocket(): Socket = throw java.io.IOException("synthetic unavailable Wi-Fi")
            override fun createSocket(host: String, port: Int): Socket = createSocket()
            override fun createSocket(host: String, port: Int, local: InetAddress, localPort: Int): Socket = createSocket()
            override fun createSocket(host: InetAddress, port: Int): Socket = createSocket()
            override fun createSocket(host: InetAddress, port: Int, local: InetAddress, localPort: Int): Socket = createSocket()
        }
        BoundHttpTransport(OkHttpClient.Builder().socketFactory(unavailable).build()).use { http ->
            try { http.execute(HttpRequest(info, "POST")); fail("Must fail closed") }
            catch (error: PortalException) { assertEquals(Failure.TEMPORARY, error.kind) }
        }
    }

    @Test fun interruptedLoginPostIsNotRetried() = runBlocking {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
            BoundHttpTransport(OkHttpClient.Builder().socketFactory(LoopbackFactory(server)).build()).use { http ->
                try { http.execute(HttpRequest(login, "POST", "test-only".toByteArray())); fail() }
                catch (error: PortalException) { assertEquals(Failure.TEMPORARY, error.kind) }
                assertEquals(1, server.requestCount)
            }
        }
    }

    @Test fun oversizedPortalResponseIsRejected() = runBlocking {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setBody("x".repeat(200001)))
            BoundHttpTransport(OkHttpClient.Builder().socketFactory(LoopbackFactory(server)).build()).use { http ->
                try { http.execute(HttpRequest(info, "POST")); fail() }
                catch (error: PortalException) { assertEquals(Failure.MANUAL, error.kind) }
            }
        }
    }

    @Test fun cancellationInterruptsPendingHttpCall() = runBlocking {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
            BoundHttpTransport(OkHttpClient.Builder().socketFactory(LoopbackFactory(server)).build()).use { http ->
                val task = launch(Dispatchers.Default) { http.execute(HttpRequest(info, "POST")) }
                assertNotNull(server.takeRequest(3, TimeUnit.SECONDS))
                withTimeout(2000) { task.cancelAndJoin() }
                assertTrue(task.isCancelled)
            }
        }
    }
}
