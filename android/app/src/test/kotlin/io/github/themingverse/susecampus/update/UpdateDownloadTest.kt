package io.github.themingverse.susecampus.update

import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.mockwebserver.*
import okio.Buffer
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class UpdateDownloadTest {
    @get:Rule val folder = TemporaryFolder()
    private val bytes = ByteArray(128 * 1024) { (it % 127).toByte() }
    private fun hash(value: ByteArray) = MessageDigest.getInstance("SHA-256").digest(value).joinToString("") { "%02x".format(it) }
    private fun verifier(wrongPackage: Boolean = false, wrongCertificate: Boolean = false) = ApkVerifier(testTrust, ArchiveInspector {
        ArchiveIdentity(if (wrongPackage) "other.app" else testTrust.applicationId, "0.4.0", 5, 29,
            listOf(if (wrongCertificate) "00".repeat(32) else testTrust.certificateSha256))
    }, { InstalledVersion("0.3.0", 4) }, 36)
    private fun http() = UpdateHttp(validate = { security(it.host in setOf("localhost", "127.0.0.1", "::1"), "Tests only use local loopback") })
    private fun assertEmpty(cache: File) {
        assertTrue(File(cache, "updates/partial").listFiles().isNullOrEmpty())
        assertTrue(File(cache, "updates/ready").listFiles().isNullOrEmpty())
    }
    @Test fun completeDownloadReportsProgressAndPublishesOnlyVerifiedFile() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody(Buffer().write(bytes)))
            val info = testRelease(size = bytes.size.toLong(), hash = hash(bytes)).copy(downloadUrl = server.url("/apk"))
            val progress = mutableListOf<DownloadProgress>()
            val ready = ApkDownloader(http(), folder.root, verifier()).download(info) { progress += it }
            assertArrayEquals(bytes, ready.file.readBytes())
            assertEquals("ready", ready.file.parentFile!!.name)
            assertEquals(bytes.size.toLong(), progress.last().bytes)
            assertTrue(progress.size >= 2)
            assertTrue(File(folder.root, "updates/partial").listFiles().isNullOrEmpty())
        }
    }
    @Test fun hashMismatchDeletesFileAndDoesNotPublishReadyApk() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody(Buffer().write(bytes)))
            val info = testRelease(size = bytes.size.toLong(), hash = "00".repeat(32)).copy(downloadUrl = server.url("/apk"))
            expectUpdateError(UpdateError.SECURITY) { ApkDownloader(http(), folder.root, verifier()).download(info) {} }
            assertEquals(1, server.requestCount)
            assertEmpty(folder.root)
        }
    }
    @Test fun packageAndCertificateMismatchBothDeleteDownloadedFile() = runBlocking {
        MockWebServer().use { server ->
            for (gate in listOf(verifier(wrongPackage = true), verifier(wrongCertificate = true))) {
                server.enqueue(MockResponse().setBody(Buffer().write(bytes)))
                val info = testRelease(size = bytes.size.toLong(), hash = hash(bytes)).copy(downloadUrl = server.url("/apk"))
                expectUpdateError(UpdateError.SECURITY) { ApkDownloader(http(), folder.root, gate).download(info) {} }
                assertEmpty(folder.root)
            }
        }
    }
    @Test fun interruptedDownloadCleansPartialFile() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody(Buffer().write(bytes)).setSocketPolicy(SocketPolicy.DISCONNECT_DURING_RESPONSE_BODY))
            val info = testRelease(size = bytes.size.toLong(), hash = hash(bytes)).copy(downloadUrl = server.url("/apk"))
            expectUpdateError(UpdateError.NETWORK) { ApkDownloader(http(), folder.root, verifier()).download(info) {} }
            assertEmpty(folder.root)
        }
    }
    @Test fun cancellationClosesResponseAndDeletesPartialFile() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody(Buffer().write(bytes)).throttleBody(1024, 100, TimeUnit.MILLISECONDS))
            val info = testRelease(size = bytes.size.toLong(), hash = hash(bytes)).copy(downloadUrl = server.url("/apk"))
            val received = CompletableDeferred<Unit>()
            val downloader = ApkDownloader(http(), folder.root, verifier())
            val job = launch { downloader.download(info) { if (it.bytes > 0) received.complete(Unit) } }
            withTimeout(5000) { received.await(); job.cancelAndJoin() }
            assertTrue(job.isCancelled); assertEmpty(folder.root)
            server.enqueue(MockResponse().setBody(Buffer().write(bytes)))
            assertTrue(downloader.download(info) {}.file.exists())
        }
    }
    @Test fun declaredSizeMismatchIsSecurityFailure() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody(Buffer().write(bytes)))
            val info = testRelease(size = 3).copy(downloadUrl = server.url("/apk"))
            expectUpdateError(UpdateError.SECURITY) { ApkDownloader(http(), folder.root, verifier()).download(info) {} }
            assertEmpty(folder.root)
        }
    }
    @Test fun productionTransportRejectsHttpBeforeConnecting() = runBlocking {
        MockWebServer().use { server ->
            expectUpdateError(UpdateError.SECURITY) { UpdateHttp().open(server.url("/must-not-connect")) }
            assertEquals(0, server.requestCount)
        }
    }
    @Test fun httpsRedirectCannotDowngradeToHttp() = runBlocking {
        var calls = 0
        val client = OkHttpClient.Builder().addInterceptor { chain -> calls++
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(302).message("redirect")
                .header("Location", "http://example.com/apk").body("".toResponseBody()).build()
        }.build()
        expectUpdateError(UpdateError.SECURITY) { UpdateHttp(client).open("https://example.com/start".toHttpUrl()) }
        assertEquals(1, calls)
    }
    @Test fun verifierRejectsWrongVersionAndDowngrade() {
        val file = folder.newFile().apply { writeBytes(bytes) }
        val info = testRelease(size = bytes.size.toLong(), hash = hash(bytes))
        for (code in listOf(4L, 6L)) {
            val gate = ApkVerifier(testTrust, ArchiveInspector { ArchiveIdentity(testTrust.applicationId, "0.4.0", code, 29, listOf(testTrust.certificateSha256)) }, { InstalledVersion("0.3.0", 4) }, 36)
            expectUpdateError(UpdateError.SECURITY) { gate.verify(file, info) }
        }
    }
    @Test fun metadataLimitsAndMalformedUtf8AreSecurityFailures() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("x".repeat(50)))
            expectUpdateError(UpdateError.SECURITY) { http().text(server.url("/too-large"), 10) }
            server.enqueue(MockResponse().setBody(Buffer().write(byteArrayOf(0xC3.toByte(), 0x28))))
            expectUpdateError(UpdateError.SECURITY) { http().text(server.url("/invalid-utf8"), 100) }
        }
    }
}
