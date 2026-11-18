package io.github.themingverse.susecampus

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.UUID

enum class WidgetSize { SMALL, WIDE }
enum class PinPhase { INITIAL, WAITING, SUCCESS, MANUAL }
data class PinState(val phase: PinPhase = PinPhase.INITIAL, val size: WidgetSize = WidgetSize.SMALL, val token: String? = null) {
    val message get() = when (phase) {
        PinPhase.INITIAL -> ""
        PinPhase.WAITING -> "请在系统弹窗中确认添加。"
        PinPhase.SUCCESS -> "已添加到桌面。"
        PinPhase.MANUAL -> "请按下方步骤手动添加。"
    }
}
interface WidgetPinGateway {
    fun supported(): Boolean
    fun request(size: WidgetSize, token: String): Boolean
    fun cancel(token: String)
    fun home(): Boolean
}
interface WidgetPinPersistence {
    fun read(): PinState
    fun write(state: PinState)
}

/** No authentication dependencies. An accepted request is never treated as confirmed success. */
class WidgetPinController(private val gateway: WidgetPinGateway, private val persistence: WidgetPinPersistence) {
    private val mutable = MutableStateFlow(runCatching { persistence.read() }.getOrDefault(PinState()))
    val state = mutable.asStateFlow()
    private fun publish(value: PinState) { persistence.write(value); mutable.value = value }
    @Synchronized fun request(size: WidgetSize, retry: Boolean = false) {
        if (mutable.value.phase == PinPhase.WAITING && !retry) return
        mutable.value.token?.let { runCatching { gateway.cancel(it) } }
        val token = UUID.randomUUID().toString()
        try {
            if (!gateway.supported()) { publish(PinState(PinPhase.MANUAL, size)); return }
            // Save before dispatch: callbacks may arrive immediately or restart our process.
            publish(PinState(PinPhase.WAITING, size, token))
            val accepted = gateway.request(size, token)
            if (!accepted && mutable.value.phase == PinPhase.WAITING && mutable.value.token == token) {
                gateway.cancel(token); publish(PinState(PinPhase.MANUAL, size))
            }
        } catch (_: Exception) {
            runCatching { gateway.cancel(token) }
            runCatching { publish(PinState(PinPhase.MANUAL, size)) }.onFailure { mutable.value = PinState(PinPhase.MANUAL, size) }
        }
    }
    @Synchronized fun confirmed(token: String) {
        if (mutable.value.phase == PinPhase.WAITING && mutable.value.token == token) {
            val result = mutable.value.copy(phase = PinPhase.SUCCESS, token = null)
            runCatching { publish(result) }.onFailure { mutable.value = result }
            runCatching { gateway.cancel(token) }
        }
    }
    fun retry(size: WidgetSize = mutable.value.size) = request(size, retry = true)
    fun returnHome() = runCatching { gateway.home() }.getOrDefault(false)
}
