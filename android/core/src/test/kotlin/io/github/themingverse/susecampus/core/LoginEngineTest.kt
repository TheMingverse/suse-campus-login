package io.github.themingverse.susecampus.core

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

internal const val TEST_PORTAL = "http://10.23.2.4/eportal/index.jsp?wlanuserip=fresh&wlanacname=fresh&mac=ab%3Acd"
internal class MemoryStore(var value: Configuration = Configuration("student", "synthetic", "A", revision = 1)) : ConfigurationStore {
    override suspend fun load() = value
    override suspend fun save(configuration: Configuration) { value = Configuration(configuration.username, configuration.password,
        configuration.service, configuration.autoLogin, revision = value.revision + 1) }
    override suspend fun block(revision: Long, value: Block?) {
        if (revision != this.value.revision) throw PortalException(Failure.CHANGED)
        this.value = this.value.withBlock(value)
    }
}
internal class Scenario : HttpTransport {
    val calls = mutableListOf<HttpRequest>()
    val probeResults = ArrayDeque(listOf("portal", "portal", "online"))
    var loginResponse = """{"result":"success"}"""
    var catalog = """{"serviceJson":[{"serviceName":"A"}]}"""
    var info = "{}"
    var gate: CompletableDeferred<Unit>? = null
    var beforeLogin: (() -> Unit)? = null
    var closed = false
    override suspend fun execute(request: HttpRequest): HttpReply {
        calls.add(request)
        gate?.await()
        if (request.probe) return when (probeResults.removeFirstOrNull() ?: "unknown") {
            "online" -> HttpReply(200, request.url, emptyMap(), Protocol.probes.first { it.first == request.url }.second.toByteArray())
            "portal" -> HttpReply(302, request.url, mapOf("Location" to TEST_PORTAL), byteArrayOf())
            "rogue" -> HttpReply(302, request.url, mapOf("Location" to TEST_PORTAL.replace("10.23.2.4", "evil.example")), byteArrayOf())
            "missing" -> HttpReply(302, request.url, mapOf("Location" to "http://10.23.2.4/eportal/index.jsp"), byteArrayOf())
            "timeout" -> throw PortalException(Failure.TEMPORARY)
            else -> HttpReply(200, request.url, emptyMap(), "unknown".toByteArray())
        }
        val body = when {
            "method=pageInfo" in request.url -> info
            "method=getServices" in request.url -> catalog
            else -> { beforeLogin?.invoke(); loginResponse }
        }
        return HttpReply(200, request.url, emptyMap(), body.toByteArray())
    }
    override fun close() { closed = true }
    fun logins() = calls.count { it.url.endsWith("method=login") }
}
internal class TestWifi(val scenario: Scenario = Scenario(), private val failure: Failure? = null) : WifiAccess {
    var closes = 0
    val invalidated = MutableStateFlow(false)
    override suspend fun acquire(): WifiLease {
        failure?.let { throw PortalException(it) }
        return object : WifiLease {
            override val transport = scenario
            override val invalidated = this@TestWifi.invalidated
            override fun guard() { if (invalidated.value) throw PortalException(Failure.CHANGED) }
            override fun close() { closes++; transport.close() }
        }
    }
}

