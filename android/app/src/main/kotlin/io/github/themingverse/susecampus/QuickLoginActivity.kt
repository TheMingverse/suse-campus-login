package io.github.themingverse.susecampus

import android.Manifest
import android.app.Application
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.*
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.themingverse.susecampus.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

data class QuickUi(val text: String = "准备检查校园 Wi-Fi……", val busy: Boolean = true,
    val success: Boolean = false, val setup: Boolean = false, val permission: Boolean = false)

class QuickLoginViewModel(application: Application, private val savedState: SavedStateHandle) : AndroidViewModel(application) {
    private val graph = (application as CampusApplication).graph
    private val mutable = MutableStateFlow(QuickUi())
    val ui = mutable.asStateFlow()
    private var preparation: Job? = null
    private var observedId: Long? = savedState["taskId"]
    private var restored = savedState.get<Boolean>("attempted") == true
    init {
        viewModelScope.launch {
            graph.coordinator.state.collect { operation ->
                if (observedId == operation.id && operation.id != 0L) {
                    mutable.value = QuickUi(operation.status.text, operation.busy,
                        !operation.busy && operation.status.stage == Stage.ONLINE,
                        operation.status.stage == Stage.SETUP, operation.status.failure == Failure.PERMISSION)
                }
            }
        }
    }
    fun begin(permissionAllowed: Boolean, retry: Boolean = false) {
        if (preparation?.isActive == true) return
        if (!retry && savedState.get<Boolean>("attempted") == true) {
            val current = graph.coordinator.state.value
            if (restored && (observedId != current.id || current.id == 0L))
                mutable.value = QuickUi("上次任务已中断，点击重试开始新检查。", false)
            return
        }
        restored = false
        savedState["attempted"] = true
        graph.coordinator.markExplicit()
        preparation = viewModelScope.launch {
            mutable.value = QuickUi()
            val current = graph.coordinator.state.value
            if (current.busy && current.kind == OperationKind.LOGIN) { join(); return@launch }
            val config = try { graph.store.load() } catch (cancelled: CancellationException) { throw cancelled } catch (_: Exception) {
                mutable.value = QuickUi("保存的数据无法解密，请进入 App 重新配置。", false, setup = true)
                hint(QuickOutcome.SETUP)
                return@launch
            }
            if (!config.complete) {
                mutable.value = QuickUi("尚未完成账号配置，请先填写账号密码并选择学校上网服务。", false, setup = true)
                hint(QuickOutcome.SETUP)
                return@launch
            }
            if (!permissionAllowed) {
                mutable.value = QuickUi(safeMessage(Failure.PERMISSION), false, permission = true)
                hint(QuickOutcome.PERMISSION)
                return@launch
            }
            join()
        }
    }
    private suspend fun hint(code: QuickOutcome) {
        runCatching { graph.history.hint(code); QuickWidgets.updateAll(getApplication()) }
    }
    private suspend fun join() {
        val id = graph.coordinator.startOrJoin()
        observedId = id; savedState["taskId"] = id
        val operation = graph.coordinator.state.value
        if (id == 0L) mutable.value = QuickUi("认证页面不在前台，本次操作未启动。", false)
        else mutable.value = QuickUi(operation.status.text, operation.busy,
            !operation.busy && operation.status.stage == Stage.ONLINE,
            operation.status.stage == Stage.SETUP, operation.status.failure == Failure.PERMISSION)
    }
    fun cancel() {
        preparation?.cancel()
        viewModelScope.launch {
            graph.coordinator.cancel()
            mutable.value = QuickUi("本次操作已取消。", false)
        }
    }
}

class QuickLoginActivity : ComponentActivity() {
    private val model: QuickLoginViewModel by viewModels()
    private var permissionRequested = false
    private var pendingClick = false
    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) model.begin(hasPermission(), retry = true)
        else pendingClick = true
    }
    private fun hasPermission() = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    private fun requestPermission() {
        (application as CampusApplication).externalFlow()
        permissionRequested = true
        permissions.launch(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION, Manifest.permission.ACCESS_FINE_LOCATION))
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        permissionRequested = savedInstanceState?.getBoolean("permissionRequested") ?: false
        setContent {
            MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme(primary = Color(0xFF9DD5C7))
                else lightColorScheme(primary = Color(0xFF245B51))) {
                val ui by model.ui.collectAsStateWithLifecycle()
                LaunchedEffect(ui.success) { if (ui.success) { delay(1000); finish() } }
                LaunchedEffect(ui.permission) {
                    if (ui.permission && !hasPermission() && !permissionRequested) requestPermission()
                }
                Scaffold { padding ->
                    Column(Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(28.dp),
                        verticalArrangement = Arrangement.spacedBy(20.dp)) {
                        Text("SUSE 快捷登录", style = MaterialTheme.typography.headlineMedium)
                        Text(ui.text)
                        if (ui.busy) {
                            LinearProgressIndicator(Modifier.fillMaxWidth())
                            OutlinedButton(onClick = model::cancel) { Text("取消本次操作") }
                        } else if (!ui.success) {
                            Button(onClick = { model.begin(hasPermission(), retry = true) }) { Text("重新检查") }
                            if (ui.permission) {
                                TextButton(onClick = ::requestPermission) { Text("授予 Wi-Fi 识别权限") }
                                TextButton(onClick = {
                                    (application as CampusApplication).externalFlow()
                                    startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS))
                                }) { Text("打开系统定位设置") }
                                TextButton(onClick = {
                                    (application as CampusApplication).externalFlow()
                                    startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.fromParts("package", packageName, null)))
                                }) { Text("打开应用权限设置") }
                            }
                            TextButton(onClick = {
                                startActivity(Intent(this@QuickLoginActivity, MainActivity::class.java)
                                    .putExtra("configure", true).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
                                finish()
                            }) { Text(if (ui.setup) "进入首次配置" else "修改账号及运营商") }
                        }
                        TextButton(onClick = { model.cancel(); finish() }) { Text("关闭") }
                    }
                }
            }
        }
    }
    override fun onResume() {
        super.onResume()
        val clicked = pendingClick; pendingClick = false
        if (!model.ui.value.success) model.begin(hasPermission(), retry = clicked)
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent)
        // onNewIntent may arrive before the stopped Activity is visible again.
        // Wait for onResume so the foreground-only coordinator can accept the click.
        pendingClick = true
    }
    override fun onSaveInstanceState(outState: Bundle) { outState.putBoolean("permissionRequested", permissionRequested); super.onSaveInstanceState(outState) }
}
