package io.github.themingverse.susecampus

import android.Manifest
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.ui.graphics.Color

class MainActivity : ComponentActivity() {
    private val model: CampusViewModel by viewModels()
    private var pendingRefresh = false
    private val permission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        // A denial also runs the guarded check, so the UI offers a concrete recovery message.
        if (pendingRefresh) model.refresh() else model.check()
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (intent.getBooleanExtra("configure", false)) model.edit()
        enableEdgeToEdge()
        setContent {
            val colors = if (isSystemInDarkTheme()) darkColorScheme(primary = Color(0xFF9DD5C7))
                else lightColorScheme(primary = Color(0xFF245B51), secondary = Color(0xFF50665F), background = Color(0xFFF7FAF6))
            MaterialTheme(colorScheme = colors) {
                CampusScreen(model, requestPermission = { refresh ->
                    pendingRefresh = refresh; model.externalFlow()
                    permission.launch(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION))
                }, openLocationSettings = {
                    model.externalFlow(); startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS))
                }, openAppSettings = {
                    model.externalFlow(); startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        android.net.Uri.parse("package:$packageName")))
                }, openUpdates = {
                    openUpdatePage(false)
                }, updateChecker = (application as CampusApplication).updates.checker, openPromptedUpdate = {
                    openUpdatePage(true)
                })
            }
        }
    }
    private fun openUpdatePage(checkOnOpen: Boolean) {
        model.externalFlow()
        startActivity(io.github.themingverse.susecampus.update.updatePageIntent(this, checkOnOpen))
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent)
        if (intent.getBooleanExtra("configure", false)) model.edit()
    }
    override fun onStart() { super.onStart(); model.foreground() }
    override fun onStop() {
        if (!isChangingConfigurations) model.background()
        super.onStop()
    }
}
