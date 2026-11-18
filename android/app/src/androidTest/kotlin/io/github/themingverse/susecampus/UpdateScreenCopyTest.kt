package io.github.themingverse.susecampus

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import io.github.themingverse.susecampus.update.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class UpdateScreenCopyTest {
    @get:Rule val compose = createComposeRule()
    private val release = ReleaseInfo("io.github.themingverse.susecampus", "0.4.2", 7, "android-v0.4.2",
        "测试更新内容", "SUSE-CampusLogin-Android-v0.4.2-release.apk", 1048576, "ab".repeat(32),
        "https://example.invalid/synthetic.apk".toHttpUrl(), UpdateChannel.GITHUB, 29)

    private fun show(state: UpdateUiState, download: () -> Unit = {}, install: () -> Unit = {}) {
        compose.setContent { MaterialTheme {
            UpdateScreen(state, { _, _, _ -> }, {}, download, {}, install, {}, {})
        } }
    }
    @Test fun currentVersionHidesReleaseDetailsAndTechnicalExplanations() {
        show(UpdateUiState(UpdateSettings(), InstalledVersion("0.4.2", 7), release = release,
            actualSource = UpdateChannel.GITHUB, message = "当前已是最新版本。"))
        compose.onNodeWithText("当前已是最新版本。").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("更新日志").assertDoesNotExist()
        compose.onNodeWithText("测试更新内容").assertDoesNotExist()
        compose.onNodeWithText("android-v0.4.2", substring = true).assertDoesNotExist()
        compose.onNodeWithText("本次连接来源", substring = true).assertDoesNotExist()
        compose.onNodeWithText("Gitee 尚未配置。").assertDoesNotExist()
        compose.onNodeWithText("当前版本：0.4.2").assertExists()
        compose.onNodeWithText("当前版本：0.4.2（7）").assertDoesNotExist()
    }
    @Test fun newerVersionKeepsNotesAndTheDownloadConfirmation() {
        var downloads = 0
        show(UpdateUiState(UpdateSettings(), InstalledVersion("0.4.1", 6), release = release,
            available = true, message = "发现新版本。"), download = { downloads++ })
        compose.onNodeWithText("测试更新内容").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("下载更新").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(0, downloads) }
        compose.onNodeWithText("取消").performClick()
        compose.runOnIdle { assertEquals(0, downloads) }
        compose.onNodeWithText("下载更新").performClick()
        compose.onNodeWithText("确认下载").performClick()
        compose.runOnIdle { assertEquals(1, downloads) }
    }
    @Test fun readyUpdateKeepsInstallAndAuthorizationActions() {
        var installations = 0
        show(UpdateUiState(UpdateSettings(), InstalledVersion("0.4.1", 6), release = release,
            available = true, ready = true, permissionNeeded = true, message = "下载完成，可以安装。"),
            install = { installations++ })
        compose.onNodeWithText("安装更新").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, installations) }
        compose.onNodeWithText("打开安装授权设置").performScrollTo().assertIsDisplayed()
    }
    @Test fun unsavedChannelShowsOnlyRelevantConfigurationHints() {
        show(UpdateUiState(UpdateSettings(), InstalledVersion("0.4.1", 6)))
        compose.onNodeWithText("已保存渠道", substring = true).assertDoesNotExist()
        compose.onNodeWithText("Gitee 国内镜像").performClick()
        compose.onNodeWithText("Gitee 尚未配置。").assertExists()
        compose.onNodeWithText("已保存渠道：GitHub 官方渠道").assertExists()
        compose.onAllNodesWithText("检查更新").filter(hasClickAction()).onFirst().assertIsNotEnabled()
    }
}
