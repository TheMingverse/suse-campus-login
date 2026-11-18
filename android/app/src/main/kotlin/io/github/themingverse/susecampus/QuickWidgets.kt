package io.github.themingverse.susecampus

import android.app.*
import android.appwidget.*
import android.content.*
import android.os.Build
import android.os.Bundle
import android.widget.RemoteViews
import kotlinx.coroutines.*

object QuickEntry {
    fun intent(context: Context) = Intent(context, QuickLoginActivity::class.java).setAction("io.github.themingverse.susecampus.QUICK_LOGIN")
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    fun pendingIntent(context: Context, request: Int = 10): PendingIntent {
        val options = ActivityOptions.makeBasic()
        // Only these explicit, immutable tokens are handed to the user-operated Launcher/SystemUI.
        if (Build.VERSION.SDK_INT >= 36) options.setPendingIntentCreatorBackgroundActivityStartMode(ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOW_ALWAYS)
        else if (Build.VERSION.SDK_INT >= 35) {
            @Suppress("DEPRECATION")
            options.setPendingIntentCreatorBackgroundActivityStartMode(ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED)
        }
        return PendingIntent.getActivity(context, request, intent(context), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE, options.toBundle())
    }
}

object QuickWidgets {
    fun views(context: Context, large: Boolean, result: QuickResult, allowLogin: Boolean = true): RemoteViews = RemoteViews(context.packageName,
        if (large) R.layout.widget_login_wide else R.layout.widget_login_small).apply {
        if (allowLogin) setOnClickPendingIntent(R.id.widget_root, QuickEntry.pendingIntent(context))
        setContentDescription(R.id.widget_root, if (allowLogin) "SUSE 登录。${result.description()}。点击检查校园 Wi-Fi 并按需认证。" else "SUSE 登录小组件预览")
        if (large) setTextViewText(R.id.widget_result, result.description())
    }
    fun updateAll(context: Context) {
        val graph = (context.applicationContext as CampusApplication).graph
        val manager = AppWidgetManager.getInstance(context)
        for ((provider, wide) in listOf(SmallLoginWidget::class.java to false, WideLoginWidget::class.java to true)) {
            val ids = manager.getAppWidgetIds(ComponentName(context, provider))
            if (ids.isNotEmpty()) manager.updateAppWidget(ids, views(context, wide, graph.history.state.value))
        }
    }
}

open class LoginWidgetProvider : AppWidgetProvider() {
    override fun onReceive(context: Context, intent: Intent) {
        // AppWidgetProvider can dispatch BOTH onRestored and onUpdate from one broadcast.
        // Acquire exactly one PendingResult for the entire dispatch, not one per callback.
        val pending = goAsync()
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try { runCatching { super.onReceive(context.applicationContext, intent) } } finally { pending?.finish() }
        }
    }
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) = QuickWidgets.updateAll(context)
    override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, options: Bundle) = QuickWidgets.updateAll(context)
    override fun onRestored(context: Context, oldIds: IntArray, newIds: IntArray) = QuickWidgets.updateAll(context)
}
class SmallLoginWidget : LoginWidgetProvider()
class WideLoginWidget : LoginWidgetProvider()
