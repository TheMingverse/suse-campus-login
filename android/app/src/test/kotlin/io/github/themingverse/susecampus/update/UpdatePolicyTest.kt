package io.github.themingverse.susecampus.update

import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.*
import org.junit.Test

val testTrust = UpdateTrust("io.github.themingverse.susecampus", "TheMingverse/suse-campus-login", "ab".repeat(32))
fun testRelease(code: Long = 5, channel: UpdateChannel = UpdateChannel.GITEE, size: Long = 3, hash: String = "cd".repeat(32)) =
    ReleaseInfo(testTrust.applicationId, if (code == 4L) "0.3.0" else "0.4.0", code,
        if (code == 4L) "android-v0.3.0" else "android-v0.4.0", "更新日志", "SUSE-CampusLogin-Android-v0.4.0-release.apk",
        size, hash, "https://github.com/TheMingverse/suse-campus-login/releases/download/android-v0.4.0/SUSE-CampusLogin-Android-v0.4.0-release.apk".toHttpUrl(), channel, 29)
fun manifest(code: Long = 5, name: String = "0.4.0") = """{
    "schemaVersion":1,"platform":"android","applicationId":"${testTrust.applicationId}",
    "versionName":"$name","versionCode":$code,"minSdk":29,"tag":"android-v$name",
    "fileName":"SUSE-CampusLogin-Android-v$name-release.apk","size":3,"sha256":"${"cd".repeat(32)}",
    "signingCertificateSha256":"${testTrust.certificateSha256}","githubRepository":"${testTrust.githubRepository}"
}"""
class FakeSource(override val channel: UpdateChannel, var info: ReleaseInfo? = testRelease(channel = channel),
                 var error: UpdateError? = null) : UpdateSource {
    var calls = 0
    override suspend fun latest(): ReleaseInfo? { calls++; error?.let { throw UpdateException(it, "synthetic error") }; return info }
}
inline fun expectUpdateError(kind: UpdateError, action: () -> Unit) {
    try { action(); fail("Expected $kind") } catch (e: UpdateException) { assertEquals(kind, e.kind) }
}

