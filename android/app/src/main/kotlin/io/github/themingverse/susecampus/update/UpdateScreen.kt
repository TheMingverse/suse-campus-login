package io.github.themingverse.susecampus.update

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.util.Locale

fun updateSize(bytes: Long) = String.format(Locale.ROOT, "%.1f MB", bytes / 1048576.0)

@Composable
fun UpdateScreen(state: UpdateUiState, save: (UpdateChannel, String, Boolean) -> Unit, check: () -> Unit,
                 download: () -> Unit, cancel: () -> Unit, install: () -> Unit,
                 permission: () -> Unit, back: () -> Unit) {
    var selected by remember(state.settings) { mutableStateOf(state.settings.channel) }
    var repository by remember(state.settings) { mutableStateOf(state.settings.giteeRepository) }
    var checkOnOpen by remember(state.settings) { mutableStateOf(state.settings.checkOnOpen) }
    var confirm by remember { mutableStateOf(false) }
    val settingsChanged = selected != state.settings.channel || repository != state.settings.giteeRepository ||
        checkOnOpen != state.settings.checkOnOpen
    Scaffold { padding ->
        Column(Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp)) {
            TextButton(onClick = back) { Text("返回校园网登录") }
            Text("更新设置", style = MaterialTheme.typography.headlineLarge)
            Text("当前版本：${state.current.name}（${state.current.code}）")
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("更新渠道", style = MaterialTheme.typography.titleLarge)
                UpdateChannel.entries.forEach { channel ->
                    Row {
                        RadioButton(selected == channel, { selected = channel }, enabled = !state.busy)
                        TextButton(onClick = { selected = channel }, enabled = !state.busy) { Text(channel.label) }
                    }
                }
                Text("已保存渠道：${state.settings.channel.label}")
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    Text("打开 App 时检查更新", modifier = Modifier.weight(1f))
                    Switch(checkOnOpen, { checkOnOpen = it }, enabled = !state.busy)
                }
                Text("进入首页时检查，发现新版会提醒；不会自动下载或安装。")
                Text("自动选择优先使用 Gitee；未配置或网络不可用时尝试 GitHub。安全校验错误会停止更新。")
                OutlinedTextField(repository, { repository = it }, label = { Text("Gitee 镜像仓库（账号/仓库，可留空）") },
                    singleLine = true, enabled = !state.busy, modifier = Modifier.fillMaxWidth())
                if (state.settings.giteeRepository.isEmpty()) Text("Gitee 尚未配置，自动选择暂用 GitHub。")
                OutlinedButton(onClick = { save(selected, repository, checkOnOpen) }, enabled = settingsChanged && !state.busy) { Text("保存更新设置") }
            } }
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("检查更新", style = MaterialTheme.typography.titleLarge)
                state.actualSource?.let { Text("本次连接来源：${it.label}") }
                Text(state.message, color = if (state.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
                if (state.busy && !state.downloading) LinearProgressIndicator(Modifier.fillMaxWidth())
                Button(onClick = check, enabled = !state.busy && !settingsChanged) { Text("检查更新") }
                if (settingsChanged) Text("请先保存渠道设置，再检查更新。")
                if (state.error != null) Text("可在上方选择其他渠道并保存后重试。")
                state.release?.let { release ->
                    Text("来源版本：${release.versionName}（${release.versionCode}） · ${updateSize(release.size)}")
                    Text("发行：${release.tag}")
                    Text("更新日志", style = MaterialTheme.typography.titleMedium)
                    Text(release.releaseNotes.ifBlank { "本次发行未提供更新日志。" })
                    if (state.available && !state.ready && !state.busy)
                        Button(onClick = { confirm = true }, enabled = !settingsChanged) { Text("下载更新") }
                }
                state.progress?.let { progress ->
                    val fraction = (progress.bytes.toDouble() / progress.total).toFloat().coerceIn(0f, 1f)
                    LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth())
                    Text("${(fraction * 100).toInt()}% · ${updateSize(progress.bytes)} / ${updateSize(progress.total)}")
                    Text("下载来源：${progress.source.label}")
                }
                if (state.busy) OutlinedButton(onClick = cancel) { Text("取消本次更新操作") }
                if (state.ready) {
                    Text("安装前会再次核对 APK，安装由 Android 系统确认。")
                    Button(onClick = install, enabled = !state.busy && !settingsChanged) { Text("安装已验证的更新") }
                }
                if (state.permissionNeeded) OutlinedButton(onClick = permission, enabled = !state.busy) { Text("打开安装授权设置") }
            } }
            Text("首页可自动检查更新；下载和安装仍需你确认。离开前台会取消检查，离开本页会取消下载，不在后台常驻。", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
    if (confirm && state.release != null && !settingsChanged) AlertDialog(onDismissRequest = { confirm = false },
        title = { Text("确认下载更新") }, text = { Text("下载 ${state.release.versionName}，大小 ${updateSize(state.release.size)}。完成安全检查后，再由你确认安装。") },
        confirmButton = { TextButton(onClick = { confirm = false; download() }) { Text("确认下载") } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("取消") } })
}
