package io.github.themingverse.susecampus

import android.Manifest
import android.content.pm.PackageManager
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.themingverse.susecampus.core.*
import io.github.themingverse.susecampus.tutorial.TutorialController
import io.github.themingverse.susecampus.tutorial.TutorialDialog

@Composable
fun CampusScreen(model: CampusViewModel, requestPermission: (Boolean) -> Unit, openLocationSettings: () -> Unit, openAppSettings: () -> Unit,
                 openUpdates: () -> Unit = {},
                 updateChecker: io.github.themingverse.susecampus.update.ForegroundUpdateChecker? = null,
                 openPromptedUpdate: () -> Unit = openUpdates,
                 tutorial: TutorialController? = null, openTutorialProject: () -> Unit = {}) {
    val ui by model.ui.collectAsStateWithLifecycle()
    val status by model.status.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val tutorialState = tutorial?.state?.collectAsStateWithLifecycle()?.value
    fun action(refresh: Boolean) {
        if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) requestPermission(refresh)
        else if (refresh) model.refresh() else model.check()
    }
    CampusContent(ui, status, onCheck = { action(false) }, onRefresh = { action(true) }, onCancel = model::cancel,
        onEdit = model::edit, onDismissEditor = model::dismissEditor, onSave = model::save,
        onPermission = { requestPermission(ui.editing) }, onLocationSettings = openLocationSettings, onAppSettings = openAppSettings,
        onUpdates = openUpdates, onTutorial = { tutorial?.open() })
    if (!ui.loading && tutorial != null && tutorialState?.visible == true) {
        TutorialDialog(tutorialState, tutorial, openTutorialProject)
    }
    updateChecker?.let { checker ->
        io.github.themingverse.susecampus.update.HomeUpdateNotice(checker,
            blocked = ui.loading || ui.busy || ui.saving || ui.editing || tutorialState?.blocksUpdatePrompt == true,
            viewUpdate = openPromptedUpdate)
    }
}

@Composable
fun CampusContent(
    ui: CampusUiState, status: LoginStatus,
    onCheck: () -> Unit = {}, onRefresh: () -> Unit = {}, onCancel: () -> Unit = {},
    onEdit: () -> Unit = {}, onDismissEditor: () -> Unit = {},
    onSave: (String, String, String, Boolean) -> Unit = { _, _, _, _ -> },
    onPermission: () -> Unit = {}, onLocationSettings: () -> Unit = {}, onAppSettings: () -> Unit = {},
    onUpdates: () -> Unit = {}, onTutorial: () -> Unit = {},
) {
    Scaffold(topBar = {
        Surface(tonalElevation = 1.dp) {
            Column(Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.statusBars)
                .padding(horizontal = 20.dp, vertical = 8.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("SUSE 校园网", Modifier.weight(1f), style = MaterialTheme.typography.headlineSmall)
                    OutlinedButton(onClick = onTutorial) { Text("使用教程") }
                }
            }
        }
    }) { padding ->
        BoxWithConstraints(Modifier.fillMaxSize().padding(padding)) {
            val wide = maxWidth >= 840.dp
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(if (wide) 40.dp else 24.dp),
                verticalArrangement = Arrangement.spacedBy(24.dp)) {
                if (ui.loading) CircularProgressIndicator()
                else if (wide) {
                    Row(horizontalArrangement = Arrangement.spacedBy(28.dp)) {
                        Column(Modifier.weight(1f)) { StatusCard(ui, status, onCheck, onCancel, onEdit, onPermission, onLocationSettings, onAppSettings) }
                        Column(Modifier.weight(1f)) {
                            if (ui.editing) ConfigurationCard(ui, status.services, onRefresh, onSave, onDismissEditor)
                            else HelpCard(ui)
                        }
                    }
                } else {
                    StatusCard(ui, status, onCheck, onCancel, onEdit, onPermission, onLocationSettings, onAppSettings)
                    if (ui.editing) ConfigurationCard(ui, status.services, onRefresh, onSave, onDismissEditor) else HelpCard(ui)
                }
                if (ui.notice.isNotEmpty()) Text(ui.notice, color = MaterialTheme.colorScheme.primary)
                if (!ui.loading) QuickEntryControls()
                OutlinedButton(onClick = onUpdates, modifier = Modifier.fillMaxWidth()) { Text("更新设置与关于") }
            }
        }
    }
}

