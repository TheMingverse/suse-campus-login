package io.github.themingverse.susecampus.update

import kotlinx.coroutines.*
import okhttp3.*
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

interface UpdateTransport {
    suspend fun open(url: HttpUrl): Response
    suspend fun text(url: HttpUrl, limit: Int): String
}
private class UpdateCallHandle(var call: Call? = null)
internal fun cancelUpdateResponse(response: Response) {
    val handle = response.request.tag(UpdateCallHandle::class.java)
    if (handle != null) handle.call?.cancel() else response.close()
}

/** Independent client: no campus binding, account, auth cookie, cache, or background service. */
class UpdateHttp(private val client: OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(8, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).callTimeout(10, TimeUnit.MINUTES)
    .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
    .cookieJar(CookieJar.NO_COOKIES).cache(null).build(),
    private val validate: (HttpUrl) -> Unit = { UpdateFormat.https(it.toString()); Unit }) : UpdateTransport {
    override suspend fun open(url: HttpUrl): Response {
        var next = url
        repeat(6) { attempt ->
            validate(next)
            val response = request(next)
            if (response.code in setOf(301, 302, 303, 307, 308)) {
                val location = response.header("Location")
                val redirected = location?.let { next.resolve(it) }
                response.close()
                security(redirected != null && attempt < 5, "更新信息异常，已停止更新。")
                next = redirected!!
            } else {
                if (!response.isSuccessful) {
                    val status = response.code
                    response.close()
                    throw UpdateException(UpdateError.SERVICE, "更新服务暂时不可用，请稍后重试。")
                }
                if (response.code != 200) { response.close(); throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。") }
                return response
            }
        }
        throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
    }
    private suspend fun request(url: HttpUrl): Response = suspendCancellableCoroutine { continuation ->
        val handle = UpdateCallHandle()
        val call = client.newCall(Request.Builder().url(url).header("Accept", "application/json, application/octet-stream")
            .header("User-Agent", "SUSE-Campus-Login-Android").header("Accept-Encoding", "identity")
            .tag(UpdateCallHandle::class.java, handle).build())
        handle.call = call
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (continuation.isActive) continuation.resumeWithException(UpdateException(UpdateError.NETWORK, "连接失败，请稍后重试。"))
            }
            override fun onResponse(call: Call, response: Response) {
                continuation.resume(response) { _, value, _ -> value.close() }
            }
        })
    }
    override suspend fun text(url: HttpUrl, limit: Int): String = withContext(Dispatchers.IO) {
        try { withTimeout(30000) { coroutineScope {
            val response = open(url)
            val cancellation = launch(start = CoroutineStart.UNDISPATCHED) { try { awaitCancellation() } finally { cancelUpdateResponse(response) } }
            try {
                response.use {
                    val body = it.body ?: throw UpdateException(UpdateError.SECURITY, "更新信息异常，已停止更新。")
                    security(body.contentLength() <= limit, "更新信息异常，已停止更新。")
                    val output = java.io.ByteArrayOutputStream()
                    val buffer = ByteArray(8192)
                    body.byteStream().use { input ->
                        while (true) {
                            ensureActive()
                            val count = input.read(buffer)
                            if (count < 0) break
                            security(output.size() + count <= limit, "更新信息异常，已停止更新。")
                            output.write(buffer, 0, count)
                        }
                    }
                    try { Charsets.UTF_8.newDecoder().decode(java.nio.ByteBuffer.wrap(output.toByteArray())).toString() }
                    catch (_: java.nio.charset.CharacterCodingException) { throw UpdateException(UpdateError.SECURITY, "更新信息不是合法的 UTF-8 文本。") }
                }
            } catch (e: IOException) { currentCoroutineContext().ensureActive(); throw UpdateException(UpdateError.NETWORK, "连接失败，请稍后重试。") }
            finally { cancellation.cancel() }
        } } } catch (e: TimeoutCancellationException) { currentCoroutineContext().ensureActive(); throw UpdateException(UpdateError.NETWORK, "连接失败，请稍后重试。") }
    }
}
