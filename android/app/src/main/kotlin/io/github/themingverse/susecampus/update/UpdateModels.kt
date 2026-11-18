package io.github.themingverse.susecampus.update

import kotlinx.serialization.json.*
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

enum class UpdateChannel(val label: String) { AUTO("自动选择"), GITEE("Gitee 国内镜像"), GITHUB("GitHub 官方渠道") }
enum class UpdateError { NETWORK, SERVICE, NOT_CONFIGURED, SECURITY, DOWNGRADE, STORAGE, INSTALL }
class UpdateException(val kind: UpdateError, override val message: String) : Exception(message)
fun security(condition: Boolean, message: String) { if (!condition) throw UpdateException(UpdateError.SECURITY, message) }

data class UpdateTrust(val applicationId: String, val githubRepository: String, val certificateSha256: String)
data class InstalledVersion(val name: String, val code: Long)
data class UpdateSettings(val channel: UpdateChannel = UpdateChannel.GITHUB, val giteeRepository: String = "",
                          val checkOnOpen: Boolean = true)
data class ReleaseInfo(
    val applicationId: String, val versionName: String, val versionCode: Long, val tag: String,
    val releaseNotes: String, val fileName: String, val size: Long, val sha256: String,
    val downloadUrl: HttpUrl, val channel: UpdateChannel, val minSdk: Int,
) {
    fun sameArtifact(other: ReleaseInfo) = applicationId == other.applicationId && versionCode == other.versionCode &&
        versionName == other.versionName && tag == other.tag && fileName == other.fileName && size == other.size && sha256 == other.sha256
}
enum class VersionDecision { AVAILABLE, CURRENT }
object UpdateChecker {
    fun compare(installed: InstalledVersion, release: ReleaseInfo): VersionDecision {
        if (release.versionCode < installed.code) throw UpdateException(UpdateError.DOWNGRADE, "更新渠道的版本较旧，暂时无法更新。")
        if (release.versionCode == installed.code) {
            security(release.versionName == installed.name, "相同版本编号对应不同版本号，已停止更新。")
            return VersionDecision.CURRENT
        }
        return VersionDecision.AVAILABLE
    }
}

object UpdateFormat {
    const val MAX_APK_BYTES = 250L * 1024 * 1024
    val versionPattern = Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)")
    fun repository(input: String): String {
        val value = input.trim().removeSuffix("/")
        val repository = if (value.startsWith("https://gitee.com/")) value.removePrefix("https://gitee.com/") else value
        security(repository.isEmpty() || Regex("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+").matches(repository) &&
            repository.split('/').none { it in setOf(".", "..") }, "请填写 Gitee 的“账号/仓库”或仓库网址。")
        return repository
    }
    fun https(value: String): HttpUrl {
        val url = value.toHttpUrlOrNull() ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
        security(url.isHttps && url.port == 443 && url.username.isEmpty() && url.password.isEmpty() && url.fragment == null,
            "更新仅允许不含凭据的 HTTPS 地址，已拒绝不安全地址。")
        return url
    }
    fun manifest(text: String, tag: String, notes: String, assets: List<ReleaseAsset>, channel: UpdateChannel,
                 trust: UpdateTrust): ReleaseInfo {
        try {
            val root = Json.parseToJsonElement(text).jsonObject
            fun string(key: String) = (root[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
            fun number(key: String) = (root[key] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
                ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
            security(number("schemaVersion") == 1L && string("platform") == "android", "不支持的更新版本信息格式。")
            security(string("applicationId") == trust.applicationId && string("githubRepository") == trust.githubRepository,
                "更新信息异常，已停止更新。")
            val name = string("versionName")
            security(versionPattern.matches(name) && tag == "android-v$name" && string("tag") == tag, "更新信息异常，已停止更新。")
            val code = number("versionCode")
            val size = number("size")
            val sdk = number("minSdk")
            security(code in 1..2100000000L && size in 1..MAX_APK_BYTES && sdk in 1..10000, "更新信息异常，已停止更新。")
            val filename = string("fileName")
            security(filename == "SUSE-CampusLogin-Android-v$name-release.apk", "更新信息异常，已停止更新。")
            val hash = string("sha256").lowercase()
            security(Regex("[0-9a-f]{64}").matches(hash), "更新信息异常，已停止更新。")
            security(string("signingCertificateSha256").replace(":", "").lowercase() == trust.certificateSha256,
                "更新信息异常，已停止更新。")
            security(notes.length <= 65536, "更新日志过长，已停止更新。")
            val matches = assets.filter { it.name == filename }
            security(matches.size == 1 && matches.single().size == size, "更新信息异常，已停止更新。")
            return ReleaseInfo(trust.applicationId, name, code, tag, notes, filename, size, hash,
                https(matches.single().url), channel, sdk.toInt())
        } catch (e: UpdateException) { throw e }
        catch (_: Exception) { throw UpdateException(UpdateError.SECURITY, "版本信息无法解析，已停止更新。") }
    }
    fun checksums(text: String, release: ReleaseInfo) {
        val entries = text.lineSequence().filter { it.isNotBlank() }.map { it.trim().split(Regex("\\s+"), limit = 2) }.toList()
        security(entries.isNotEmpty() && entries.all { it.size == 2 && Regex("[0-9a-fA-F]{64}").matches(it[0]) }, "更新信息异常，已停止更新。")
        val matches = entries.filter { it[1].removePrefix("*") == release.fileName }
        security(matches.size == 1 && matches.single()[0].lowercase() == release.sha256, "更新信息异常，已停止更新。")
    }
}
data class ReleaseAsset(val name: String, val size: Long, val url: String)
