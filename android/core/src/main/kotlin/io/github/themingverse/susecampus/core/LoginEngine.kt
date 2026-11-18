package io.github.themingverse.susecampus.core

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex

/** A finite operation, never a polling worker. One engine instance is owned by the ViewModel. */
class LoginEngine(private val store: ConfigurationStore, private val wifi: WifiAccess) {
    private val mutex = Mutex()
    private val mutableStatus = MutableStateFlow(LoginStatus())
    val status: StateFlow<LoginStatus> = mutableStatus.asStateFlow()
    private var active: Job? = null
    fun cancel() { active?.cancel() }
    fun resetCatalog() { mutableStatus.value = LoginStatus() }
    fun invalidateCatalog() {
        mutableStatus.update {
            if (it.stage in setOf(Stage.ONLINE, Stage.CATALOG)) LoginStatus(Stage.IDLE, "Wi-Fi 连接已变化，请重新检查。")
            else it.copy(services = emptyList())
        }
    }

    suspend fun run(automatic: Boolean = false, refreshOnly: Boolean = false): LoginStatus {
        if (!mutex.tryLock()) return LoginStatus(Stage.BUSY, "已有操作正在进行")
        active = currentCoroutineContext().job
        var lease: WifiLease? = null
        var config: Configuration? = null
        var submitted = false
        fun emit(stage: Stage, text: String, services: List<ServiceOption> = mutableStatus.value.services, failure: Failure? = null) {
            mutableStatus.value = LoginStatus(stage, text, services, failure)
        }
        try {
            withTimeout(75000) {
                config = store.load()
                val settings = config!!
                if (automatic && (!settings.autoLogin || !settings.complete)) {
                    emit(Stage.SETUP, "请完成配置，或点击按钮手动检查。", emptyList())
                    return@withTimeout
                }
                emit(Stage.CHECKING, "正在检查校园 Wi-Fi…", emptyList())
                val connection = wifi.acquire().also { lease = it }
                coroutineScope {
                    val operation = currentCoroutineContext().job
                    val watcher = launch {
                        connection.invalidated.first { it }
                        operation.cancel(NetworkChanged())
                    }
                    try {
                        connection.guard()
                        val probe = NetworkProbe(connection.transport, connection::guard)
                        val result = probe.check()
                        if (result.state == ProbeState.ONLINE) {
                            emit(Stage.ONLINE, if (refreshOnly) "当前已联网，请在下次需要认证时刷新上网服务。" else "校园 Wi-Fi 已联网。")
                            return@coroutineScope
                        }
                        if (result.state == ProbeState.UNKNOWN) {
                            emit(Stage.FAILED, "无法确认联网状态，请稍后重试。")
                            return@coroutineScope
                        }
                        if (result.state == ProbeState.UNSUPPORTED) throw PortalException(Failure.MANUAL)
                        if (!refreshOnly && (settings.block == Block.CREDENTIALS || (automatic && settings.block != null))) {
                            emit(Stage.BLOCKED, if (settings.block == Block.CREDENTIALS) safeMessage(Failure.CREDENTIALS)
                                else "请在学校登录页面完成认证后重新检查。",
                                failure = if (settings.block == Block.CREDENTIALS) Failure.CREDENTIALS else Failure.MANUAL)
                            return@coroutineScope
                        }
                        val url = result.portal ?: throw PortalException(Failure.MANUAL)
                        emit(Stage.PREPARING, "正在获取上网服务…")
                        val client = PortalClient(connection.transport, connection::guard)
                        val prepared = client.prepare(url)
                        connection.guard()
                        if (refreshOnly) {
                            emit(Stage.CATALOG, "上网服务已更新，请选择并保存。", prepared.services)
                            return@coroutineScope
                        }
                        if (!settings.complete) {
                            emit(Stage.SETUP, "请填写账号、密码并选择上网服务。", prepared.services)
                            return@coroutineScope
                        }
                        emit(Stage.PREPARING, "已获取上网服务。", prepared.services)
                        Protocol.requireService(prepared.services, settings.service)
                        // Validate encryption/auth mode before writing the crash-safety block.
                        Protocol.loginFields(settings, Protocol.connectionQuery(url), prepared.info)
                        connection.guard(); currentCoroutineContext().ensureActive()
                        store.block(settings.revision, Block.UNVERIFIED)
                        connection.guard(); currentCoroutineContext().ensureActive()
                        submitted = true
                        emit(Stage.AUTHENTICATING, "正在登录…")
                        client.authenticate(url, settings, prepared)
                        emit(Stage.VERIFYING, "正在检查联网状态…")
                        val verified = probe.check()
                        connection.guard()
                        if (verified.state == ProbeState.ONLINE) {
                            store.block(settings.revision, null)
                            emit(Stage.ONLINE, "登录成功。")
                        } else {
                            emit(Stage.BLOCKED, if (settings.service == "校园网")
                                "校内网认证已通过，暂未确认外网连接。"
                                else "认证已通过，暂未确认能否上网。")
                        }
                    } finally { watcher.cancel() }
                }
            }
        } catch (_: NetworkChanged) {
            emit(Stage.CANCELLED, safeMessage(Failure.CHANGED), emptyList())
        } catch (_: TimeoutCancellationException) {
            emit(Stage.FAILED, safeMessage(Failure.TEMPORARY))
        } catch (error: CancellationException) {
            emit(Stage.CANCELLED, "本次操作已取消。", emptyList())
            throw error
        } catch (error: PortalException) {
            config?.let { settings ->
                val block = when (error.kind) {
                    Failure.CREDENTIALS -> Block.CREDENTIALS
                    Failure.MANUAL, Failure.SERVICE -> Block.MANUAL
                    else -> if (submitted) Block.UNVERIFIED else null
                }
                if (!refreshOnly && block != null) {
                    // The pre-submit UNVERIFIED marker already protects failed login writes.
                    // A storage failure or a newer revision must never escape the UI task.
                    runCatching { store.block(settings.revision, block) }
                }
            }
            emit(Stage.FAILED, safeMessage(error.kind), if (error.kind == Failure.CHANGED) emptyList() else mutableStatus.value.services, error.kind)
        } catch (_: Exception) {
            emit(Stage.FAILED, "无法读取配置或完成本次操作，请重新配置或稍后重试。", emptyList())
        } finally {
            try { lease?.close() } finally { active = null; mutex.unlock() }
        }
        return mutableStatus.value
    }
    private class NetworkChanged : CancellationException("Network changed")
}
