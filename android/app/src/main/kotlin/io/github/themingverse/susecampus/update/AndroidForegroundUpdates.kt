package io.github.themingverse.susecampus.update

import android.app.Activity
import android.app.Application
import android.app.KeyguardManager
import android.content.Intent
import android.content.SharedPreferences
import android.os.Build
import android.os.Bundle
import io.github.themingverse.susecampus.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class AndroidForegroundUpdates(private val application: Application) : Application.ActivityLifecycleCallbacks {
    private val store = UpdateSettingsStore(application)
    private val transport = UpdateHttp()
    val checker = ForegroundUpdateChecker(CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate),
        { store.load() }, { AndroidUpdateTrust.installed(application) }, Build.VERSION.SDK_INT,
        { selected -> updateRepository(selected, AndroidUpdateTrust.load(application), transport).latest() })
    private val sessions = UpdateForegroundSession(checker)
    private val changed = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> checker.settingsChanged() }
    init { store.observe(changed) }

    override fun onActivityStarted(activity: Activity) { sessions.started(activity) }
    override fun onActivityResumed(activity: Activity) {
        if (activity is MainActivity && !application.getSystemService(KeyguardManager::class.java).isKeyguardLocked)
            checker.homeResumed()
    }
    override fun onActivityPaused(activity: Activity) { if (activity is MainActivity) checker.homePaused() }
    override fun onActivityStopped(activity: Activity) { sessions.stopped(activity, activity.isChangingConfigurations) }
    override fun onActivityCreated(activity: Activity, state: Bundle?) {}
    override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) {}
    override fun onActivityDestroyed(activity: Activity) {}
}

fun updatePageIntent(context: android.content.Context, checkOnOpen: Boolean = false) =
    Intent(context, UpdateActivity::class.java).putExtra(UpdateActivity.CHECK_ON_OPEN, checkOnOpen)
