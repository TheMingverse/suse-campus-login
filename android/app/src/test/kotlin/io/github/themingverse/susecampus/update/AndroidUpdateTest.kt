package io.github.themingverse.susecampus.update

import android.content.Intent
import android.net.Uri
import android.content.pm.PackageInfo
import android.content.pm.ApplicationInfo
import android.content.pm.Signature
import android.content.pm.SigningInfo
import android.provider.Settings
import androidx.core.content.FileProvider
import io.github.themingverse.susecampus.CampusApplication
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29, 34, 36], application = CampusApplication::class)
class AndroidUpdateTest {
    private val context get() = RuntimeEnvironment.getApplication() as CampusApplication
    @Before fun reset() { context.getSharedPreferences("update_settings", 0).edit().clear().commit() }
    @Test fun defaultChannelAndAllThreeChoicesPersistAcrossStoreInstances() {
        assertEquals(UpdateChannel.GITHUB, UpdateSettingsStore(context).load().channel)
        assertEquals(context.getString(io.github.themingverse.susecampus.R.string.update_gitee_repository), UpdateSettingsStore(context).load().giteeRepository)
        for (channel in UpdateChannel.entries) {
            UpdateSettingsStore(context).save(UpdateSettings(channel, "test-owner/test-repo"))
            assertEquals(UpdateSettings(channel, "test-owner/test-repo"), UpdateSettingsStore(context).load())
        }
    }
    @Test fun invalidRepositoryDoesNotReplaceSavedSettings() {
        val store = UpdateSettingsStore(context)
        store.save(UpdateSettings(UpdateChannel.GITHUB))
        expectUpdateError(UpdateError.SECURITY) { store.save(UpdateSettings(UpdateChannel.GITEE, "https://other.example/a/b")) }
        assertEquals(UpdateChannel.GITHUB, store.load().channel)
    }
    @Test fun automaticCheckPreferenceDefaultsOnAndPersistsWithoutChangingChannel() {
        val store = UpdateSettingsStore(context)
        assertTrue(store.load().checkOnOpen)
        store.save(UpdateSettings(UpdateChannel.AUTO, checkOnOpen = false))
        assertEquals(UpdateSettings(UpdateChannel.AUTO, checkOnOpen = false), UpdateSettingsStore(context).load())
    }
    @Test fun savedLegacyChannelIsPreservedWhenAddingAutomaticChecks() {
        context.getSharedPreferences("update_settings", 0).edit().putString("channel", "GITEE")
            .putString("gitee_repository", "test-owner/test-repo").commit()
        assertEquals(UpdateSettings(UpdateChannel.GITEE, "test-owner/test-repo", true), UpdateSettingsStore(context).load())
    }
    @Test fun promptNavigationTargetsRealPrivateUpdateActivityAndRequestsFreshCheck() {
        val prompted = updatePageIntent(context, true)
        assertEquals(UpdateActivity::class.java.name, prompted.component!!.className)
        assertTrue(prompted.getBooleanExtra(UpdateActivity.CHECK_ON_OPEN, false))
        assertFalse(updatePageIntent(context).getBooleanExtra(UpdateActivity.CHECK_ON_OPEN, false))
        assertEquals(setOf(UpdateActivity.CHECK_ON_OPEN), prompted.extras!!.keySet())
    }
    @Test fun lifecycleAdapterRecognizesHomeAndCancelsOnBackgroundWithoutNetworking() {
        UpdateSettingsStore(context).save(UpdateSettings(checkOnOpen = false))
        val adapter = AndroidForegroundUpdates(context)
        val home = io.github.themingverse.susecampus.MainActivity()
        adapter.onActivityStarted(home); adapter.onActivityResumed(home)
        assertTrue(adapter.checker.state.value.homeVisible)
        assertFalse(adapter.checker.state.value.checking)
        adapter.onActivityPaused(home); adapter.onActivityStopped(home)
        assertFalse(adapter.checker.state.value.homeVisible)
        assertFalse(adapter.checker.state.value.checking)
    }
    @Test fun lifecycleAdapterDoesNotTreatUpdatePageAsHome() {
        UpdateSettingsStore(context).save(UpdateSettings(checkOnOpen = false))
        val adapter = AndroidForegroundUpdates(context)
        val update = UpdateActivity()
        adapter.onActivityStarted(update); adapter.onActivityResumed(update)
        assertFalse(adapter.checker.state.value.homeVisible)
        adapter.onActivityPaused(update); adapter.onActivityStopped(update)
    }
    @Test fun applicationRegistersUpdateLifecycleAlongsideCampusLifecycle() {
        UpdateSettingsStore(context).save(UpdateSettings(checkOnOpen = false))
        val home = io.github.themingverse.susecampus.MainActivity()
        fun dispatch(method: String) = org.robolectric.util.ReflectionHelpers.callInstanceMethod<Void>(context, method,
            org.robolectric.util.ReflectionHelpers.ClassParameter.from(android.app.Activity::class.java, home))
        dispatch("dispatchActivityStarted"); dispatch("dispatchActivityResumed")
        assertTrue(context.updates.checker.state.value.homeVisible)
        dispatch("dispatchActivityPaused"); dispatch("dispatchActivityStopped")
        assertFalse(context.updates.checker.state.value.homeVisible)
    }
    @Test fun compiledTrustMatchesPublicConfigurationAndNotRemoteData() {
        val trust = AndroidUpdateTrust.load(context)
        assertEquals("io.github.themingverse.susecampus", trust.applicationId)
        assertEquals("TheMingverse/suse-campus-login", trust.githubRepository)
        assertEquals("d2311bc8eca941cefe1dfc8a75af476e3de5b230b4622a8820d6191af7452f36", trust.certificateSha256)
        assertEquals(InstalledVersion(requireNotNull(System.getProperty("suse.test.versionName")),
            requireNotNull(System.getProperty("suse.test.versionCode")).toLong()), AndroidUpdateTrust.installed(context))
    }
    private fun packageForInstall(): Pair<VerifiedApk, ApkVerifier> {
        val file = File(context.cacheDir, "updates/ready/test.apk").apply { parentFile!!.mkdirs(); writeBytes(byteArrayOf(1, 2, 3)) }
        val info = testRelease(size = file.length(), hash = fileSha256(file))
        val verifier = ApkVerifier(testTrust, ArchiveInspector { ArchiveIdentity(testTrust.applicationId, "0.4.0", 5, 29, listOf(testTrust.certificateSha256)) },
            { InstalledVersion("0.3.0", 4) }, 36)
        return VerifiedApk(file, info) to verifier
    }
    @Test fun missingInstallAuthorizationProducesOnlySettingsIntent() {
        val (apk, verifier) = packageForInstall()
        val installer = ApkInstaller(context, verifier) { false }
        assertFalse(installer.canInstall())
        assertEquals(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, installer.permissionIntent().action)
        assertEquals("package:${context.packageName}", installer.permissionIntent().data.toString())
        expectUpdateError(UpdateError.INSTALL) { installer.installIntent(apk) }
    }
    @Test fun grantedAuthorizationProducesContentUriAndReadOnlyGrant() {
        val (apk, verifier) = packageForInstall()
        var allowed = false
        // AndroidX FileProvider assumes Android '/' paths; the host JVM uses Windows '\\'.
        // Isolate only URI creation; permissions, containment, re-verification and Intent remain real.
        val installer = ApkInstaller(context, verifier, uriForFile = { Uri.parse("content://${context.packageName}.updates/verified_update/${it.name}") }) { allowed }
        assertFalse(installer.canInstall()); allowed = true; assertTrue(installer.canInstall())
        val intent = installer.installIntent(apk)
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals("content", intent.data!!.scheme)
        assertEquals("${context.packageName}.updates", intent.data!!.authority)
        assertEquals("application/vnd.android.package-archive", intent.type)
        assertTrue(intent.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
        assertEquals(0, intent.flags and Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
    }
    @Test fun unverifiedPartialDirectoryCannotBeShared() {
        val (valid, verifier) = packageForInstall()
        val partial = File(context.cacheDir, "updates/partial/unverified.part").apply { parentFile!!.mkdirs(); writeBytes(valid.file.readBytes()) }
        var shared = false
        val installer = ApkInstaller(context, verifier, uriForFile = { shared = true; Uri.parse("content://invalid") }) { true }
        expectUpdateError(UpdateError.SECURITY) { installer.installIntent(VerifiedApk(partial, valid.release)) }
        assertFalse(shared)
    }
    @Test fun providerConfigurationExposesOnlyVerifiedCacheFiles() {
        val parser = context.resources.getXml(io.github.themingverse.susecampus.R.xml.update_file_paths)
        val entries = mutableListOf<Pair<String, String?>>()
        while (parser.next() != org.xmlpull.v1.XmlPullParser.END_DOCUMENT) {
            if (parser.eventType == org.xmlpull.v1.XmlPullParser.START_TAG && parser.name != "paths")
                entries += parser.name to parser.getAttributeValue(null, "path")
        }
        parser.close()
        assertEquals(listOf("cache-path" to "updates/ready/"), entries)
    }
    @Test fun changedApkIsRejectedAndDeletedBeforeInstallation() {
        val (apk, verifier) = packageForInstall()
        apk.file.writeBytes(byteArrayOf(9, 8, 7))
        expectUpdateError(UpdateError.SECURITY) { ApkInstaller(context, verifier) { true }.installIntent(apk) }
        assertFalse(apk.file.exists())
    }
    @Test fun malformedRealArchiveHasNoInstallableIdentity() {
        val file = File(context.cacheDir, "malformed.apk").apply { writeText("not an APK") }
        expectUpdateError(UpdateError.SECURITY) { AndroidArchiveInspector(context).inspect(file) }
    }
    @Test fun archiveAdapterHashesFrameworkSigningCertificateAndReadsActualVersion() {
        val file = File(context.cacheDir, "synthetic-archive.apk").apply { writeText("framework mock only") }
        val certificate = byteArrayOf(1, 4, 9, 16)
        val signing = org.robolectric.util.ReflectionHelpers.newInstance(SigningInfo::class.java)
        shadowOf(signing).setSignatures(arrayOf(Signature(certificate)))
        val info = PackageInfo().apply {
            packageName = testTrust.applicationId; versionName = "0.4.0"; setLongVersionCode(5)
            applicationInfo = ApplicationInfo().apply { minSdkVersion = 29 }; signingInfo = signing
        }
        shadowOf(context.packageManager).setPackageArchiveInfo(file.absolutePath, info)
        val parsed = AndroidArchiveInspector(context).inspect(file)
        val expected = java.security.MessageDigest.getInstance("SHA-256").digest(certificate).joinToString("") { "%02x".format(it) }
        assertEquals(listOf(expected), parsed.certificateSha256)
        assertEquals(5L, parsed.versionCode); assertEquals("0.4.0", parsed.versionName); assertEquals(29, parsed.minSdk)
    }
    @Test fun archiveWithoutFrameworkSigningInfoIsRejected() {
        val file = File(context.cacheDir, "missing-certificate.apk").apply { writeText("framework mock only") }
        shadowOf(context.packageManager).setPackageArchiveInfo(file.absolutePath, PackageInfo().apply { packageName = testTrust.applicationId })
        expectUpdateError(UpdateError.SECURITY) { AndroidArchiveInspector(context).inspect(file) }
    }
    @Test fun actualPermissionAdapterRechecksSystemAuthorization() {
        val (_, verifier) = packageForInstall()
        val installer = ApkInstaller(context, verifier)
        shadowOf(context.packageManager).setCanRequestPackageInstalls(false)
        assertFalse(installer.canInstall())
        shadowOf(context.packageManager).setCanRequestPackageInstalls(true)
        assertTrue(installer.canInstall())
    }
}
