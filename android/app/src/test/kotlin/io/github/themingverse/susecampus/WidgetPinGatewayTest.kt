package io.github.themingverse.susecampus

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.os.Bundle
import android.widget.RemoteViews
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.*
import org.robolectric.shadow.api.Shadow

@Implements(AppWidgetManager::class)
class PinLauncherShadow : org.robolectric.shadows.ShadowAppWidgetManager() {
    var provider: ComponentName? = null
    var extras: Bundle? = null
    var callback: PendingIntent? = null
    @Implementation override fun isRequestPinAppWidgetSupported() = true
    @Implementation override fun requestPinAppWidget(provider: ComponentName, extras: Bundle?, successCallback: PendingIntent?): Boolean {
        this.provider = provider; this.extras = extras; callback = successCallback; return true
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29, 34, 36], application = CampusApplication::class, shadows = [PinLauncherShadow::class])
class WidgetPinGatewayTest {
    private val app get() = RuntimeEnvironment.getApplication() as CampusApplication
    @Test fun bothSizesSendCorrectPreviewAndImmutablePrivateCallback() {
        val gateway = AndroidWidgetPinGateway(app)
        val launcher = Shadow.extract<PinLauncherShadow>(AppWidgetManager.getInstance(app))
        for (size in WidgetSize.entries) {
            assertTrue(gateway.request(size, "test-${size.name}"))
            assertEquals(if (size == WidgetSize.SMALL) SmallLoginWidget::class.java.name else WideLoginWidget::class.java.name, launcher.provider!!.className)
            @Suppress("DEPRECATION")
            val preview = launcher.extras!!.getParcelable<RemoteViews>(AppWidgetManager.EXTRA_APPWIDGET_PREVIEW)!!
            assertEquals(if (size == WidgetSize.SMALL) R.layout.widget_login_small else R.layout.widget_login_wide, preview.layoutId)
            assertFalse(preview.apply(app, null).performClick())
            val callback = launcher.callback!!
            assertTrue(shadowOf(callback).flags and PendingIntent.FLAG_IMMUTABLE != 0)
            assertEquals(WidgetPinResultReceiver::class.java.name, shadowOf(callback).savedIntent.component!!.className)
            gateway.cancel("test-${size.name}")
        }
        assertNull(shadowOf(app).nextStartedActivity)
        assertEquals(0L, app.graph.coordinator.state.value.id)
    }
    @Test fun callbackBroadcastPayloadUpdatesOnlyPinState() {
        val launcher = Shadow.extract<PinLauncherShadow>(AppWidgetManager.getInstance(app))
        app.widgetPins.request(WidgetSize.SMALL)
        assertEquals(PinPhase.WAITING, app.widgetPins.state.value.phase)
        launcher.callback!!.send()
        shadowOf(android.os.Looper.getMainLooper()).idle()
        // Robolectric records explicit broadcasts but does not instantiate manifest receivers here.
        // Deliver that exact recorded payload to the production receiver at the system boundary.
        val delivered = shadowOf(app).broadcastIntents.last { it.action == AndroidWidgetPinGateway.ACTION }
        assertEquals(WidgetPinResultReceiver::class.java.name, delivered.component!!.className)
        @Suppress("DEPRECATION")
        val info = app.packageManager.getReceiverInfo(delivered.component!!, 0)
        assertFalse(info.exported)
        WidgetPinResultReceiver().onReceive(app, delivered)
        assertEquals(PinPhase.SUCCESS, app.widgetPins.state.value.phase)
        assertEquals(0L, app.graph.coordinator.state.value.id)
        assertNull(shadowOf(app).nextStartedActivity)
    }
    @Test fun homeIsAnExplicitActionAndIgnoresUnknownCallbacks() {
        app.widgetPins.request(WidgetSize.WIDE)
        WidgetPinResultReceiver().onReceive(app, AndroidWidgetPinGateway.callbackIntent(app, "stale"))
        assertEquals(PinPhase.WAITING, app.widgetPins.state.value.phase)
        assertNull(shadowOf(app).nextStartedActivity)
        assertTrue(app.widgetPins.returnHome())
        assertTrue(shadowOf(app).nextStartedActivity.categories.contains(android.content.Intent.CATEGORY_HOME))
        assertEquals(0L, app.graph.coordinator.state.value.id)
    }
}
