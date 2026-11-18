package io.github.themingverse.susecampus.update

import kotlinx.coroutines.*
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID

fun fileSha256(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input -> val buffer = ByteArray(65536); while (true) {
        val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count)
    } }
    return digest.digest().joinToString("") { "%02x".format(it) }
}
data class ArchiveIdentity(val applicationId: String, val versionName: String, val versionCode: Long,
                           val minSdk: Int, val certificateSha256: List<String>)
fun interface ArchiveInspector { fun inspect(file: File): ArchiveIdentity }
class ApkVerifier(private val trust: UpdateTrust, private val inspector: ArchiveInspector,
                  private val installed: () -> InstalledVersion, private val sdk: Int) {
    fun verify(file: File, release: ReleaseInfo) {
        security(file.isFile && file.length() == release.size && fileSha256(file) == release.sha256,
            "安装包校验失败，无法安装。")
        val identity = inspector.inspect(file)
        security(identity.applicationId == trust.applicationId && release.applicationId == trust.applicationId, "安装包与当前应用不匹配，无法安装。")
        security(identity.versionCode == release.versionCode && identity.versionName == release.versionName,
            "安装包校验失败，无法安装。")
        security(identity.versionCode > installed().code, "安装包版本过旧，无法更新。")
        security(identity.minSdk == release.minSdk && identity.minSdk <= sdk, "新版暂不支持当前系统。")
        security(identity.certificateSha256.size == 1 && identity.certificateSha256.single() == trust.certificateSha256,
            "安装包校验失败，无法安装。")
    }
}
class VerifiedApk internal constructor(val file: File, val release: ReleaseInfo)
data class DownloadProgress(val bytes: Long, val total: Long, val source: UpdateChannel)

class ApkDownloader(private val transport: UpdateTransport, private val cache: File, private val verifier: ApkVerifier) {
    suspend fun download(release: ReleaseInfo, progress: (DownloadProgress) -> Unit): VerifiedApk = withContext(Dispatchers.IO) {
        val partialDir = File(cache, "updates/partial").apply { mkdirs() }
        val readyDir = File(cache, "updates/ready").apply { mkdirs() }
        val partial = File(partialDir, UUID.randomUUID().toString() + ".part")
        var ready: File? = null
        var complete = false
        try {
            coroutineScope {
                val response = transport.open(release.downloadUrl)
                val cancellation = launch(start = CoroutineStart.UNDISPATCHED) { try { awaitCancellation() } finally { cancelUpdateResponse(response) } }
                try { response.use {
                    val body = it.body ?: throw UpdateException(UpdateError.SECURITY, "下载失败，请重试。")
                    security(body.contentLength() == -1L || body.contentLength() == release.size, "安装包校验失败，无法安装。")
                    security(it.header("Content-Encoding") in setOf(null, "identity"), "安装包校验失败，无法安装。")
                    var downloaded = 0L
                    partial.outputStream().use { output -> body.byteStream().use { input ->
                        val buffer = ByteArray(65536)
                        progress(DownloadProgress(0, release.size, release.channel))
                        while (true) {
                            ensureActive()
                            val count = try { input.read(buffer) } catch (_: IOException) {
                                ensureActive(); throw UpdateException(UpdateError.NETWORK, "下载中断，请检查网络后重试。")
                            }
                            if (count < 0) break
                            downloaded += count
                            security(downloaded <= release.size, "安装包校验失败，无法安装。")
                            output.write(buffer, 0, count)
                            progress(DownloadProgress(downloaded, release.size, release.channel))
                        }
                    } }
                    if (downloaded != release.size) throw UpdateException(UpdateError.NETWORK, "下载不完整，请重试。")
                } } finally { cancellation.cancel() }
            }
            currentCoroutineContext().ensureActive()
            verifier.verify(partial, release)
            currentCoroutineContext().ensureActive()
            ready = File(readyDir, UUID.randomUUID().toString() + ".apk")
            if (!partial.renameTo(ready)) throw UpdateException(UpdateError.STORAGE, "无法保存更新文件，请检查存储空间。")
            complete = true
            VerifiedApk(ready!!, release)
        } catch (e: CancellationException) { throw e }
        catch (e: UpdateException) { throw e }
        catch (_: IOException) { throw UpdateException(UpdateError.STORAGE, "无法保存更新文件，请检查存储空间。") }
        finally { partial.delete(); if (!complete) ready?.delete() }
    }
}
