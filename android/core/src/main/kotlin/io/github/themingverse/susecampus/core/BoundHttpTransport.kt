package io.github.themingverse.susecampus.core

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.Proxy
import java.net.URI
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

object RequestPolicy {
    fun allows(request: HttpRequest): Boolean = runCatching {
        val uri = URI(request.url)
        if (request.probe) request.method == "GET" && request.body.isEmpty() && Protocol.probes.any { it.first == request.url }
        else uri.scheme == "http" && uri.host == Protocol.HOST && uri.port in setOf(-1, 80, 8080) &&
            uri.rawUserInfo == null && uri.rawFragment == null && uri.rawPath == "/eportal/InterFace.do" &&
            request.method == "POST" && uri.rawQuery.orEmpty().let { query ->
                query == "method=pageInfo" || query == "method=login" ||
                    (query.startsWith("method=getServices&queryString=") && !query.removePrefix("method=getServices&queryString=").contains('&'))
            }
    }.getOrDefault(false)
}

/** Construct one per WifiLease; the supplied client MUST have that Network's SocketFactory and DNS. */
class BoundHttpTransport(base: OkHttpClient) : HttpTransport {
    private val jar = object : CookieJar {
        private val cookies = mutableListOf<Cookie>()
        @Synchronized override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
            if (url.host != Protocol.HOST) return
            for (cookie in cookies.filter { it.domain == Protocol.HOST }) {
                this.cookies.removeAll { it.name == cookie.name && it.path == cookie.path }
                if (cookie.expiresAt > System.currentTimeMillis()) this.cookies.add(cookie)
            }
        }
        @Synchronized override fun loadForRequest(url: HttpUrl): List<Cookie> =
            if (url.host == Protocol.HOST) cookies.filter { it.matches(url) && it.expiresAt > System.currentTimeMillis() } else emptyList()
        @Synchronized fun clear() { cookies.clear() }
    }
    private fun builder(base: OkHttpClient) = base.newBuilder()
        .proxy(Proxy.NO_PROXY).cache(null).followRedirects(false).followSslRedirects(false)
        .authenticator(Authenticator.NONE).proxyAuthenticator(Authenticator.NONE).retryOnConnectionFailure(false)
    private val portal = builder(base).cookieJar(jar).connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(6, TimeUnit.SECONDS).callTimeout(12, TimeUnit.SECONDS).build()
    private val probe = builder(base).cookieJar(CookieJar.NO_COOKIES).connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(4, TimeUnit.SECONDS).callTimeout(8, TimeUnit.SECONDS).build()

    override suspend fun execute(request: HttpRequest): HttpReply {
        if (!RequestPolicy.allows(request)) throw PortalException(Failure.MANUAL)
        val builder = Request.Builder().url(request.url).header("Cache-Control", "no-cache").header("Pragma", "no-cache")
        if (request.method == "POST") builder.post(request.body.toRequestBody("application/x-www-form-urlencoded; charset=UTF-8".toMediaType()))
        val call = (if (request.probe) probe else portal).newCall(builder.build())
        return suspendCancellableCoroutine { continuation ->
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (continuation.isActive) continuation.resumeWithException(PortalException(Failure.TEMPORARY))
                }
                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        try {
                            val limit = if (request.probe) 65536 else 200000
                            val output = ByteArrayOutputStream()
                            response.body?.byteStream()?.use { input ->
                                val buffer = ByteArray(4096)
                                while (output.size() <= limit) {
                                    val count = input.read(buffer, 0, minOf(buffer.size, limit + 1 - output.size()))
                                    if (count < 0) break
                                    output.write(buffer, 0, count)
                                }
                            }
                            if (output.size() > limit) throw PortalException(Failure.MANUAL)
                            if (continuation.isActive) continuation.resume(HttpReply(response.code, request.url,
                                response.headers.names().associateWith { response.header(it).orEmpty() }, output.toByteArray()))
                        } catch (error: Exception) {
                            if (continuation.isActive) continuation.resumeWithException(
                                if (error is PortalException) error else PortalException(Failure.TEMPORARY))
                        }
                    }
                }
            })
        }
    }

    override fun close() {
        portal.dispatcher.cancelAll(); probe.dispatcher.cancelAll()
        portal.connectionPool.evictAll(); probe.connectionPool.evictAll()
        portal.dispatcher.executorService.shutdown(); probe.dispatcher.executorService.shutdown()
        jar.clear()
    }
}
