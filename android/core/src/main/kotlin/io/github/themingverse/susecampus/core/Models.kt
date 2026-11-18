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
    Failure.OUTSIDE -> "当前 Wi-Fi 不在已支持的校园网名单中，未提交账号密码。"
    Failure.PERMISSION -> "无法读取校园 Wi-Fi 信息，请允许精确位置权限并开启系统定位后重试。"
    Failure.AMBIGUOUS -> "存在多个 Wi-Fi，无法确定认证目标，请保留一个校园 Wi-Fi 连接后重试。"
    Failure.CHANGED -> "网络或设置已变化，本次操作已取消，请重新检查。"
    Failure.CREDENTIALS -> "账号或密码未通过认证，自动提交已暂停；请检查配置并明确保存后重试。"
    Failure.SERVICE -> "无法匹配学校最新上网服务，请刷新列表、重新选择并保存。"
    Failure.TEMPORARY -> "请求超时或校园网服务暂时不可用，本次操作已结束，请稍后手动重试。"
    Failure.MANUAL -> "认证入口、参数或认证方式无法确认，已停止提交；请使用学校官方登录页面。"
}
