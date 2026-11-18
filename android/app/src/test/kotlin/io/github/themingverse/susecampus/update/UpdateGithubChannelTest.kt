package io.github.themingverse.susecampus.update

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.util.concurrent.TimeUnit

/** Real transport and source parsing, routed to loopback only; no public releases or keys. */
class UpdateGithubChannelTest {
    @get:Rule val folder = TemporaryFolder()
    private val apk = "apk".toByteArray()
    private val digest = java.security.MessageDigest.getInstance("SHA-256").digest(apk).joinToString("") { "%02x".format(it) }
    private fun localTransport(server: MockWebServer): UpdateHttp {
        val client = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
            .retryOnConnectionFailure(false).readTimeout(250, TimeUnit.MILLISECONDS)
            .callTimeout(2, TimeUnit.SECONDS).addInterceptor { chain ->
                val original = chain.request()
                assertTrue(original.url.isHttps)
                assertNull(original.header("Authorization"))
                chain.proceed(original.newBuilder().url(server.url(original.url.encodedPath)).build())
            }.build()
        return UpdateHttp(client)
    }
    private fun verifier() = ApkVerifier(testTrust, ArchiveInspector {
        ArchiveIdentity(testTrust.applicationId, "0.4.0", 5, 29, listOf(testTrust.certificateSha256))
    }, { InstalledVersion("0.3.0", 4) }, 36)

    @Test fun anonymousGithubCheckAndCdnRedirectDownloadUseSameArtifact() = runBlocking {
        MockWebServer().use { server ->
            val transport = localTransport(server)
            server.enqueue(MockResponse().setBody(JsonArray(listOf(githubRelease())).toString()))
            server.enqueue(MockResponse().setBody(manifest().replace("cd".repeat(32), digest)))
            server.enqueue(MockResponse().setBody("$digest  SUSE-CampusLogin-Android-v0.4.0-release.apk\n"))
            server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", "https://release-assets.githubusercontent.com/asset.apk"))
            server.enqueue(MockResponse().setBody("apk"))
            val release = GitHubUpdateSource(testTrust, transport).latest()!!
            assertEquals(UpdateChannel.GITHUB, release.channel)
            val ready = ApkDownloader(transport, folder.root, verifier()).download(release) {}
            assertArrayEquals(apk, ready.file.readBytes())
            assertEquals(5, server.requestCount)
        }
    }

    @Test fun androidReleaseIgnoresDesktopAssetsEvenWithUnrelatedDownloadUrls() = runBlocking {
        val release = githubRelease().toMutableMap().apply {
            put("assets", JsonArray(githubRelease()["assets"]!!.jsonArray + buildJsonObject {
                put("name", "SUSE-Windows.zip"); put("browser_download_url", "http://desktop.invalid/windows.zip"); put("size", 1)
            } + buildJsonObject { put("name", "SUSE-macOS.dmg"); put("size", 1) }))
        }
        val transport = FakeTransport { url -> if (url.pathSegments.last() == "releases")
            JsonArray(listOf(JsonObject(release))).toString() else sourceText(url) }
        assertEquals(5L, GitHubUpdateSource(testTrust, transport).latest()!!.versionCode)
        assertFalse(transport.calls.any { it.toString().contains("desktop.invalid") })
    }

    @Test fun allSupportedHttpsRedirectCodesWorkThroughLocalServer() = runBlocking {
        MockWebServer().use { server ->
            val transport = localTransport(server)
            for (code in listOf(301, 302, 303, 307, 308)) {
                server.enqueue(MockResponse().setResponseCode(code).addHeader("Location", "https://release-assets.githubusercontent.com/file"))
                server.enqueue(MockResponse().setBody("ok"))
                assertEquals("ok", transport.text("https://github.com/start".toHttpUrl(), 10))
            }
        }
    }

    @Test fun missingLocationAndRedirectLoopsFailClosed() = runBlocking {
        MockWebServer().use { server ->
            val transport = localTransport(server)
            server.enqueue(MockResponse().setResponseCode(302))
            expectUpdateError(UpdateError.SECURITY) { transport.open("https://github.com/start".toHttpUrl()) }
            repeat(6) { server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", "/loop")) }
            expectUpdateError(UpdateError.SECURITY) { transport.open("https://github.com/loop".toHttpUrl()) }
            assertEquals(7, server.requestCount)
        }
    }

    @Test fun githubServerErrorsAreExplicitServiceErrors() = runBlocking {
        MockWebServer().use { server ->
            for (code in listOf(403, 404, 429, 500, 503)) {
                server.enqueue(MockResponse().setResponseCode(code))
                try { GitHubUpdateSource(testTrust, localTransport(server)).latest(); fail("Expected HTTP error") }
                catch (error: UpdateException) { assertEquals(UpdateError.SERVICE, error.kind); assertTrue(error.message!!.contains("HTTP $code")) }
            }
        }
    }

    @Test fun metadataReadTimeoutIsAnExplicitNetworkError() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("[]").setHeadersDelay(600, TimeUnit.MILLISECONDS))
            expectUpdateError(UpdateError.NETWORK) { GitHubUpdateSource(testTrust, localTransport(server)).latest() }
        }
    }

    @Test fun downloadTimeoutCleansPartialAndNeverCreatesReady() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("apk").setBodyDelay(600, TimeUnit.MILLISECONDS))
            val release = testRelease(channel = UpdateChannel.GITHUB, hash = digest)
            expectUpdateError(UpdateError.NETWORK) { ApkDownloader(localTransport(server), folder.root, verifier()).download(release) {} }
            assertTrue(java.io.File(folder.root, "updates/partial").listFiles().isNullOrEmpty())
            assertTrue(java.io.File(folder.root, "updates/ready").listFiles().isNullOrEmpty())
        }
    }

    @Test fun selectedGithubApkMustUseHttpsAndOfficialRepository() = runBlocking {
        for (url in listOf("http://github.com/unsafe.apk", "https://github.com/other/repository/releases/download/android-v0.4.0/a.apk")) {
            val release = githubRelease().toMutableMap().apply {
                put("assets", JsonArray(githubRelease()["assets"]!!.jsonArray.map { asset ->
                    if (asset.jsonObject["name"]!!.jsonPrimitive.content.endsWith(".apk"))
                        JsonObject(asset.jsonObject.toMutableMap().apply { put("browser_download_url", JsonPrimitive(url)) }) else asset
                }))
            }
            expectUpdateError(UpdateError.SECURITY) { GitHubUpdateSource(testTrust, FakeTransport { JsonArray(listOf(JsonObject(release))).toString() }).latest() }
        }
    }
}
