package io.github.themingverse.susecampus

import android.content.ComponentName
import android.content.pm.PackageManager
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Safe on a configured phone: never launches authentication or reads the saved account. */
@RunWith(AndroidJUnit4::class)
class QuickWidgetDeviceTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    @Test fun realRemoteViewsInflateAndClearlyLabelHistoricalResult() {
        val result = QuickResult(QuickOutcome.ONLINE, 1794810000000L, 1)
        val wide = QuickWidgets.views(context, true, result).apply(context, null)
        assertTrue(wide.findViewById<TextView>(R.id.widget_result).text.startsWith("上次检查："))
        assertNotNull(QuickWidgets.views(context, false, result).apply(context, null))
    }
    @Test fun manifestOnlyExposesPermissionProtectedTileAndPrivateQuickActivity() {
        @Suppress("DEPRECATION")
        val tile = context.packageManager.getServiceInfo(ComponentName(context, LoginTileService::class.java), 0)
        assertEquals("android.permission.BIND_QUICK_SETTINGS_TILE", tile.permission)
        assertTrue(tile.exported)
        @Suppress("DEPRECATION")
        val activity = context.packageManager.getActivityInfo(ComponentName(context, QuickLoginActivity::class.java), 0)
        assertFalse(activity.exported)
        @Suppress("DEPRECATION")
        val receiver = context.packageManager.getReceiverInfo(ComponentName(context, WideLoginWidget::class.java), PackageManager.GET_META_DATA)
        assertFalse(receiver.exported)
        assertNotNull(receiver.metaData)
    }
    @Test fun launchIntentIsExplicitAndContainsNoCredentials() {
        val intent = QuickEntry.intent(context)
        assertEquals(QuickLoginActivity::class.java.name, intent.component!!.className)
        assertNull(intent.extras)
    }
}