class LoginEngineTest {
    @Test fun observedWifiChangeClearsOldOnlineStateAndCatalog() = runTest {
        val engine = LoginEngine(MemoryStore(), TestWifi())
        assertEquals(Stage.CATALOG, engine.run(refreshOnly = true).stage)
        assertFalse(engine.status.value.services.isEmpty())
        engine.invalidateCatalog()
        assertEquals(Stage.IDLE, engine.status.value.stage)
        assertTrue(engine.status.value.services.isEmpty())
    }
    @Test fun alreadyOnlineDoesNotAuthenticate() = runTest {
        val wifi = TestWifi().apply { scenario.probeResults.clear(); scenario.probeResults.add("online") }
        assertEquals(Stage.ONLINE, LoginEngine(MemoryStore(), wifi).run().stage)
        assertEquals(0, wifi.scenario.logins()); assertEquals(1, wifi.closes)
    }
    @Test fun noWifiDoesNotSendRequests() = runTest {
        val wifi = TestWifi(failure = Failure.NO_WIFI)
        assertEquals(Stage.FAILED, LoginEngine(MemoryStore(), wifi).run().stage)
        assertTrue(wifi.scenario.calls.isEmpty())
    }
    @Test fun unrelatedWifiIsRejected() = runTest {
        val wifi = TestWifi(failure = Failure.OUTSIDE)
        assertEquals(safeMessage(Failure.OUTSIDE), LoginEngine(MemoryStore(), wifi).run().text)
        assertTrue(wifi.scenario.calls.isEmpty())
    }
    @Test fun wifiPathUsedForProbeLoginAndVerification() = runTest {
        // A mobile/default path is deliberately not part of the operation interface.
        val wifi = TestWifi()
        assertEquals(Stage.ONLINE, LoginEngine(MemoryStore(), wifi).run().stage)
        assertEquals(6, wifi.scenario.calls.size)
        assertEquals(1, wifi.scenario.logins()); assertTrue(wifi.scenario.closed)
    }
    @Test fun roguePortalNeverReceivesCredentials() = runTest {
        val wifi = TestWifi().apply { scenario.probeResults.clear(); scenario.probeResults.addAll(listOf("rogue", "rogue")) }
        assertEquals(Stage.FAILED, LoginEngine(MemoryStore(), wifi).run().stage)
        assertEquals(0, wifi.scenario.logins()); assertTrue(wifi.scenario.calls.all { it.probe })
    }
    @Test fun missingParametersStopBeforePreparation() = runTest {
        val wifi = TestWifi().apply { scenario.probeResults.clear(); scenario.probeResults.addAll(listOf("missing", "missing")) }
        assertEquals(safeMessage(Failure.MANUAL), LoginEngine(MemoryStore(), wifi).run().text)
        assertTrue(wifi.scenario.calls.all { it.probe })
    }
    @Test fun serviceMismatchNeverSubmitsCredentials() = runTest {
        val wifi = TestWifi().apply { scenario.catalog = """{"serviceJson":[{"serviceName":"different"}]}""" }
        val status = LoginEngine(MemoryStore(), wifi).run()
        assertEquals(safeMessage(Failure.SERVICE), status.text)
        assertEquals(0, wifi.scenario.logins())
        assertEquals("different", status.services.single().name)
    }
    @Test fun wrongCredentialsPersistBlockAndReadOnlyRefreshDoesNotResetIt() = runTest {
        val store = MemoryStore()
        val first = TestWifi().apply { scenario.loginResponse = """{"result":"fail","message":"student 密码错误"}""" }
        assertEquals(safeMessage(Failure.CREDENTIALS), LoginEngine(store, first).run().text)
        assertEquals(Block.CREDENTIALS, store.value.block)
        val afterRestart = TestWifi()
        assertEquals(Stage.BLOCKED, LoginEngine(store, afterRestart).run(automatic = true).stage)
        assertEquals(0, afterRestart.scenario.logins())
        val readOnly = TestWifi()
        assertEquals(Stage.CATALOG, LoginEngine(store, readOnly).run(refreshOnly = true).stage)
        assertEquals(Block.CREDENTIALS, store.value.block); assertEquals(0, readOnly.scenario.logins())
    }
    @Test fun timeoutDoesNotCauseLogin() = runTest {
        val wifi = TestWifi().apply { scenario.probeResults.clear(); scenario.probeResults.addAll(listOf("timeout", "timeout")) }
        assertEquals(Stage.FAILED, LoginEngine(MemoryStore(), wifi).run().stage)
        assertEquals(0, wifi.scenario.logins()); assertTrue(wifi.scenario.closed)
    }
    @Test fun acceptedLoginWithoutInternetIsNotSuccessAndBlocksAutomaticRetry() = runTest {
        val wifi = TestWifi().apply { scenario.probeResults.clear(); scenario.probeResults.addAll(listOf("portal", "portal", "unknown", "unknown")) }
        val store = MemoryStore()
        assertEquals(Stage.BLOCKED, LoginEngine(store, wifi).run().stage)
        assertEquals(Block.UNVERIFIED, store.value.block)
        val next = TestWifi()
        assertEquals(Stage.BLOCKED, LoginEngine(store, next).run(automatic = true).stage)
        assertEquals(0, next.scenario.logins())
    }
    @Test fun duplicateTriggersDoNotQueue() = runTest {
        val wifi = TestWifi().apply { scenario.gate = CompletableDeferred() }
        val engine = LoginEngine(MemoryStore(), wifi)
        val first = async { engine.run() }
        yield()
        assertEquals(Stage.BUSY, engine.run().stage)
        wifi.scenario.gate!!.complete(Unit)
        assertEquals(Stage.ONLINE, first.await().stage)
        assertEquals(1, wifi.scenario.logins())
    }
    @Test fun networkSwitchCancelsInFlightTaskAndReleasesLease() = runTest {
        val wifi = TestWifi().apply { scenario.gate = CompletableDeferred() }
        val engine = LoginEngine(MemoryStore(), wifi)
        val task = async { engine.run() }
        yield(); wifi.invalidated.value = true
        assertEquals(Stage.CANCELLED, task.await().stage)
        assertEquals(1, wifi.closes); assertEquals(0, wifi.scenario.logins())
    }
    @Test fun explicitCancellationClosesAndCanBeFollowedByAnotherTask() = runTest {
        val wifi = TestWifi().apply { scenario.gate = CompletableDeferred() }
        val engine = LoginEngine(MemoryStore(), wifi)
        val task = launch { engine.run() }
        yield(); engine.cancel(); task.join()
        assertEquals(Stage.CANCELLED, engine.status.value.stage)
        assertEquals(1, wifi.closes)
        wifi.scenario.gate = null
        assertEquals(Stage.ONLINE, engine.run().stage)
    }
    @Test fun disabledAutomaticAndIncompleteDraftDoNotSubmit() = runTest {
        for (config in listOf(Configuration("student", "synthetic", "A", false), Configuration("student", "synthetic"))) {
            val wifi = TestWifi()
            assertEquals(Stage.SETUP, LoginEngine(MemoryStore(config), wifi).run(automatic = true).stage)
            assertTrue(wifi.scenario.calls.isEmpty())
        }
    }
    @Test fun secondProbeOnlineOverridesFirstPortalOrTimeout() = runTest {
        for (first in listOf("portal", "timeout")) {
            val wifi = TestWifi().apply { scenario.probeResults.clear(); scenario.probeResults.addAll(listOf(first, "online")) }
            assertEquals(Stage.ONLINE, LoginEngine(MemoryStore(), wifi).run().stage)
            assertEquals(0, wifi.scenario.logins())
        }
    }
    @Test fun unknownAuthModeStopsBeforeLogin() = runTest {
        val wifi = TestWifi().apply { scenario.info = """{"passwordEncrypt":"unexpected"}""" }
        assertEquals(safeMessage(Failure.MANUAL), LoginEngine(MemoryStore(), wifi).run().text)
        assertEquals(0, wifi.scenario.logins())
    }
    @Test fun configurationChangeBeforeSubmissionDoesNotOverwriteNewSettings() = runTest {
        val store = MemoryStore()
        val scenario = Scenario()
        val transport = object : HttpTransport {
            override suspend fun execute(request: HttpRequest): HttpReply {
                val reply = scenario.execute(request)
                if ("method=getServices" in request.url) store.save(Configuration("new-student", "new-synthetic", "A"))
                return reply
            }
            override fun close() = scenario.close()
        }
        val wifi = object : WifiAccess {
            override suspend fun acquire() = object : WifiLease {
                override val transport = transport
                override val invalidated = MutableStateFlow(false)
                override fun guard() {}
                override fun close() = transport.close()
            }
        }
        assertEquals(Stage.FAILED, LoginEngine(store, wifi).run().stage)
        assertEquals(0, scenario.logins()); assertEquals("new-student", store.value.username)
    }
}
