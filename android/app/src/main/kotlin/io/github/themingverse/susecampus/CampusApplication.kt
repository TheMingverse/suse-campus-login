package io.github.themingverse.susecampus

import android.app.*
import android.os.Bundle
import io.github.themingverse.susecampus.core.*
import kotlinx.coroutines.*

class CampusApplication : Application(), Application.ActivityLifecycleCallbacks {
    val updates by lazy { io.github.themingverse.susecampus.update.AndroidForegroundUpdates(this) }
    val widgetPins by lazy { WidgetPinController(AndroidWidgetPinGateway(this), PinFile(this)) }
    val graph by lazy { CampusGraph(this) }
    private var visible = 0
    private var external = false
    fun externalFlow() { external = true }
    val hasVisibleActivity get() = visible > 0 && !getSystemService(KeyguardManager::class.java).isKeyguardLocked
    override fun onCreate() {
        super.onCreate()
        registerActivityLifecycleCallbacks(this)
        registerActivityLifecycleCallbacks(updates)
    }
    override fun onActivityStarted(activity: Activity) { visible++; external = false }
    override fun onActivityStopped(activity: Activity) {
        visible = (visible - 1).coerceAtLeast(0)
        if (visible == 0 && !activity.isChangingConfigurations) {
            val preserveSession = external
            graph.scope.launch {
                if (!hasVisibleActivity) {
                    graph.coordinator.cancel()
                    if (!preserveSession) graph.coordinator.newForegroundSession()
                }
            }
        }
    }
    override fun onActivityCreated(a: Activity, state: Bundle?) {}
    override fun onActivityResumed(a: Activity) {}
    override fun onActivityPaused(a: Activity) {}
    override fun onActivitySaveInstanceState(a: Activity, state: Bundle) {}
    override fun onActivityDestroyed(a: Activity) {}
}

class CampusGraph(private val app: CampusApplication) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    val store = SecureConfigurationStore(app)
    val engine = LoginEngine(store, AndroidWifiAccess(app))
    val history = QuickResultStore(app)
    val coordinator = LoginCoordinator(store, engine, scope, { app.hasVisibleActivity }) { operation ->
        history.record(operation)
        runCatching { QuickWidgets.updateAll(app) }
    }
    suspend fun save(config: Configuration) {
        coordinator.saveConfiguration(config)
        history.invalidate()
        QuickWidgets.updateAll(app)
    }
}
