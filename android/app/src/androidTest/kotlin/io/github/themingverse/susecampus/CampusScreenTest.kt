package io.github.themingverse.susecampus

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import io.github.themingverse.susecampus.core.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class CampusScreenTest {
    @get:Rule val compose = createComposeRule()
    @Test fun phoneSetupHasNoInventedServiceAndSavesDraft() {
        var savedService: String? = null
        compose.setContent { MaterialTheme { Box(Modifier.width(390.dp)) {
            CampusContent(CampusUiState(loading = false), LoginStatus(), onSave = { _, _, service, _ -> savedService = service })
        } } }
        compose.onNodeWithText("校园网账号").performTextInput("synthetic-user")
        compose.onNodeWithText("校园网密码").performScrollTo().performTextInput("synthetic-secret")
        compose.onNodeWithText("保存加密草稿").performScrollTo().performClick()
        assertEquals("", savedService)
    }
    @Test fun permissionFailureOffersRecovery() {
        compose.setContent { MaterialTheme {
            CampusContent(CampusUiState(loading = false), LoginStatus(Stage.FAILED, safeMessage(Failure.PERMISSION)))
        } }
        compose.onNodeWithText("授予 Wi-Fi 识别权限").assertExists()
        compose.onNodeWithText("打开系统定位设置").assertExists()
    }
    @Test fun tabletMainPageShowsSavedServiceAndManualControl() {
        var checks = 0
        compose.setContent { MaterialTheme { Box(Modifier.width(1000.dp)) {
            CampusContent(CampusUiState(loading = false, editing = false, service = "测试服务", autoLogin = false),
                LoginStatus(Stage.ONLINE, "校园 Wi-Fi 已能上网，无需重复登录。"), onCheck = { checks++ })
        } } }
        compose.onNodeWithText("立即检查并登录").performClick()
        assertEquals(1, checks)
        compose.onNodeWithText("上网服务：测试服务").assertExists()
        compose.onNodeWithText("自动登录已关闭。").assertExists()
    }
}
