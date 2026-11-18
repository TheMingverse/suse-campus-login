package io.github.themingverse.susecampus

import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collectLatest

class LoginTileService : TileService() {
    private var listening: CoroutineScope? = null
    override fun onStartListening() {
        super.onStartListening()
        listening?.cancel()
        listening = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate).also { scope ->
            val graph = (application as CampusApplication).graph
            scope.launch { graph.coordinator.state.collectLatest { repaint() } }
            scope.launch { graph.history.state.collectLatest { repaint() } }
        }
    }
    private fun repaint() {
        val tile = qsTile ?: return
        val graph = (application as CampusApplication).graph
        val busy = graph.coordinator.state.value.busy
        tile.label = "SUSE 登录"
        tile.state = if (busy) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        tile.subtitle = if (busy) "点击查看本次进度" else graph.history.state.value.description()
        tile.contentDescription = "SUSE 登录。${tile.subtitle}"
        tile.updateTile()
    }
    override fun onStopListening() { listening?.cancel(); listening = null; super.onStopListening() }
    override fun onDestroy() { listening?.cancel(); super.onDestroy() }
    override fun onClick() {
        super.onClick()
        val launch = Runnable {
            runCatching {
                TileDispatch.launch(Build.VERSION.SDK_INT,
                    modern = { if (Build.VERSION.SDK_INT >= 34) startActivityAndCollapse(QuickEntry.pendingIntent(this, 20)) },
                    legacy = { launchLegacy() })
            }.onFailure {
                qsTile?.apply { state = Tile.STATE_INACTIVE; subtitle = "请打开 SUSE 校园网重试"; updateTile() }
            }
        }
        if (isLocked) unlockAndRun(launch) else launch.run()
    }
    // This overload is the only platform API available on 29-33. Dispatch excludes API 34+.
    @android.annotation.SuppressLint("StartActivityAndCollapseDeprecated")
    @Suppress("DEPRECATION")
    private fun launchLegacy() { startActivityAndCollapse(QuickEntry.intent(this)) }
}

object TileDispatch {
    fun launch(sdk: Int, modern: () -> Unit, legacy: () -> Unit) { if (sdk >= 34) modern() else legacy() }
}