class UpdatePolicyTest {
    @Test fun autoPrefersConfiguredGitee() = runBlocking {
        val github = FakeSource(UpdateChannel.GITHUB); val gitee = FakeSource(UpdateChannel.GITEE)
        assertEquals(UpdateChannel.GITEE, UpdateRepository(github, gitee, UpdateChannel.AUTO).latest()!!.channel)
        assertEquals(0, github.calls); assertEquals(1, gitee.calls)
    }
    @Test fun autoFallsBackOnlyForNetworkOrServiceErrors() = runBlocking {
        for (error in listOf(UpdateError.NETWORK, UpdateError.SERVICE)) {
            val github = FakeSource(UpdateChannel.GITHUB); val gitee = FakeSource(UpdateChannel.GITEE, error = error)
            assertEquals(UpdateChannel.GITHUB, UpdateRepository(github, gitee, UpdateChannel.AUTO).latest()!!.channel)
            assertEquals(1, github.calls)
        }
    }
    @Test fun autoDoesNotIgnoreSecurityErrors() = runBlocking {
        val github = FakeSource(UpdateChannel.GITHUB); val gitee = FakeSource(UpdateChannel.GITEE, error = UpdateError.SECURITY)
        expectUpdateError(UpdateError.SECURITY) { UpdateRepository(github, gitee, UpdateChannel.AUTO).latest() }
        assertEquals(0, github.calls)
    }
    @Test fun manualGiteeNeverFallsBack() = runBlocking {
        val github = FakeSource(UpdateChannel.GITHUB); val gitee = FakeSource(UpdateChannel.GITEE, error = UpdateError.NETWORK)
        expectUpdateError(UpdateError.NETWORK) { UpdateRepository(github, gitee, UpdateChannel.GITEE).latest() }
        assertEquals(0, github.calls)
    }
    @Test fun manualGithubNeverUsesGitee() = runBlocking {
        val github = FakeSource(UpdateChannel.GITHUB, error = UpdateError.NETWORK); val gitee = FakeSource(UpdateChannel.GITEE)
        expectUpdateError(UpdateError.NETWORK) { UpdateRepository(github, gitee, UpdateChannel.GITHUB).latest() }
        assertEquals(0, gitee.calls)
    }
    @Test fun unconfiguredGiteeUsesGithubOnlyInAutoMode() = runBlocking {
        val github = FakeSource(UpdateChannel.GITHUB)
        assertNotNull(UpdateRepository(github, null, UpdateChannel.AUTO).latest())
        expectUpdateError(UpdateError.NOT_CONFIGURED) { UpdateRepository(github, null, UpdateChannel.GITEE).latest() }
    }
    @Test fun emptySourceDoesNotClaimLatest() = runBlocking {
        assertNull(UpdateRepository(FakeSource(UpdateChannel.GITHUB, info = null), null, UpdateChannel.AUTO).latest())
    }
    @Test fun compareHigherSameAndLowerVersionCodes() {
        val installed = InstalledVersion("0.3.0", 4)
        assertEquals(VersionDecision.AVAILABLE, UpdateChecker.compare(installed, testRelease()))
        assertEquals(VersionDecision.CURRENT, UpdateChecker.compare(installed, testRelease(4)))
        expectUpdateError(UpdateError.DOWNGRADE) { UpdateChecker.compare(installed, testRelease(3)) }
        expectUpdateError(UpdateError.SECURITY) { UpdateChecker.compare(installed, testRelease(4).copy(versionName = "9.0.0")) }
    }
    @Test fun compatibleSchemaOneGetsNotesAndUrlFromReleaseAssets() {
        val info = UpdateFormat.manifest(manifest(), "android-v0.4.0", "日志", listOf(ReleaseAsset(
            "SUSE-CampusLogin-Android-v0.4.0-release.apk", 3, testRelease().downloadUrl.toString())), UpdateChannel.GITHUB, testTrust)
        assertEquals("日志", info.releaseNotes); assertEquals(5L, info.versionCode); assertEquals(testRelease().downloadUrl, info.downloadUrl)
    }
    @Test fun incompleteMalformedAndUnsafeMetadataAreRejected() {
        val assets = listOf(ReleaseAsset(testRelease().fileName, 3, testRelease().downloadUrl.toString()))
        val invalid = listOf("{}", "not-json", manifest().replace("\"schemaVersion\":1", "\"schemaVersion\":2"),
            manifest().replace(testTrust.applicationId, "other.app"), manifest().replace("\"size\":3", "\"size\":0"),
            manifest().replace("\"versionCode\":5", "\"versionCode\":\"5\""), manifest().replace("cd".repeat(32), "bad"),
            manifest().replace(testTrust.certificateSha256, "ef".repeat(32)), manifest().replace("android-v0.4.0", "v1.1.3"))
        for (text in invalid) expectUpdateError(UpdateError.SECURITY) { UpdateFormat.manifest(text, "android-v0.4.0", "", assets, UpdateChannel.GITHUB, testTrust) }
        expectUpdateError(UpdateError.SECURITY) { UpdateFormat.manifest(manifest(), "android-v0.4.0", "", emptyList(), UpdateChannel.GITHUB, testTrust) }
        expectUpdateError(UpdateError.SECURITY) { UpdateFormat.https("http://github.com/file.apk") }
        expectUpdateError(UpdateError.SECURITY) { UpdateFormat.https("https://user:password@github.com/file.apk") }
    }
    @Test fun checksumsMustMatchManifestAndNotRepeat() {
        val release = testRelease()
        val line = "${release.sha256}  ${release.fileName}\n"
        UpdateFormat.checksums(line, release)
        expectUpdateError(UpdateError.SECURITY) { UpdateFormat.checksums(line + line, release) }
        expectUpdateError(UpdateError.SECURITY) { UpdateFormat.checksums(line.replace(release.sha256, "00".repeat(32)), release) }
    }
    @Test fun giteeRepositoryConfigurationIsExplicitAndValidated() {
        assertEquals("", UpdateFormat.repository(""))
        assertEquals("test-owner/test-repo", UpdateFormat.repository("https://gitee.com/test-owner/test-repo/"))
        for (input in listOf("https://evil.example/a/b", "../repo", "owner/repo/extra", "http://gitee.com/a/b"))
            expectUpdateError(UpdateError.SECURITY) { UpdateFormat.repository(input) }
    }
    @Test fun automaticDownloadFallbackRequiresIdenticalArtifact() = runBlocking {
        val github = FakeSource(UpdateChannel.GITHUB)
        val repository = UpdateRepository(github, FakeSource(UpdateChannel.GITEE), UpdateChannel.AUTO)
        assertEquals(UpdateChannel.GITHUB, repository.fallbackDownload(testRelease(), UpdateException(UpdateError.NETWORK, "test")).channel)
        github.info = testRelease(channel = UpdateChannel.GITHUB, hash = "00".repeat(32))
        expectUpdateError(UpdateError.SECURITY) { repository.fallbackDownload(testRelease(), UpdateException(UpdateError.NETWORK, "test")) }
    }
    @Test fun downloadSecurityFailureDoesNotTriggerFallback() = runBlocking {
        val github = FakeSource(UpdateChannel.GITHUB)
        expectUpdateError(UpdateError.SECURITY) { UpdateRepository(github, null, UpdateChannel.AUTO)
            .fallbackDownload(testRelease(), UpdateException(UpdateError.SECURITY, "hash mismatch")) }
        assertEquals(0, github.calls)
    }
}
