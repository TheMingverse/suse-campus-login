package io.github.themingverse.susecampus.update

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import okhttp3.HttpUrl
import okhttp3.Response
import org.junit.Assert.*
import org.junit.Test

class FakeTransport(val resolve: (HttpUrl) -> String) : UpdateTransport {
    val calls = mutableListOf<HttpUrl>()
    override suspend fun text(url: HttpUrl, limit: Int): String { calls += url; return resolve(url) }
    override suspend fun open(url: HttpUrl): Response = error("No actual network in source tests")
}
fun githubRelease(code: Long = 5, name: String = "0.4.0") = buildJsonObject {
    put("tag_name", "android-v$name"); put("draft", false); put("prerelease", false); put("body", "实际发行日志 $name")
    putJsonArray("assets") {
        for ((file, size) in listOf("android-release.json" to 600, "SHA256SUMS.txt" to 100, "SUSE-CampusLogin-Android-v$name-release.apk" to 3)) addJsonObject {
            put("name", file); put("size", size)
            put("browser_download_url", "https://github.com/${testTrust.githubRepository}/releases/download/android-v$name/$file")
        }
    }
}
fun sourceText(url: HttpUrl): String = when (url.pathSegments.last()) {
    "android-release.json" -> if (url.toString().contains("0.5.0")) manifest(6, "0.5.0") else manifest()
    "SHA256SUMS.txt" -> "${"cd".repeat(32)}  SUSE-CampusLogin-Android-v${if (url.toString().contains("0.5.0")) "0.5.0" else "0.4.0"}-release.apk\n"
    else -> error("Unexpected synthetic URL $url")
}

class UpdateSourceTest {
    @Test fun githubSelectsMaximumAndroidCodeAndIgnoresDesktopLatest() = runBlocking {
        val transport = FakeTransport { url -> if (url.pathSegments.last() == "releases")
            JsonArray(listOf(buildJsonObject { put("tag_name", "v9.0.0"); put("draft", false) }, githubRelease(), githubRelease(6, "0.5.0"))).toString()
            else sourceText(url) }
        val result = GitHubUpdateSource(testTrust, transport).latest()!!
        assertEquals(6L, result.versionCode); assertEquals("实际发行日志 0.5.0", result.releaseNotes)
        assertTrue(transport.calls.none { it.toString().contains("/latest") })
        assertTrue(transport.calls.all { it.isHttps })
    }
    @Test fun githubFollowsPaginationInsteadOfTakingFirstRelease() = runBlocking {
        val transport = FakeTransport { url -> if (url.pathSegments.last() == "releases") {
            if (url.queryParameter("page") == "1") JsonArray((1..100).map { buildJsonObject { put("tag_name", "v$it.0.0") } }).toString()
            else JsonArray(listOf(githubRelease())).toString()
        } else sourceText(url) }
        assertEquals(5L, GitHubUpdateSource(testTrust, transport).latest()!!.versionCode)
        assertTrue(transport.calls.any { it.queryParameter("page") == "2" })
    }
    @Test fun prereleasesAndDraftsAreNotOffered() = runBlocking {
        val release = githubRelease().toMutableMap().apply { put("prerelease", JsonPrimitive(true)) }
        val transport = FakeTransport { JsonArray(listOf(JsonObject(release), JsonObject(githubRelease().toMutableMap().apply { put("draft", JsonPrimitive(true)) }))).toString() }
        assertNull(GitHubUpdateSource(testTrust, transport).latest())
    }
    @Test fun missingManifestAndInvalidJsonAreSecurityErrors() = runBlocking {
        val invalid = FakeTransport { "<html>intercepted</html>" }
        expectUpdateError(UpdateError.SECURITY) { GitHubUpdateSource(testTrust, invalid).latest() }
        val missing = FakeTransport { JsonArray(listOf(JsonObject(githubRelease().toMutableMap().apply { put("assets", JsonArray(emptyList())) }))).toString() }
        expectUpdateError(UpdateError.SECURITY) { GitHubUpdateSource(testTrust, missing).latest() }
    }
    @Test fun githubRejectsAssetUrlOutsideOfficialRepository() = runBlocking {
        val raw = JsonArray(listOf(githubRelease())).toString().replace("https://github.com/", "https://evil.example/")
        expectUpdateError(UpdateError.SECURITY) { GitHubUpdateSource(testTrust, FakeTransport { raw }).latest() }
    }
    @Test fun giteeUsesDocumentedAttachmentApiAndConfiguredRepository() = runBlocking {
        val transport = FakeTransport { url -> when {
            url.pathSegments.last() == "releases" -> """[{"id":17,"tag_name":"android-v0.4.0","prerelease":false,"body":"国内日志"}]"""
            url.pathSegments.last() == "attach_files" -> """[{"id":1,"name":"android-release.json","size":600},{"id":2,"name":"SHA256SUMS.txt","size":100},{"id":3,"name":"SUSE-CampusLogin-Android-v0.4.0-release.apk","size":3}]"""
            url.encodedPath.endsWith("/1/download") -> manifest()
            url.encodedPath.endsWith("/2/download") -> "${"cd".repeat(32)}  ${testRelease().fileName}"
            else -> error("Unexpected Gitee URL")
        } }
        val info = GiteeUpdateSource("test-owner/test-repo", testTrust, transport).latest()!!
        assertEquals(UpdateChannel.GITEE, info.channel); assertEquals("国内日志", info.releaseNotes)
        assertEquals("/api/v5/repos/test-owner/test-repo/releases/17/attach_files/3/download", info.downloadUrl.encodedPath)
        assertTrue(transport.calls.all { it.host == "gitee.com" && it.encodedPath.startsWith("/api/v5/repos/test-owner/test-repo/") })
    }
    @Test fun unconfiguredGiteeDoesNotMakeNetworkRequest() = runBlocking {
        val transport = FakeTransport { error("Must not request guessed repository") }
        expectUpdateError(UpdateError.NOT_CONFIGURED) { GiteeUpdateSource("", testTrust, transport).latest() }
        assertEquals(0, transport.calls.size)
    }
    @Test fun checksumDisagreementDoesNotProduceAnUpdate() = runBlocking {
        val transport = FakeTransport { url -> if (url.pathSegments.last() == "releases") JsonArray(listOf(githubRelease())).toString()
            else if (url.pathSegments.last() == "SHA256SUMS.txt") "${"00".repeat(32)}  ${testRelease().fileName}" else sourceText(url) }
        expectUpdateError(UpdateError.SECURITY) { GitHubUpdateSource(testTrust, transport).latest() }
    }
}
