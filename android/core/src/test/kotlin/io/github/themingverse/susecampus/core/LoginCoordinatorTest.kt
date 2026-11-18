package io.github.themingverse.susecampus.core

import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class LoginCoordinatorTest {
    @Test fun cancellationBeforeFirstDispatchDoesNotLeaveBusyState() = runTest {
        val store = MemoryStore()
        val wifi = TestWifi()
        val coordinator = LoginCoordinator(store, LoginEngine(store, wifi), backgroundScope)
        coordinator.startOrJoin()
        coordinator.cancel()
        assertFalse(coordinator.state.value.busy)
        assertEquals(Stage.CANCELLED, coordinator.state.value.status.stage)
        assertTrue(wifi.scenario.calls.isEmpty())
    }
    @Test fun historyWriteFailureDoesNotReportPublishedSuccess() = runTest {
        val store = MemoryStore()
        val wifi = TestWifi()
        val coordinator = LoginCoordinator(store, LoginEngine(store, wifi), backgroundScope, record = {
            if (!it.busy) throw java.io.IOException("synthetic history write failure")
        })
        coordinator.startOrJoin(); runCurrent()
        assertFalse(coordinator.state.value.busy)
        assertEquals(Stage.FAILED, coordinator.state.value.status.stage)
        assertEquals(1, wifi.scenario.logins())
        assertTrue(wifi.scenario.closed)
    }
    @Test fun threeEntrancesJoinOneTaskAndPublishAfterRelease() = runTest {
        val wifi = TestWifi().apply { scenario.gate = CompletableDeferred() }
        val store = MemoryStore()
        val records = mutableListOf<OperationState>()
        val coordinator = LoginCoordinator(store, LoginEngine(store, wifi), backgroundScope, record = {
            if (!it.busy) assertTrue(wifi.scenario.closed)
            records.add(it)
        })
        val first = coordinator.startOrJoin()
        runCurrent()
        assertEquals(first, coordinator.startOrJoin())
        assertEquals(first, coordinator.startOrJoin(automatic = true))
        wifi.scenario.gate!!.complete(Unit)
        runCurrent()
        assertFalse(coordinator.state.value.busy)
        assertEquals(Stage.ONLINE, coordinator.state.value.status.stage)
        assertEquals(1, wifi.scenario.logins())
        assertEquals(listOf(true, false), records.map { it.busy })
    }
    @Test fun explicitLoginReplacesReadOnlyRefreshWithoutParallelSubmission() = runTest {
        val wifi = TestWifi().apply { scenario.gate = CompletableDeferred() }
        val store = MemoryStore()
        val coordinator = LoginCoordinator(store, LoginEngine(store, wifi), backgroundScope)
        val refresh = coordinator.startOrJoin(refreshOnly = true)
        runCurrent()
        val login = coordinator.startOrJoin()
        assertNotEquals(refresh, login)
        assertEquals(1, wifi.closes)
        wifi.scenario.gate!!.complete(Unit)
        runCurrent()
        assertEquals(1, wifi.scenario.logins())
    }
    @Test fun backgroundCancellationTerminatesAndClearsBusyState() = runTest {
        val wifi = TestWifi().apply { scenario.gate = CompletableDeferred() }
        val store = MemoryStore()
        val coordinator = LoginCoordinator(store, LoginEngine(store, wifi), backgroundScope)
        coordinator.startOrJoin(); runCurrent()
        coordinator.cancel()
        assertEquals(Stage.CANCELLED, coordinator.state.value.status.stage)
        assertFalse(coordinator.state.value.busy)
        assertEquals(1, wifi.closes)
    }
    @Test fun saveWaitsForOldTaskThenChangesRevision() = runTest {
        val wifi = TestWifi().apply { scenario.gate = CompletableDeferred() }
        val store = MemoryStore()
        val coordinator = LoginCoordinator(store, LoginEngine(store, wifi), backgroundScope)
        coordinator.startOrJoin(); runCurrent()
        coordinator.saveConfiguration(Configuration("new-test", "synthetic-new", "A"))
        assertEquals(1, wifi.closes)
        assertEquals("new-test", store.load().username)
        assertEquals(0L, coordinator.state.value.id)
        assertEquals(0, wifi.scenario.logins())
    }
    @Test fun noVisibleActivityCannotStartNetworkWork() = runTest {
        val wifi = TestWifi()
        val store = MemoryStore()
        val coordinator = LoginCoordinator(store, LoginEngine(store, wifi), backgroundScope, allowed = { false })
        assertEquals(0L, coordinator.startOrJoin())
        assertTrue(wifi.scenario.calls.isEmpty())
    }
    @Test fun quickEntryConsumesAutomaticSessionAndDoesNotQueueAnotherCheck() = runTest {
        val store = MemoryStore()
        val coordinator = LoginCoordinator(store, LoginEngine(store, TestWifi()), backgroundScope)
        coordinator.markExplicit()
        assertFalse(coordinator.consumeAutomatic())
        coordinator.newForegroundSession()
        assertTrue(coordinator.consumeAutomatic())
        assertFalse(coordinator.consumeAutomatic())
    }
    @Test fun completedTaskIsNotReusedForANewClick() = runTest {
        val store = MemoryStore()
        val wifi = TestWifi()
        val coordinator = LoginCoordinator(store, LoginEngine(store, wifi), backgroundScope)
        val first = coordinator.startOrJoin(); runCurrent()
        wifi.scenario.probeResults.add("online")
        val next = coordinator.startOrJoin()
        assertNotEquals(first, next)
        runCurrent()
        assertEquals(Stage.ONLINE, coordinator.state.value.status.stage)
        assertEquals(1, wifi.scenario.logins())
    }
}
