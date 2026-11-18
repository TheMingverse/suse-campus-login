package io.github.themingverse.susecampus.update

import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.*
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl

interface UpdateSource { val channel: UpdateChannel; suspend fun latest(): ReleaseInfo? }

fun updateRepository(settings: UpdateSettings, trust: UpdateTrust, transport: UpdateTransport,
                     onSource: (UpdateChannel) -> Unit = {}) = UpdateRepository(
    GitHubUpdateSource(trust, transport),
    settings.giteeRepository.takeIf { it.isNotEmpty() }?.let { GiteeUpdateSource(it, trust, transport) },
    settings.channel, onSource)

/** Reuse schemaVersion 1 manifests; notes and URLs come from the same release's API assets. */
open class ReleaseApiSource(
    override val channel: UpdateChannel, private val repository: String,
    private val trust: UpdateTrust, private val transport: UpdateTransport,
) : UpdateSource {
    private val base: HttpUrl = (if (channel == UpdateChannel.GITHUB) "https://api.github.com/repos/$repository/"
        else "https://gitee.com/api/v5/repos/$repository/").toHttpUrl()
    private fun parse(text: String): JsonElement = try { Json.parseToJsonElement(text) }
        catch (_: Exception) { throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。") }
    private fun JsonObject.string(key: String): String = (get(key) as? JsonPrimitive)?.takeIf { it.isString }?.content
        ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
    private fun JsonObject.number(key: String): Long {
        val number = (get(key) as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
            ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
        security(number >= 0 && (key != "id" || number > 0), "更新信息异常，已停止更新。")
        return number
    }
    private fun JsonObject.flag(key: String): Boolean {
        if (get(key) == null) return false
        return (get(key) as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
            ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
    }
    private suspend fun pages(path: String): List<JsonObject> {
        val result = mutableListOf<JsonObject>()
        for (page in 1..20) {
            val url = base.resolve(path)!!.newBuilder().addQueryParameter("per_page", "100").addQueryParameter("page", "$page")
                .apply { if (channel == UpdateChannel.GITEE) addQueryParameter("direction", "desc") }.build()
            val entries = parse(transport.text(url, 2 * 1024 * 1024)) as? JsonArray
                ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
            result += entries.map { it as? JsonObject ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。") }
            if (entries.size < 100) return result
        }
        throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
    }
    override suspend fun latest(): ReleaseInfo? {
        if (repository.isEmpty()) throw UpdateException(UpdateError.NOT_CONFIGURED, "请配置 Gitee 镜像仓库，或选择 GitHub。")
        try {
            val releases = pages("releases").filter {
                val tag = it.string("tag_name")
                tag.startsWith("android-v") && !it.flag("draft") && !it.flag("prerelease") &&
                    UpdateFormat.versionPattern.matches(tag.removePrefix("android-v"))
            }
            val available = releases.map { release ->
                val tag = release.string("tag_name")
                val rawAssets = if (channel == UpdateChannel.GITHUB) {
                    (release["assets"] as? JsonArray)?.map { it as? JsonObject
                        ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。") }
                        ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
                } else pages("releases/${release.number("id")}/attach_files")
                val androidFiles = setOf("android-release.json", "SHA256SUMS.txt",
                    "SUSE-CampusLogin-Android-v${tag.removePrefix("android-v")}-release.apk")
                val assets = rawAssets.filter { it.string("name") in androidFiles }.map { asset ->
                    val name = asset.string("name")
                    val url = if (channel == UpdateChannel.GITHUB) asset.string("browser_download_url")
                        else base.resolve("releases/${release.number("id")}/attach_files/${asset.number("id")}/download")!!.toString()
                    if (channel == UpdateChannel.GITHUB) {
                        val parsed = UpdateFormat.https(url)
                        security(parsed.host == "github.com" && parsed.encodedPath.startsWith("/$repository/releases/download/$tag/"),
                            "更新信息异常，已停止更新。")
                    }
                    ReleaseAsset(name, asset.number("size"), url)
                }
                suspend fun assetText(name: String): String {
                    val matches = assets.filter { it.name == name }
                    security(matches.size == 1, "更新信息异常，已停止更新。")
                    return transport.text(UpdateFormat.https(matches.single().url), 128 * 1024)
                }
                val notes = release["body"]?.let { if (it is JsonNull) "" else (it as? JsonPrimitive)?.takeIf { v -> v.isString }?.content
                    ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。") } ?: ""
                val info = UpdateFormat.manifest(assetText("android-release.json"), tag, notes, assets, channel, trust)
                UpdateFormat.checksums(assetText("SHA256SUMS.txt"), info)
                info
            }
            security(available.groupBy { it.versionCode }.values.none { sameCode -> sameCode.any { !it.sameArtifact(sameCode.first()) } },
                "更新信息异常，已停止更新。")
            return available.maxByOrNull { it.versionCode }
        } catch (e: CancellationException) { throw e }
        catch (e: UpdateException) { throw e }
        catch (_: Exception) { throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。") }
    }
}

class GitHubUpdateSource(trust: UpdateTrust, transport: UpdateTransport) :
    ReleaseApiSource(UpdateChannel.GITHUB, trust.githubRepository, trust, transport)
class GiteeUpdateSource(repository: String, trust: UpdateTrust, transport: UpdateTransport) :
    ReleaseApiSource(UpdateChannel.GITEE, UpdateFormat.repository(repository), trust, transport)

class UpdateRepository(private val github: UpdateSource, private val gitee: UpdateSource?, val channel: UpdateChannel,
                       private val onSource: (UpdateChannel) -> Unit = {}) {
    private fun fallback(error: UpdateException) = error.kind in setOf(UpdateError.NETWORK, UpdateError.SERVICE)
    private suspend fun fetch(source: UpdateSource): ReleaseInfo? { onSource(source.channel); return source.latest() }
    suspend fun latest(): ReleaseInfo? = when (channel) {
        UpdateChannel.GITHUB -> fetch(github)
        UpdateChannel.GITEE -> fetch(gitee ?: throw UpdateException(UpdateError.NOT_CONFIGURED, "请配置 Gitee 镜像仓库，或选择 GitHub。"))
        UpdateChannel.AUTO -> if (gitee == null) fetch(github) else try { fetch(gitee) }
            catch (e: UpdateException) { if (fallback(e)) fetch(github) else throw e }
    }
    suspend fun fallbackDownload(expected: ReleaseInfo, error: UpdateException): ReleaseInfo {
        if (channel != UpdateChannel.AUTO || expected.channel != UpdateChannel.GITEE || !fallback(error)) throw error
        val official = fetch(github)
        security(official != null && expected.sameArtifact(official), "更新信息异常，已停止更新。")
        return official!!
    }
}