@Composable
private fun StatusCard(ui: CampusUiState, status: LoginStatus, onCheck: () -> Unit, onCancel: () -> Unit,
    onEdit: () -> Unit, onPermission: () -> Unit, onLocationSettings: () -> Unit, onAppSettings: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(if (status.stage == Stage.ONLINE) "校园 Wi-Fi 已联网" else "校园 Wi-Fi 状态", style = MaterialTheme.typography.titleLarge)
            Text(ui.networkText, color = MaterialTheme.colorScheme.primary)
            Text(status.text)
            if (ui.busy) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                OutlinedButton(onClick = onCancel) { Text("取消本次操作") }
            } else {
                Button(onClick = onCheck, enabled = !ui.saving, modifier = Modifier.fillMaxWidth()) { Text("立即检查并登录") }
                if (!ui.editing) OutlinedButton(onClick = onEdit, enabled = !ui.saving) { Text("修改账号及运营商") }
            }
            if (status.stage == Stage.FAILED && status.text == safeMessage(Failure.PERMISSION)) {
                TextButton(onClick = onPermission) { Text("授予 Wi-Fi 识别权限") }
                TextButton(onClick = onAppSettings) { Text("打开应用权限设置") }
                TextButton(onClick = onLocationSettings) { Text("打开系统定位设置") }
            }
        }
    }
}

@Composable
private fun HelpCard(ui: CampusUiState) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("已保存的配置", style = MaterialTheme.typography.titleMedium)
            Text("上网服务：${ui.service.ifEmpty { "待选择" }}")
            Text(if (ui.autoLogin) "打开 App 时自动检查并登录。" else "自动登录已关闭。")
        }
    }
}

@Composable
private fun ConfigurationCard(ui: CampusUiState, services: List<ServiceOption>, onRefresh: () -> Unit,
    onSave: (String, String, String, Boolean) -> Unit, onDismiss: () -> Unit) {
    // Password deliberately uses remember, never rememberSaveable / SavedStateHandle.
    var username by remember(ui.username) { mutableStateOf(ui.username) }
    var password by remember { mutableStateOf("") }
    var service by remember(ui.service) { mutableStateOf(ui.service) }
    var automatic by remember(ui.autoLogin) { mutableStateOf(ui.autoLogin) }
    var expanded by remember { mutableStateOf(false) }
    LaunchedEffect(services) {
        if (service != ui.service && services.none { it.name == service && it.available }) service = ui.service
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(if (ui.hasPassword) "账号与设置" else "首次配置", style = MaterialTheme.typography.titleLarge)
            OutlinedTextField(username, { username = it }, label = { Text("校园网账号") }, singleLine = true,
                enabled = !ui.saving && !ui.busy, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(password, { password = it }, label = { Text("校园网密码") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                supportingText = { Text(if (ui.hasPassword) "留空保留已保存密码" else "仅加密保存在此设备") },
                enabled = !ui.saving && !ui.busy, modifier = Modifier.fillMaxWidth())
            Box {
                OutlinedButton(onClick = { expanded = true }, enabled = !ui.busy && !ui.saving && services.any { it.available },
                    modifier = Modifier.fillMaxWidth()) { Text("上网服务：${service.ifEmpty { "请刷新后选择" }}") }
                DropdownMenu(expanded, { expanded = false }) {
                    services.forEach { option ->
                        DropdownMenuItem(text = { Text(if (option.available) option.name else "${option.name} · ${option.reason}") },
                            onClick = { service = option.name; expanded = false }, enabled = option.available)
                    }
                }
            }
            OutlinedButton(onClick = onRefresh, enabled = !ui.busy && !ui.saving) { Text("只读刷新上网服务") }
            if (services.isEmpty()) Text("请先连接 SUSE 或 SUSE_Hostel 再刷新；暂时无法获取时可先保存账号草稿。",
                style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Switch(automatic, { automatic = it }, enabled = !ui.saving)
                Text("打开 App 后自动检查并按需登录", modifier = Modifier.weight(1f))
            }
            Button(onClick = { onSave(username, password, service, automatic); password = "" },
                enabled = !ui.saving && username.isNotBlank() && (password.isNotEmpty() || ui.hasPassword), modifier = Modifier.fillMaxWidth()) {
                Text(if (ui.saving) "正在安全保存……" else if (service.isEmpty()) "保存加密草稿" else "保存设置")
            }
            if (ui.hasPassword && ui.service.isNotEmpty()) TextButton(onClick = onDismiss, enabled = !ui.saving) { Text("返回主页") }
        }
    }
}
