package io.github.themingverse.susecampus

import android.content.Context
import io.github.themingverse.susecampus.core.*
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

enum class QuickOutcome(val label: String) {
    NONE("尚未检查，点击登录"), REQUESTED("已发起检查"), ONLINE("已联网"), FAILED("检查未完成"),
    CANCELLED("已取消"), INTERRUPTED("任务已中断"), SETUP("请先完成账号配置"),
    NO_WIFI("未连接 Wi-Fi"), OUTSIDE("非校园 Wi-Fi"), PERMISSION("需要 Wi-Fi 识别权限"),
    CREDENTIALS("请检查账号密码并保存"), SERVICE("请重新选择上网服务"),
    MANUAL("需要人工处理"), UNVERIFIED("认证已接受，联网未确认"), CHANGED("网络已变化"), STALE("设置已更新，请重新检查")
}
data class QuickResult(val outcome: QuickOutcome = QuickOutcome.NONE, val time: Long = 0, val task: Long = 0) {
    fun description(): String = if (time == 0L) outcome.label else
        "上次检查：${SimpleDateFormat("MM-dd HH:mm", Locale.CHINA).format(Date(time))} · ${outcome.label}"
}

/** No credentials, network identities, server messages or arbitrary strings are stored here. */
class QuickResultStore(context: Context, private val blob: ConfigurationBlob = AtomicConfigurationBlob(File(context.noBackupFilesDir, "quick-result.json"))) {
    private val mutable = MutableStateFlow(read())
    val state = mutable.asStateFlow()
    private fun read(): QuickResult = runCatching {
        val bytes = blob.read() ?: return@runCatching QuickResult()
        require(bytes.size <= 4096)
        val value = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        val code = QuickOutcome.valueOf(value.getValue("code").jsonPrimitive.content)
        QuickResult(if (code == QuickOutcome.REQUESTED) QuickOutcome.INTERRUPTED else code,
            value.getValue("time").jsonPrimitive.long, value.getValue("task").jsonPrimitive.long)
    }.getOrDefault(QuickResult())
    private suspend fun write(result: QuickResult) = withContext(Dispatchers.IO) {
        val value = buildJsonObject { put("code", result.outcome.name); put("time", result.time); put("task", result.task) }
        blob.write(value.toString().toByteArray())
        mutable.value = result
    }
    suspend fun invalidate() = write(QuickResult(QuickOutcome.STALE, System.currentTimeMillis()))
    suspend fun hint(code: QuickOutcome) = write(QuickResult(code, System.currentTimeMillis()))
    suspend fun record(operation: OperationState) {
        val status = operation.status
        val code = if (operation.busy) QuickOutcome.REQUESTED else when (status.failure) {
            Failure.NO_WIFI -> QuickOutcome.NO_WIFI
            Failure.OUTSIDE -> QuickOutcome.OUTSIDE
            Failure.PERMISSION -> QuickOutcome.PERMISSION
            Failure.CREDENTIALS -> QuickOutcome.CREDENTIALS
            Failure.SERVICE -> QuickOutcome.SERVICE
            Failure.CHANGED -> QuickOutcome.CHANGED
            Failure.MANUAL -> QuickOutcome.MANUAL
            else -> when (status.stage) {
                Stage.ONLINE -> QuickOutcome.ONLINE
                Stage.SETUP -> QuickOutcome.SETUP
                Stage.CANCELLED -> QuickOutcome.CANCELLED
                Stage.BLOCKED -> QuickOutcome.UNVERIFIED
                else -> QuickOutcome.FAILED
            }
        }
        write(QuickResult(code, System.currentTimeMillis(), operation.id))
    }
}
