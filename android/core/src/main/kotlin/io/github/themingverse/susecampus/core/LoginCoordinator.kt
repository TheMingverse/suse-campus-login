package io.github.themingverse.susecampus.core

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

enum class OperationKind { LOGIN, REFRESH }
data class OperationState(val id: Long = 0, val kind: OperationKind = OperationKind.LOGIN,
    val busy: Boolean = false, val status: LoginStatus = LoginStatus())

/** One application instance, one engine, one structured task. No queued credential submissions. */
class LoginCoordinator(
    val store: ConfigurationStore,
    val engine: LoginEngine,
    private val scope: CoroutineScope,
    private val allowed: () -> Boolean = { true },
    private val record: suspend (OperationState) -> Unit = {},
) {
    private val gate = Mutex()
    private var active: Job? = null
    private var sequence = 0L
    private val mutable = MutableStateFlow(OperationState())
    val state = mutable.asStateFlow()
    private var autoConsumed = false
    fun consumeAutomatic(): Boolean {
        if (autoConsumed) return false
        autoConsumed = true
        return true
    }
    fun markExplicit() { autoConsumed = true }
    fun newForegroundSession() { autoConsumed = false }
    fun invalidateCatalog() {
        engine.invalidateCatalog()
        if (!mutable.value.busy) mutable.value = mutable.value.copy(status = engine.status.value)
    }

    suspend fun startOrJoin(automatic: Boolean = false, refreshOnly: Boolean = false): Long = gate.withLock {
        if (!automatic) markExplicit()
        if (active?.isActive == true) {
            if (mutable.value.kind == OperationKind.LOGIN || refreshOnly || automatic) return@withLock mutable.value.id
            active?.cancelAndJoin() // An explicit login may replace a read-only operation, never another login.
        }
        if (!allowed()) return@withLock 0L
        val id = ++sequence
        val kind = if (refreshOnly) OperationKind.REFRESH else OperationKind.LOGIN
        engine.resetCatalog()
        mutable.value = OperationState(id, kind, true, LoginStatus(Stage.CHECKING, "正在准备检查校园 Wi-Fi……"))
        val job = scope.launch(start = CoroutineStart.LAZY) {
            var outcome: LoginStatus? = null
            try {
                if (kind == OperationKind.LOGIN) record(mutable.value)
                coroutineScope {
                    val observer = launch(start = CoroutineStart.UNDISPATCHED) {
                        engine.status.collect { status -> mutable.value = OperationState(id, kind, true, status) }
                    }
                    try { outcome = engine.run(automatic, refreshOnly) } finally { observer.cancelAndJoin() }
                }
            } catch (_: CancellationException) {
                outcome = LoginStatus(Stage.CANCELLED, "本次操作已取消。")
                // Engine has released its lease before the terminal record is published.
            } catch (_: Exception) {
                outcome = LoginStatus(Stage.FAILED, "本次操作未完成，请稍后重试。")
            } finally {
                withContext(NonCancellable) {
                    val status = outcome ?: LoginStatus(Stage.CANCELLED, "本次操作已取消。")
                    val terminal = if (status.stage in setOf(Stage.IDLE, Stage.CHECKING, Stage.PREPARING, Stage.AUTHENTICATING, Stage.VERIFYING))
                        LoginStatus(Stage.CANCELLED, "本次操作已取消。") else status
                    val result = OperationState(id, kind, false, terminal)
                    val published = if (kind == OperationKind.LOGIN) runCatching { record(result) }.isSuccess else true
                    mutable.value = if (published) result else result.copy(status = LoginStatus(Stage.FAILED,
                        "认证流程已结束，但快捷结果未能保存；请在 App 中检查连接状态。"))
                }
            }
        }
        active = job
        job.start()
        id
    }

    suspend fun cancel() = gate.withLock {
        active?.cancelAndJoin()
        // A job cancelled before its first dispatch never enters its try/finally block.
        if (mutable.value.busy) {
            val result = mutable.value.copy(busy = false, status = LoginStatus(Stage.CANCELLED, "本次操作已取消。"))
            if (result.kind == OperationKind.LOGIN) runCatching { record(result) }
            mutable.value = result
        }
    }
    suspend fun saveConfiguration(config: Configuration) = gate.withLock {
        active?.cancelAndJoin()
        store.save(config)
        engine.resetCatalog()
        mutable.value = OperationState()
    }
}
