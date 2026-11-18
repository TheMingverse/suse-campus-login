package io.github.themingverse.susecampus.update

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.runtime.getValue

class UpdateActivity : ComponentActivity() {
    private val model: UpdateViewModel by viewModels()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val colors = if (isSystemInDarkTheme()) darkColorScheme(primary = Color(0xFF9DD5C7))
                else lightColorScheme(primary = Color(0xFF245B51), secondary = Color(0xFF50665F), background = Color(0xFFF7FAF6))
            MaterialTheme(colorScheme = colors) {
                val state by model.ui.collectAsStateWithLifecycle()
                UpdateScreen(state, model::saveSettings, model::check, model::download, model::cancel,
                    { model.install(this) }, { model.requestPermission(this) }, { finish() })
            }
        }
        if (savedInstanceState == null && intent.getBooleanExtra(CHECK_ON_OPEN, false)) model.check()
    }
    override fun onResume() { super.onResume(); model.permissionReturned(this) }
    override fun onStop() { if (!isChangingConfigurations) model.cancel(); super.onStop() }
    companion object { const val CHECK_ON_OPEN = "check_update_on_open" }
}
