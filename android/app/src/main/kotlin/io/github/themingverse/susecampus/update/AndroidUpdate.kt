package io.github.themingverse.susecampus.update

import android.content.Context
import android.content.Intent
import android.content.ClipData
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import io.github.themingverse.susecampus.R
import java.io.File
import java.security.MessageDigest

class UpdateSettingsStore(context: Context) {
    private val preferences = context.getSharedPreferences("update_settings", Context.MODE_PRIVATE)
    private val defaultGitee = context.getString(R.string.update_gitee_repository)
    fun load(): UpdateSettings {
        val channel = runCatching { UpdateChannel.valueOf(preferences.getString("channel", "GITHUB")!!) }.getOrDefault(UpdateChannel.GITHUB)
        val repository = preferences.getString("gitee_repository", defaultGitee) ?: ""
        return UpdateSettings(channel, UpdateFormat.repository(repository), preferences.getBoolean("check_on_open", true))
    }
    fun save(settings: UpdateSettings) {
        val repository = UpdateFormat.repository(settings.giteeRepository)
        if (!preferences.edit().putString("channel", settings.channel.name).putString("gitee_repository", repository)
                .putBoolean("check_on_open", settings.checkOnOpen).commit())
            throw UpdateException(UpdateError.STORAGE, "无法保存更新设置，请重试。")
    }
    fun observe(listener: android.content.SharedPreferences.OnSharedPreferenceChangeListener) {
        preferences.registerOnSharedPreferenceChangeListener(listener)
    }
}
object AndroidUpdateTrust {
    fun load(context: Context) = UpdateTrust(context.getString(R.string.update_application_id),
        context.getString(R.string.update_github_repository), context.getString(R.string.update_certificate_sha256))
    @Suppress("DEPRECATION")
    fun installed(context: Context): InstalledVersion {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        return InstalledVersion(info.versionName ?: "未知", info.longVersionCode)
    }
}

class AndroidArchiveInspector(private val context: Context) : ArchiveInspector {
    @Suppress("DEPRECATION")
    override fun inspect(file: File): ArchiveIdentity {
        val info = context.packageManager.getPackageArchiveInfo(file.absolutePath, PackageManager.GET_SIGNING_CERTIFICATES)
            ?: throw UpdateException(UpdateError.SECURITY, "安装包校验失败，无法安装。")
        val signers = info.signingInfo?.apkContentsSigners
            ?: throw UpdateException(UpdateError.SECURITY, "安装包校验失败，无法安装。")
        return ArchiveIdentity(info.packageName, info.versionName ?: "", info.longVersionCode,
            info.applicationInfo?.minSdkVersion ?: Int.MAX_VALUE, signers.map {
                MessageDigest.getInstance("SHA-256").digest(it.toByteArray()).joinToString("") { byte -> "%02x".format(byte) }
            })
    }
}

/** The OS performs the final cryptographic APK validation and always asks the user to install. */
class ApkInstaller(private val context: Context, private val verifier: ApkVerifier,
                   private val uriForFile: (File) -> Uri = { FileProvider.getUriForFile(context, "${context.packageName}.updates", it) },
                   private val allowed: () -> Boolean = { context.packageManager.canRequestPackageInstalls() }) {
    fun canInstall() = allowed()
    fun permissionIntent() = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
    fun installIntent(apk: VerifiedApk): Intent {
        if (!allowed()) throw UpdateException(UpdateError.INSTALL, "请在系统设置中允许本应用安装更新。")
        val ready = File(context.cacheDir, "updates/ready").canonicalFile
        security(apk.file.canonicalFile.parentFile == ready, "安装文件无效，请重新下载。")
        try { verifier.verify(apk.file, apk.release) }
        catch (e: Exception) { apk.file.delete(); throw e }
        val uri = uriForFile(apk.file)
        security(uri.scheme == "content" && uri.authority == "${context.packageName}.updates", "安装文件无效，请重新下载。")
        return Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION).apply { clipData = ClipData.newRawUri("APK", uri) }
    }
}
