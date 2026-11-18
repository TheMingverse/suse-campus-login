package io.github.themingverse.susecampus

import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Context
import android.graphics.drawable.Icon
import android.os.Build
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun QuickEntryControls() {
    val context = LocalContext.current
    val pins = (context.applicationContext as CampusApplication).widgetPins
    val pinState by pins.state.collectAsStateWithLifecycle()
    var notice by remember { mutableStateOf("") }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("桌面与快捷入口", style = MaterialTheme.typography.titleMedium)
            Text("点击桌面小组件或控制中心磁贴，直接检查并按需登录。离开认证页面或锁屏会取消本次操作。")
            for ((label, size) in listOf("添加 1×1 小组件" to WidgetSize.SMALL, "添加 2×1 小组件" to WidgetSize.WIDE)) {
                OutlinedButton(onClick = { pins.request(size) }, enabled = pinState.phase != PinPhase.WAITING) { Text(label) }
            }
            if (pinState.message.isNotEmpty()) Text(pinState.message)
            if (pinState.phase in setOf(PinPhase.WAITING, PinPhase.MANUAL)) {
                Text("手动添加：长按桌面空白处 → 添加小组件 → SUSE 登录 → 选择 1×1 或 2×1。取消系统确认不会自动重试。")
                OutlinedButton(onClick = { pins.retry(WidgetSize.SMALL) }) { Text("重新请求 1×1") }
                OutlinedButton(onClick = { pins.retry(WidgetSize.WIDE) }) { Text("重新请求 2×1") }
                TextButton(onClick = {
                    if (!pins.returnHome()) notice = "无法打开桌面，请按 Home 键后按上方步骤添加。"
                }) { Text("返回桌面") }
            }
            OutlinedButton(onClick = {
                if (Build.VERSION.SDK_INT >= 33) {
                    runCatching {
                        context.getSystemService(StatusBarManager::class.java).requestAddTileService(
                            ComponentName(context, LoginTileService::class.java), "SUSE 登录",
                            Icon.createWithResource(context, R.drawable.ic_quick_login), context.mainExecutor) { result ->
                            notice = when (result) {
                                StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ADDED -> "SUSE 登录磁贴已添加。"
                                StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ALREADY_ADDED -> "SUSE 登录磁贴已经添加。"
                                else -> "可下拉控制中心，点击编辑，将 SUSE 登录拖入快捷区域。"
                            }
                        }
                    }.onFailure { notice = "请下拉控制中心，点击编辑并添加 SUSE 登录。" }
                } else notice = "请下拉控制中心，点击编辑，将 SUSE 登录拖入快捷区域。"
            }) { Text("添加快捷设置磁贴") }
            Text("小组件显示最近一次检查结果和时间，不代表实时联网状态。", style = MaterialTheme.typography.bodySmall)
            if (notice.isNotEmpty()) Text(notice)
        }
    }
}
