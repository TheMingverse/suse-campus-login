package io.github.themingverse.susecampus

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.widget.TextView
import io.github.themingverse.susecampus.core.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29, 34, 36], application = CampusApplication::class)
class QuickComponentsTest {
    private val context get() = RuntimeEnvironment.getApplication() as CampusApplication
    private class MemoryBlob : ConfigurationBlob {
        var bytes: ByteArray? = null
        override fun read() = bytes
        override fun write(bytes: ByteArray) { this.bytes = bytes }
    }
    @Test fun widgetRemoteViewsHaveHistoricalStatusAndExplicitImmutableActivityIntent() {
        val result = QuickResult(QuickOutcome.ONLINE, 1794810000000L, 7)
        val view = QuickWidgets.views(context, true, result).apply(context, null)
        assertTrue(view.findViewById<TextView>(R.id.widget_result).text.startsWith("上次检查："))
        assertTrue(view.performClick())
        val intent = shadowOf(context).nextStartedActivity
        assertEquals(QuickLoginActivity::class.java.name, intent.component!!.className)
        val pending = QuickEntry.pendingIntent(context)
        assertTrue(shadowOf(pending).isActivityIntent)
        assertTrue(shadowOf(pending).flags and PendingIntent.FLAG_IMMUTABLE != 0)
        assertTrue(shadowOf(pending).savedIntent.extras == null)
    }
    @Test fun smallWidgetAndNightLayoutRenderWithoutCredentialAccess() {
        for (night in listOf(Configuration.UI_MODE_NIGHT_NO, Configuration.UI_MODE_NIGHT_YES)) {
            val config = Configuration(context.resources.configuration).apply { uiMode = night }
            val themed = context.createConfigurationContext(config)
            assertNotNull(QuickWidgets.views(themed, false, QuickResult()).apply(themed, null))
            assertNotNull(QuickWidgets.views(themed, true, QuickResult()).apply(themed, null))
        }
    }
    @Test fun freshInstallAndRebootRecoveryDoNotStartAuthentication() = runBlocking {
        val blob = MemoryBlob()
        val first = QuickResultStore(context, blob)
        assertEquals(QuickOutcome.NONE, first.state.value.outcome)
        first.record(OperationState(8, busy = true))
        val restored = QuickResultStore(context, blob)
        assertEquals(QuickOutcome.INTERRUPTED, restored.state.value.outcome)
        assertFalse(context.graph.coordinator.state.value.busy)
        assertEquals(0L, context.graph.coordinator.state.value.id)
    }
    @Test fun terminalResultsPersistAsCodesAndTimesWithoutSensitiveText() = runBlocking {
        val blob = MemoryBlob()
        val store = QuickResultStore(context, blob)
        val cases = listOf(
            LoginStatus(Stage.ONLINE) to QuickOutcome.ONLINE,
            LoginStatus(Stage.CANCELLED) to QuickOutcome.CANCELLED,
            LoginStatus(Stage.FAILED, failure = Failure.NO_WIFI) to QuickOutcome.NO_WIFI,
            LoginStatus(Stage.FAILED, failure = Failure.OUTSIDE) to QuickOutcome.OUTSIDE,
            LoginStatus(Stage.FAILED, failure = Failure.CREDENTIALS) to QuickOutcome.CREDENTIALS,
            LoginStatus(Stage.FAILED, failure = Failure.PERMISSION) to QuickOutcome.PERMISSION,
            LoginStatus(Stage.BLOCKED) to QuickOutcome.UNVERIFIED,
            LoginStatus(Stage.SETUP) to QuickOutcome.SETUP,
        )
        for ((status, outcome) in cases) {
            store.record(OperationState(4, status = status.copy(text = "synthetic-account password cookie http://sensitive.example/")))
            assertEquals(outcome, QuickResultStore(context, blob).state.value.outcome)
            assertFalse(blob.bytes!!.toString(Charsets.UTF_8).contains("synthetic-account"))
            assertFalse(blob.bytes!!.toString(Charsets.UTF_8).contains("http"))
        }
        store.invalidate(); assertEquals(QuickOutcome.STALE, store.state.value.outcome)
    }
    @Test fun addDeleteAndReaddOnlyRepaintExistingState() {
        val id = context.graph.coordinator.state.value.id
        for (provider in listOf(SmallLoginWidget(), WideLoginWidget())) {
            provider.onReceive(context, Intent("android.appwidget.action.APPWIDGET_UPDATE").putExtra("appWidgetIds", intArrayOf(99)))
            provider.onDeleted(context, intArrayOf(99))
            provider.onReceive(context, Intent("android.appwidget.action.APPWIDGET_UPDATE").putExtra("appWidgetIds", intArrayOf(100)))
        }
        assertEquals(id, context.graph.coordinator.state.value.id)
        assertFalse(context.graph.coordinator.state.value.busy)
    }
    @Test fun tileUsesOnlyVersionAppropriateLaunchPath() {
        for (sdk in listOf(29, 30, 33, 34, 35, 36)) {
            var modern = 0; var legacy = 0
            TileDispatch.launch(sdk, { modern++ }, { legacy++ })
            assertEquals(if (sdk >= 34) 1 else 0, modern)
            assertEquals(if (sdk < 34) 1 else 0, legacy)
        }
    }
    @Test fun internalActivityHandoffDoesNotRearmAutomaticButHomeDoes() {
        val first = android.app.Activity()
        val second = android.app.Activity()
        context.onActivityStarted(first)
        context.graph.coordinator.markExplicit()
        context.onActivityStarted(second)
        context.onActivityStopped(first)
        assertFalse(context.graph.coordinator.consumeAutomatic())
        context.onActivityStopped(second)
        shadowOf(android.os.Looper.getMainLooper()).idle()
        assertTrue(context.graph.coordinator.consumeAutomatic())
    }
    @Test fun restoredWidgetDispatchIsReadOnlyAndLeavesNoPendingTask() {
        SmallLoginWidget().onReceive(context, Intent("android.appwidget.action.APPWIDGET_RESTORED")
            .putExtra("appWidgetOldIds", intArrayOf(10)).putExtra("appWidgetIds", intArrayOf(20)))
        assertFalse(context.graph.coordinator.state.value.busy)
        assertEquals(0L, context.graph.coordinator.state.value.id)
    }
    @Test fun rotationDoesNotRearmTheAutomaticForegroundSession() {
        val controller = org.robolectric.Robolectric.buildActivity(android.app.Activity::class.java).create().start().resume()
        context.graph.coordinator.markExplicit()
        controller.configurationChange()
        shadowOf(android.os.Looper.getMainLooper()).idle()
        assertFalse(context.graph.coordinator.consumeAutomatic())
        controller.pause().stop().destroy()
    }
}
