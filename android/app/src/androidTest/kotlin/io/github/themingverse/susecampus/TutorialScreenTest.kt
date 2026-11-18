package io.github.themingverse.susecampus

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import io.github.themingverse.susecampus.update.*
import io.github.themingverse.susecampus.core.LoginStatus
import io.github.themingverse.susecampus.tutorial.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import kotlinx.coroutines.*
import okhttp3.HttpUrl.Companion.toHttpUrl

/** Device UI tests. The pure content host never authenticates or contacts an update source. */
class TutorialScreenTest {
    @get:Rule val compose = createComposeRule()
    private class Memory : TutorialPreferences {
        var dismissed = false
        override fun hasDismissed() = dismissed
        override fun markDismissed() { dismissed = true }
    }
    private fun show(controller: TutorialController, project: () -> Unit = {}) {
        compose.setContent {
            MaterialTheme {
                val state by controller.state.collectAsState()
                CampusContent(CampusUiState(loading = false, editing = false), LoginStatus(), onTutorial = controller::open)
                if (state.visible) TutorialDialog(state, controller, project)
            }
        }
    }
    @Test fun swipeAndButtonsNavigateWithoutHidingTheFooter() {
        show(TutorialController(Memory()))
        compose.onNodeWithText("1 / 6").assertIsDisplayed()
        compose.onNodeWithTag("tutorial-pager").performTouchInput { swipeLeft() }
        compose.onNodeWithText("2 / 6").assertIsDisplayed()
        compose.onNodeWithText("上一步").performClick()
        compose.onNodeWithText("1 / 6").assertIsDisplayed()
        compose.onNodeWithText("下一步").performClick()
        compose.onNodeWithText("填写你的校园网账号").assertIsDisplayed()
    }
    @Test fun closingAndTopEntryReopenTheGuideAtPageOne() {
        val memory = Memory()
        val controller = TutorialController(memory)
        show(controller)
        compose.onNodeWithText("关闭教程").performClick()
        compose.onNodeWithText("首次配置前，先看这里").assertDoesNotExist()
        compose.onNodeWithText("使用教程").performClick()
        compose.onNodeWithText("1 / 6").assertIsDisplayed()
        compose.runOnIdle { assertTrue(memory.dismissed) }
    }
    @Test fun widgetDetailsAndZoomReturnToTheOriginalMainPage() {
        val controller = TutorialController(Memory()).apply { selectPage(4) }
        show(controller)
        compose.onNodeWithText("查看手动添加图解").performScrollTo().performClick()
        compose.onNodeWithText("1 / 5").assertIsDisplayed()
        compose.onNodeWithTag("tutorial-image-WIDGET_DESKTOP").performScrollTo().performClick()
        compose.onNodeWithText("放大").performClick()
        compose.onNodeWithText("150%").assertIsDisplayed()
        compose.onNodeWithText("关闭大图").performClick()
        compose.runOnIdle { controller.back() }
        compose.onNodeWithText("5 / 6").assertIsDisplayed()
    }
    @Test fun thanksPageOnlyOpensTheProjectOnAnExplicitClick() {
        val memory = Memory()
        var openings = 0
        val controller = TutorialController(memory).apply { selectPage(5) }
        show(controller) { openings++ }
        compose.onNodeWithText("前往 GitHub 点 Star").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, openings); assertFalse(memory.dismissed) }
        compose.onNodeWithText("开始使用").performClick()
        compose.runOnIdle { assertTrue(memory.dismissed); assertFalse(controller.state.value.visible) }
    }
    @Test fun homeTutorialEntryRemainsVisibleAfterScrollingTheBody() {
        var openings = 0
        compose.setContent { MaterialTheme {
            CampusContent(CampusUiState(loading = false, editing = false), LoginStatus(), onTutorial = { openings++ })
        } }
        compose.onNodeWithText("更新设置与关于").performScrollTo()
        compose.onNodeWithText("使用教程").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(1, openings) }
    }
    @Test fun largeFontsKeepCloseAndNavigationReachable() {
        val controller = TutorialController(Memory())
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, 2f)) {
                MaterialTheme {
                    val state by controller.state.collectAsState()
                    if (state.visible) TutorialDialog(state, controller, {})
                }
            }
        }
        compose.onNodeWithText("关闭教程").assertIsDisplayed()
        compose.onNodeWithText("下一步").assertIsDisplayed().performClick()
        compose.onNodeWithText("2 / 6").assertIsDisplayed()
    }
    @Test fun updatePromptWaitsUntilTheTutorialCloses() {
        val controller = TutorialController(Memory())
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
        val release = ReleaseInfo("io.github.themingverse.susecampus", "0.4.2", 7, "android-v0.4.2",
            "Synthetic local update test", "SUSE-CampusLogin-Android-v0.4.2-release.apk", 100, "ab".repeat(32),
            "https://example.invalid/synthetic.apk".toHttpUrl(), UpdateChannel.GITHUB, 29)
        val checker = ForegroundUpdateChecker(scope, { UpdateSettings() }, { InstalledVersion("0.4.1", 6) }, 36, { release })
        try {
            compose.setContent { MaterialTheme {
                val state by controller.state.collectAsState()
                if (state.visible) TutorialDialog(state, controller, {})
                HomeUpdateNotice(checker, state.blocksUpdatePrompt, {})
            } }
            compose.runOnIdle { checker.foreground(); checker.homeResumed() }
            compose.onNodeWithText("发现新版本").assertDoesNotExist()
            compose.onNodeWithText("关闭教程").performClick()
            compose.onNodeWithText("发现新版本").assertIsDisplayed()
        } finally { compose.runOnIdle { scope.cancel() } }
    }
}
