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
            Text("当前版本：${state.current.name}")
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("更新渠道", style = MaterialTheme.typography.titleLarge)
                UpdateChannel.entries.forEach { channel ->
                    Row {
                        RadioButton(selected == channel, { selected = channel }, enabled = !state.busy)
                        TextButton(onClick = { selected = channel }, enabled = !state.busy) { Text(channel.label) }
                    }
                }
                if (settingsChanged) Text("已保存渠道：${state.settings.channel.label}")
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    Text("打开 App 时检查更新", modifier = Modifier.weight(1f))
                    Switch(checkOnOpen, { checkOnOpen = it }, enabled = !state.busy)
                }
                OutlinedTextField(repository, { repository = it }, label = { Text("Gitee 镜像仓库（账号/仓库，可留空）") },
                    singleLine = true, enabled = !state.busy, modifier = Modifier.fillMaxWidth())
                if (selected != UpdateChannel.GITHUB && repository.isBlank()) Text("Gitee 尚未配置。")
                OutlinedButton(onClick = { save(selected, repository, checkOnOpen) }, enabled = settingsChanged && !state.busy) { Text("保存更新设置") }
            } }
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (state.available) state.actualSource?.let { Text("本次连接来源：${it.label}") }
                if (state.message.isNotBlank()) Text(state.message,
                    color = if (state.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
                if (state.busy && !state.downloading) LinearProgressIndicator(Modifier.fillMaxWidth())
                Button(onClick = check, enabled = !state.busy && !settingsChanged) { Text("检查更新") }
                if (settingsChanged) Text("请先保存渠道设置，再检查更新。")
                if (state.available) state.release?.let { release ->
                    Text("新版本：${release.versionName} · ${updateSize(release.size)}")
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
                    Button(onClick = install, enabled = !state.busy && !settingsChanged) { Text("安装更新") }
                }
                if (state.permissionNeeded) OutlinedButton(onClick = permission, enabled = !state.busy) { Text("打开安装授权设置") }
            } }
        }
    }
    if (confirm && state.release != null && !settingsChanged) AlertDialog(onDismissRequest = { confirm = false },
        title = { Text("确认下载更新") }, text = { Text("下载 ${state.release.versionName}，大小 ${updateSize(state.release.size)}。") },
        confirmButton = { TextButton(onClick = { confirm = false; download() }) { Text("确认下载") } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("取消") } })
}
