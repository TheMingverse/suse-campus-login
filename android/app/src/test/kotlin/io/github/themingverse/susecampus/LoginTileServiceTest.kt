package io.github.themingverse.susecampus

import android.app.PendingIntent
import android.content.Intent
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.*
import org.robolectric.shadow.api.Shadow

/** Model the SystemUI boundary: tests choose whether the user completes or cancels unlock. */
@Implements(TileService::class)
class TileSystemUiShadow : org.robolectric.shadows.ShadowService() {
    @RealObject lateinit var service: TileService
    var locked = false
    var unlock: Runnable? = null
    @Implementation fun isLocked() = locked
    @Implementation fun unlockAndRun(runnable: Runnable) { unlock = runnable }
    @Implementation fun getQsTile(): Tile? = null
    @Implementation(maxSdk = 33) fun startActivityAndCollapse(intent: Intent) { service.startActivity(intent) }
    @Implementation(minSdk = 34) fun startActivityAndCollapse(pending: PendingIntent) { pending.send() }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29, 34, 36], application = CampusApplication::class, shadows = [TileSystemUiShadow::class])
class LoginTileServiceTest {
    private val app get() = RuntimeEnvironment.getApplication() as CampusApplication
    @Test fun unlockedClickStartsOnlyQuickActivityAndDoesNotAuthenticateInService() {
        val controller = Robolectric.buildService(LoginTileService::class.java).create()
        controller.get().onClick()
        assertEquals(QuickLoginActivity::class.java.name, shadowOf(app).nextStartedActivity.component!!.className)
        assertEquals(0L, app.graph.coordinator.state.value.id)
        controller.destroy()
    }
    @Test fun cancelledUnlockDoesNotLaunchButSuccessfulUnlockDoes() {
        val controller = Robolectric.buildService(LoginTileService::class.java).create()
        val service = controller.get()
        val boundary = Shadow.extract<TileSystemUiShadow>(service)
        boundary.locked = true
        service.onClick()
        assertNotNull(boundary.unlock)
        assertNull(shadowOf(app).nextStartedActivity)
        boundary.unlock = null // User cancels the system unlock prompt.
        assertEquals(0L, app.graph.coordinator.state.value.id)
        service.onClick(); boundary.locked = false; boundary.unlock!!.run()
        assertEquals(QuickLoginActivity::class.java.name, shadowOf(app).nextStartedActivity.component!!.className)
        controller.destroy()
    }
    @Test fun listeningAndStoppingNeverStartNetworkWork() {
        val controller = Robolectric.buildService(LoginTileService::class.java).create()
        controller.get().onStartListening()
        shadowOf(android.os.Looper.getMainLooper()).idle()
        controller.get().onStopListening()
        assertFalse(app.graph.coordinator.state.value.busy)
        assertEquals(0L, app.graph.coordinator.state.value.id)
        controller.destroy()
    }
}
