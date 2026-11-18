package io.github.themingverse.susecampus.update

import android.app.Activity
import android.app.Application
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.themingverse.susecampus.CampusApplication
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

data class UpdateUiState(
    val settings: UpdateSettings, val current: InstalledVersion, val release: ReleaseInfo? = null,
    val available: Boolean = false, val busy: Boolean = false, val downloading: Boolean = false,
    val progress: DownloadProgress? = null, val actualSource: UpdateChannel? = null,
    val message: String = "",
    val error: UpdateError? = null, val ready: Boolean = false, val permissionNeeded: Boolean = false,
)

class UpdateViewModel(application: Application) : AndroidViewModel(application) {
    private val store = UpdateSettingsStore(application)
    private val trust = AndroidUpdateTrust.load(application)
    private val transport = UpdateHttp()
    private val verifier = ApkVerifier(trust, AndroidArchiveInspector(application), { AndroidUpdateTrust.installed(application) }, Build.VERSION.SDK_INT)
    private val downloader = ApkDownloader(transport, application.cacheDir, verifier)
    private val installer = ApkInstaller(application, verifier)
    private val mutable = MutableStateFlow(UpdateUiState(runCatching { store.load() }.getOrDefault(UpdateSettings()), AndroidUpdateTrust.installed(application)))
    val ui = mutable.asStateFlow()
    private var work: Job? = null
    private var verified: VerifiedApk? = null
    private var awaitingPermission = false

    private val cleanup = viewModelScope.launch(Dispatchers.IO) {
        // Process restart never trusts an old ready file; this runs before any user download.
        for (directory in listOf("updates/partial", "updates/ready")) {
            java.io.File(application.cacheDir, directory).listFiles()?.filter { it.isFile }?.forEach { it.delete() }
        }
    }
    private fun repository() = updateRepository(ui.value.settings, trust, transport) { source ->
        mutable.update { it.copy(actualSource = source) }
    }
    private fun clearReady() { verified?.file?.delete(); verified = null; awaitingPermission = false }
    private fun launch(block: suspend () -> Unit) {
        if (work?.isActive == true) return
        mutable.update { it.copy(busy = true, error = null, permissionNeeded = false) }
        work = viewModelScope.launch {
            try { cleanup.join(); block() }
            catch (e: CancellationException) { mutable.update { it.copy(message = "已取消。") }; throw e }
            catch (e: UpdateException) {
                clearReady()
                mutable.update { it.copy(message = e.message, error = e.kind, ready = false,
                    release = if (e.kind == UpdateError.SECURITY) null else it.release,
                    available = if (e.kind == UpdateError.SECURITY) false else it.available) }
            } catch (_: Exception) { clearReady(); mutable.update { it.copy(message = "更新操作未完成，请重新检查更新。", error = UpdateError.SERVICE, ready = false) } }
            finally { mutable.update { it.copy(busy = false, downloading = false) } }
        }
    }
    fun saveSettings(channel: UpdateChannel, repository: String, checkOnOpen: Boolean) = launch {
        val settings = UpdateSettings(channel, UpdateFormat.repository(repository), checkOnOpen)
        withContext(Dispatchers.IO) { store.save(settings) }
        clearReady()
        mutable.value = UpdateUiState(settings, ui.value.current, message = "设置已保存。")
    }
    fun check() = launch {
        clearReady()
        mutable.update { it.copy(release = null, ready = false, available = false, progress = null, actualSource = null, message = "正在检查更新…") }
        val info = repository().latest()
        if (info == null) mutable.update { it.copy(message = "暂无可用的更新信息。") }
        else {
            val decision = UpdateChecker.compare(ui.value.current, info)
            val supported = info.minSdk <= Build.VERSION.SDK_INT
            mutable.update { it.copy(release = info, actualSource = info.channel, available = decision == VersionDecision.AVAILABLE && supported,
                message = if (decision == VersionDecision.CURRENT) "当前已是最新版本。" else if (!supported)
                    "新版暂不支持当前系统。" else "发现新版本。") }
        }
    }
    fun download() = launch {
        val info = ui.value.release ?: return@launch
        if (!ui.value.available) return@launch
        clearReady()
        mutable.update { it.copy(downloading = true, ready = false, progress = null, message = "正在下载更新…") }
        val repository = repository()
        fun progress(value: DownloadProgress) { mutable.update { it.copy(progress = value, actualSource = value.source) } }
        verified = try { downloader.download(info, ::progress) }
            catch (e: UpdateException) {
                val fallback = repository.fallbackDownload(info, e)
                mutable.update { it.copy(release = fallback, actualSource = fallback.channel, message = "正在改用 GitHub 下载…") }
                downloader.download(fallback, ::progress)
            }
        mutable.update { it.copy(ready = true, message = "下载完成，可以安装。") }
    }
    fun install(activity: Activity) = launch {
        val apk = verified ?: return@launch
        if (!installer.canInstall()) {
            mutable.update { it.copy(permissionNeeded = true, message = "请在系统设置中允许本应用安装更新。") }
            return@launch
        }
        val intent = withContext(Dispatchers.IO) { installer.installIntent(apk) }
        (getApplication<Application>() as CampusApplication).externalFlow()
        try { activity.startActivity(intent); mutable.update { it.copy(message = "请在系统界面确认安装。") } }
        catch (_: Exception) { throw UpdateException(UpdateError.INSTALL, "系统安装器无法打开，请稍后重试。") }
    }
    fun requestPermission(activity: Activity) {
        if (verified == null || ui.value.busy) return
        awaitingPermission = true
        (getApplication<Application>() as CampusApplication).externalFlow()
        try { activity.startActivity(installer.permissionIntent()) }
        catch (_: Exception) { awaitingPermission = false; mutable.update { it.copy(message = "请在系统设置中允许本应用安装更新。") } }
    }
    fun permissionReturned(activity: Activity) {
        if (!awaitingPermission) return
        awaitingPermission = false
        if (installer.canInstall()) install(activity)
        else mutable.update { it.copy(permissionNeeded = true, message = "尚未获得安装权限。") }
    }
    fun cancel() { work?.cancel() }
    override fun onCleared() { work?.cancel(); clearReady(); super.onCleared() }
}
