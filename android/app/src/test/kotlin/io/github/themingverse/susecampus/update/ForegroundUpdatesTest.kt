package io.github.themingverse.susecampus.update

import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ForegroundUpdatesTest {
    private val newer get() = testRelease(code = 6, channel = UpdateChannel.GITHUB).copy(
        versionName = "0.4.1", tag = "android-v0.4.1", fileName = "SUSE-CampusLogin-Android-v0.4.1-release.apk")
    private class Fixture(scope: CoroutineScope) {
        var settings = UpdateSettings()
        var installed = InstalledVersion("0.4.0", 5)
        var calls = 0
        var fetch: suspend (UpdateSettings) -> ReleaseInfo? = { null }
        val checker = ForegroundUpdateChecker(scope, { settings }, { installed }, 36) {
            calls++; fetch(it)
        }
        val sessions = UpdateForegroundSession(checker)
        val home = Any()
        fun open() { sessions.started(home); checker.homeResumed() }
        fun close() { checker.homePaused(); sessions.stopped(home, false) }
    }

    @Test fun newerReleaseProducesForegroundPromptAndUsesSelectedSettings() = runTest {
        val f = Fixture(this)
        f.fetch = { assertEquals(UpdateChannel.GITHUB, it.channel); newer }
        f.open(); runCurrent()
        assertTrue(f.checker.state.value.showPrompt(false))
        assertEquals("0.4.1", f.checker.state.value.release!!.versionName)
        assertEquals(1, f.calls)
    }

    @Test fun currentOlderAndEmptySourcesNeverOfferAnUpdate() = runTest {
        val f = Fixture(this)
        for (release in listOf(null, newer.copy(versionCode = 5, versionName = "0.4.0"),
                               newer.copy(versionCode = 4, versionName = "0.3.0"))) {
            f.fetch = { release }; f.open(); runCurrent()
            assertNull(f.checker.state.value.release); f.close()
        }
        assertEquals(3, f.calls)
    }

    @Test fun unsafeMetadataAndNetworkFailuresStaySilentAndCanRetryNextVisit() = runTest {
        val f = Fixture(this)
        for (error in listOf(UpdateError.NETWORK, UpdateError.SERVICE, UpdateError.SECURITY, UpdateError.NOT_CONFIGURED)) {
            f.fetch = { throw UpdateException(error, "synthetic error") }
            f.open(); runCurrent()
            assertFalse(f.checker.state.value.checking); assertFalse(f.checker.state.value.showPrompt(false))
            f.close()
        }
        f.fetch = { newer }; f.open(); runCurrent()
        assertTrue(f.checker.state.value.showPrompt(false))
    }

    @Test fun equalCodeWrongNameAndUnsupportedSdkAreNotOffered() = runTest {
        val f = Fixture(this)
        for (release in listOf(newer.copy(versionCode = 5), newer.copy(minSdk = 37))) {
            f.fetch = { release }; f.open(); runCurrent()
            assertNull(f.checker.state.value.release); f.close()
        }
    }

    @Test fun repeatedResumeAndRenderingDoNotStartDuplicateRequests() = runTest {
        val f = Fixture(this); val response = CompletableDeferred<ReleaseInfo>()
        f.fetch = { response.await() }
        f.open(); repeat(10) { f.checker.homeResumed() }; runCurrent()
        assertEquals(1, f.calls)
        response.complete(newer); runCurrent()
        repeat(10) { f.checker.homeResumed() }; runCurrent()
        assertEquals(1, f.calls)
    }

    @Test fun rotationRetainsOneCheckAndOnePendingPrompt() = runTest {
        val f = Fixture(this); f.fetch = { newer }; f.open(); runCurrent()
        f.checker.homePaused(); f.sessions.stopped(f.home, true)
        val rotated = Any(); f.sessions.started(rotated); f.checker.homeResumed(); runCurrent()
        assertEquals(1, f.calls); assertTrue(f.checker.state.value.showPrompt(false))
    }

    @Test fun visitingUpdatePageAndReturningDoesNotRecheckOrRepeatDismissedPrompt() = runTest {
        val f = Fixture(this); f.fetch = { newer }; f.open(); runCurrent()
        f.checker.dismiss()
        val updatePage = Any()
        f.sessions.started(updatePage); f.checker.homePaused(); f.sessions.stopped(f.home, false)
        f.sessions.started(f.home); f.sessions.stopped(updatePage, false); f.checker.homeResumed(); runCurrent()
        assertEquals(1, f.calls); assertNull(f.checker.state.value.release)
    }

    @Test fun laterOnlyDismissesThisForegroundVisit() = runTest {
        val f = Fixture(this); f.fetch = { newer }; f.open(); runCurrent()
        f.checker.dismiss(); f.checker.homeResumed(); runCurrent()
        assertFalse(f.checker.state.value.showPrompt(false)); assertEquals(1, f.calls)
        f.close(); f.open(); runCurrent()
        assertTrue(f.checker.state.value.showPrompt(false)); assertEquals(2, f.calls)
    }

    @Test fun loginEditingOrSavingDelaysPromptWithoutRepeatingNetworkCheck() = runTest {
        val f = Fixture(this); f.fetch = { newer }; f.open(); runCurrent()
        assertFalse(f.checker.state.value.showPrompt(true))
        assertTrue(f.checker.state.value.showPrompt(false))
        assertEquals(1, f.calls)
    }

    @Test fun disabledCheckDoesNotCallSourceAndEnablingCanCheck() = runTest {
        val f = Fixture(this); f.settings = f.settings.copy(checkOnOpen = false); f.fetch = { newer }
        f.open(); runCurrent(); assertEquals(0, f.calls)
        f.settings = f.settings.copy(checkOnOpen = true); f.checker.settingsChanged(); runCurrent()
        assertEquals(1, f.calls); assertTrue(f.checker.state.value.showPrompt(false))
    }

    @Test fun disablingCancelsInflightRequestAndClearsPendingPrompt() = runTest {
        val f = Fixture(this); var canceled = false
        f.fetch = { try { awaitCancellation() } finally { canceled = true } }
        f.open(); runCurrent()
        f.settings = f.settings.copy(checkOnOpen = false); f.checker.settingsChanged(); runCurrent()
        assertTrue(canceled); assertFalse(f.checker.state.value.checking); assertNull(f.checker.state.value.release)
    }

    @Test fun backgroundCancelsAndDiscardsLateResults() = runTest {
        val f = Fixture(this)
        f.fetch = { withContext(NonCancellable) { delay(100); newer } }
        f.open(); runCurrent(); f.close(); advanceUntilIdle()
        assertFalse(f.checker.state.value.homeVisible); assertNull(f.checker.state.value.release)
    }

    @Test fun fastBackgroundReturnWaitsForPreviousCleanupAndKeepsSingleFlight() = runTest {
        val f = Fixture(this); var active = 0; var maximum = 0
        f.fetch = {
            active++; maximum = maxOf(maximum, active)
            try { delay(100); newer } finally { withContext(NonCancellable) { delay(20); active-- } }
        }
        f.open(); runCurrent(); f.close(); f.open(); advanceUntilIdle()
        assertEquals(1, maximum); assertEquals(2, f.calls); assertTrue(f.checker.state.value.showPrompt(false))
    }

    @Test fun changingChannelInvalidatesResultAndUsesNewSetting() = runTest {
        val f = Fixture(this); val seen = mutableListOf<UpdateChannel>()
        f.fetch = { seen += it.channel; newer }
        f.open(); runCurrent()
        f.settings = f.settings.copy(channel = UpdateChannel.AUTO); f.checker.settingsChanged(); runCurrent()
        assertEquals(listOf(UpdateChannel.GITHUB, UpdateChannel.AUTO), seen)
    }

    @Test fun pausedHomeCannotShowAnArrivingPrompt() = runTest {
        val f = Fixture(this); val response = CompletableDeferred<ReleaseInfo>()
        f.fetch = { response.await() }; f.open(); runCurrent(); f.checker.homePaused()
        response.complete(newer); runCurrent()
        assertFalse(f.checker.state.value.showPrompt(false))
        f.checker.homeResumed(); assertTrue(f.checker.state.value.showPrompt(false)); assertEquals(1, f.calls)
    }

    @Test fun quickEntryOrOtherActivitiesAloneNeverStartUpdateRequests() = runTest {
        val f = Fixture(this); val quick = Any()
        f.sessions.started(quick); runCurrent(); assertEquals(0, f.calls)
        f.sessions.stopped(quick, false)
    }

    @Test fun canceledSettingsReadAndMalformedPreferencesDoNotCrashHome() = runTest {
        var calls = 0
        val checker = ForegroundUpdateChecker(this, { error("invalid preferences") }, { InstalledVersion("0.4.0", 5) }, 36) {
            calls++; newer
        }
        checker.foreground(); checker.homeResumed(); runCurrent()
        assertEquals(0, calls); assertNull(checker.state.value.release)
    }
}
