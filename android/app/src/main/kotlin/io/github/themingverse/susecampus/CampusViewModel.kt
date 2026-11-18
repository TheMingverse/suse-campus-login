package io.github.themingverse.susecampus

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.themingverse.susecampus.core.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

data class CampusUiState(
    val loading: Boolean = true,
    val editing: Boolean = true,
    val username: String = "",
    val service: String = "",
    val autoLogin: Boolean = true,
    val hasPassword: Boolean = false,
    val busy: Boolean = false,
    val notice: String = "",
    val saving: Boolean = false,
    val networkText: String = "Wi-Fi 状态待检查",
)

class CampusViewModel(application: Application) : AndroidViewModel(application) {
    private val graph = (application as CampusApplication).graph
    private val store = graph.store
    private val engine = graph.engine
    val status = graph.coordinator.state.map { it.status }.stateIn(viewModelScope, SharingStarted.Eagerly, LoginStatus())
    private val mutableUi = MutableStateFlow(CampusUiState())
    val ui = mutableUi.asStateFlow()
    private var saved = Configuration()
    private var visible = false
    private var forceEditor = false
    private var overview: WifiOverview? = null

    init {
        viewModelScope.launch { graph.coordinator.state.collect { state -> mutableUi.update { it.copy(busy = state.busy) } } }
        viewModelScope.launch {
            try {
                saved = store.load()
                mutableUi.value = CampusUiState(false, forceEditor || !saved.complete, saved.username, saved.service, saved.autoLogin,
                    saved.password.isNotEmpty(), busy = graph.coordinator.state.value.busy, networkText = ui.value.networkText)
            } catch (_: Exception) {
                mutableUi.value = CampusUiState(loading = false, notice = "保存的数据无法解密，请重新填写配置并保存。", networkText = ui.value.networkText)
            }
            maybeAutomatic()
        }
    }

    fun foreground() {
        if (overview == null) {
            overview = WifiOverview(getApplication()) { text, changed ->
                mutableUi.update { it.copy(networkText = text) }
                if (changed) graph.coordinator.invalidateCatalog()
            }.also { runCatching { it.start() } }
        }
        visible = true; maybeAutomatic()
    }
    fun background() { visible = false; overview?.close(); overview = null }
    override fun onCleared() { overview?.close(); super.onCleared() }
    fun externalFlow() { getApplication<CampusApplication>().externalFlow() }
    private fun maybeAutomatic() {
        if (visible && !ui.value.loading && graph.coordinator.consumeAutomatic()) {
            if (saved.complete && saved.autoLogin && !ui.value.editing) start(automatic = true)
        }
    }
    fun edit() { forceEditor = true; cancel(); mutableUi.update { it.copy(editing = true, notice = "") } }
    fun dismissEditor() { mutableUi.update { it.copy(editing = !saved.complete, notice = "") } }
    fun cancel() { viewModelScope.launch { graph.coordinator.cancel() } }
    fun check() = start()
    fun refresh() = start(refreshOnly = true)

    private fun start(automatic: Boolean = false, refreshOnly: Boolean = false) {
        if (ui.value.saving) return
        viewModelScope.launch {
            mutableUi.update { it.copy(notice = "") }
            graph.coordinator.startOrJoin(automatic, refreshOnly)
        }
    }

    fun save(username: String, passwordInput: String, service: String, autoLogin: Boolean) {
        if (ui.value.saving) return
        mutableUi.update { it.copy(saving = true) }
        viewModelScope.launch {
            try {
                val password = passwordInput.ifEmpty { saved.password }
                require(username.isNotBlank() && password.isNotEmpty())
                if (service.isNotEmpty() && service != saved.service) Protocol.requireService(status.value.services, service)
                graph.save(Configuration(username, password, service, autoLogin))
                saved = store.load()
                engine.resetCatalog()
                mutableUi.value = CampusUiState(false, !saved.complete, saved.username, saved.service, saved.autoLogin,
                    saved.password.isNotEmpty(), notice = if (saved.complete) "配置已保存，点击“立即检查并登录”开始。" else "账号草稿已加密保存；请连接校园 Wi-Fi，刷新并选择上网服务。",
                    networkText = ui.value.networkText)
            } catch (_: Exception) {
                mutableUi.update { it.copy(notice = "保存失败。请检查账号密码及服务选择，原配置仍然保留。") }
            } finally { mutableUi.update { it.copy(saving = false) } }
        }
    }
}

/** Kept independent of Android so rotation and permission-return decisions can be unit tested. */
class ForegroundSession {
    private var foreground = false
    private var consumed = false
    private var external = false
    fun externalFlow() { external = true }
    fun foreground() { foreground = true; external = false }
    fun background() { foreground = false; if (!external) consumed = false }
    fun consume(): Boolean {
        if (!foreground || consumed) return false
        consumed = true
        return true
    }
}
