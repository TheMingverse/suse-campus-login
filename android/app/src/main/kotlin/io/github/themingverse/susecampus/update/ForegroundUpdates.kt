package io.github.themingverse.susecampus.update

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

data class ForegroundUpdateState(val homeVisible: Boolean = false, val checking: Boolean = false,
                                 val release: ReleaseInfo? = null) {
    fun showPrompt(blocked: Boolean) = homeVisible && !blocked && release != null
}

/** Main-thread state machine. No APK cache, account access, installation, timers or background jobs. */
class ForegroundUpdateChecker(
    private val scope: CoroutineScope,
    private val settings: () -> UpdateSettings,
    private val installed: () -> InstalledVersion,
    private val sdk: Int,
    private val fetch: suspend (UpdateSettings) -> ReleaseInfo?,
) {
    private val mutable = MutableStateFlow(ForegroundUpdateState())
    val state = mutable.asStateFlow()
    private var foreground = false
    private var attempted = false
    private var generation = 0L
    private var work: Job? = null

    fun foreground() {
        if (foreground) return
        foreground = true
        attempted = false
        generation++
    }
    fun homeResumed() {
        mutable.value = mutable.value.copy(homeVisible = true)
        checkIfNeeded()
    }
    fun homePaused() { mutable.value = mutable.value.copy(homeVisible = false) }
    fun background() {
        foreground = false
        generation++
        work?.cancel()
        mutable.value = ForegroundUpdateState()
    }
    fun settingsChanged() {
        generation++
        work?.cancel()
        attempted = false
        mutable.value = ForegroundUpdateState(homeVisible = mutable.value.homeVisible)
        checkIfNeeded()
    }
    fun dismiss() { mutable.value = mutable.value.copy(release = null) }

    private fun checkIfNeeded() {
        if (!foreground || !mutable.value.homeVisible || attempted) return
        val selected = try { settings() } catch (_: Exception) { return }
        if (!selected.checkOnOpen) return
        attempted = true
        val token = generation
        val previous = work
        mutable.value = mutable.value.copy(checking = true)
        work = scope.launch {
            // A canceled request must finish cleanup before another foreground starts one.
            previous?.cancelAndJoin()
            try {
                ensureActive()
                val info = fetch(selected)
                ensureActive()
                if (token == generation && foreground && settings() == selected && info != null &&
                    info.minSdk <= sdk && UpdateChecker.compare(installed(), info) == VersionDecision.AVAILABLE) {
                    mutable.value = mutable.value.copy(release = info)
                }
            } catch (error: CancellationException) { throw error }
            catch (_: Exception) {
                // Automatic checks never interrupt campus login. The update page can explain/retry failures.
            } finally {
                if (token == generation) mutable.value = mutable.value.copy(checking = false)
            }
        }
    }
}

/** Application-wide activity visibility, so changing activities/rotation is not a new visit. */
class UpdateForegroundSession(private val checker: ForegroundUpdateChecker) {
    private val started = mutableSetOf<Any>()
    fun started(activity: Any) {
        if (started.add(activity) && started.size == 1) checker.foreground()
    }
    fun stopped(activity: Any, changingConfiguration: Boolean) {
        if (started.remove(activity) && started.isEmpty() && !changingConfiguration) checker.background()
    }
}
