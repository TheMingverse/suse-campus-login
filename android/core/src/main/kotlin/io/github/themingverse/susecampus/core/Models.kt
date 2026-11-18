package io.github.themingverse.susecampus.core

import kotlinx.coroutines.flow.StateFlow

enum class Failure { MANUAL, CREDENTIALS, TEMPORARY, SERVICE, NO_WIFI, OUTSIDE, PERMISSION, AMBIGUOUS, CHANGED }
class PortalException(val kind: Failure) : Exception(kind.name)
enum class Block { CREDENTIALS, MANUAL, UNVERIFIED }

class Configuration(
    val username: String = "",
    val password: String = "",
    val service: String = "",
    val autoLogin: Boolean = true,
    val block: Block? = null,
    val revision: Long = 0,
) {
    val complete get() = username.isNotBlank() && password.isNotEmpty() && service.isNotBlank()
    fun withBlock(value: Block?) = Configuration(username, password, service, autoLogin, value, revision)
    override fun toString() = "Configuration([redacted])"
}

interface ConfigurationStore {
    suspend fun load(): Configuration
    suspend fun save(configuration: Configuration)
    /** Compare-and-set: stale tasks cannot overwrite a newly saved configuration. */
    suspend fun block(revision: Long, value: Block?)
}

data class ServiceOption(val name: String, val available: Boolean, val reason: String = "")
enum class Stage { IDLE, CHECKING, PREPARING, AUTHENTICATING, VERIFYING, ONLINE, CATALOG, SETUP, BLOCKED, FAILED, CANCELLED, BUSY }
data class LoginStatus(val stage: Stage = Stage.IDLE, val text: String = "点击按钮检查校园 Wi-Fi", val services: List<ServiceOption> = emptyList(), val failure: Failure? = null)
enum class ProbeState { ONLINE, PORTAL, UNSUPPORTED, UNKNOWN }
class ProbeResult(val state: ProbeState, val portal: String? = null) {
    override fun toString() = "ProbeResult($state)"
}

class HttpRequest(val url: String, val method: String = "GET", val body: ByteArray = byteArrayOf(), val probe: Boolean = false) {
    override fun toString() = "HttpRequest([redacted])"
}
class HttpReply(val code: Int, val url: String, val headers: Map<String, String>, val body: ByteArray) {
    override fun toString() = "HttpReply($code, [redacted])"
    fun header(name: String) = headers.entries.firstOrNull { it.key.equals(name, true) }?.value.orEmpty()
}
interface HttpTransport : AutoCloseable { suspend fun execute(request: HttpRequest): HttpReply }
interface WifiLease : AutoCloseable {
    val transport: HttpTransport
    val invalidated: StateFlow<Boolean>
    fun guard()
}
interface WifiAccess { suspend fun acquire(): WifiLease }

fun safeMessage(kind: Failure): String = when (kind) {
    Failure.NO_WIFI -> "未连接 Wi-Fi，请先连接 SUSE 或 SUSE_Hostel。"
    Failure.OUTSIDE -> "请连接 SUSE 或 SUSE_Hostel 校园 Wi-Fi。"
    Failure.PERMISSION -> "请允许精确位置权限并开启系统定位后重试。"
    Failure.AMBIGUOUS -> "请只保留一个校园 Wi-Fi 连接后重试。"
    Failure.CHANGED -> "网络或设置已变化，请重新检查。"
    Failure.CREDENTIALS -> "账号或密码错误，请修改并保存后重试。"
    Failure.SERVICE -> "请刷新上网服务，重新选择并保存。"
    Failure.TEMPORARY -> "连接失败，请稍后重试。"
    Failure.MANUAL -> "无法识别认证页面，请使用学校登录页面。"
}
