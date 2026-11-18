package io.github.themingverse.susecampus.tutorial

import android.content.Intent
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelProvider
import io.github.themingverse.susecampus.CampusApplication
import io.github.themingverse.susecampus.MainActivity
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Robolectric
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29, 34, 36], application = CampusApplication::class)
class AndroidTutorialTest {
    private val context get() = RuntimeEnvironment.getApplication() as CampusApplication
    @Before fun clearTutorial() { context.getSharedPreferences("usage_tutorial", 0).edit().clear().commit() }

    @Test fun upgradedUserWithExistingAccountAndUpdateSettingsStillSeesItOnce() {
        val account = File(context.noBackupFilesDir, "account.enc")
        val encryptedFixture = byteArrayOf(2, 7, 11, 31)
        account.writeBytes(encryptedFixture)
        val updates = context.getSharedPreferences("update_settings", 0)
        updates.edit().putString("channel", "GITHUB").putBoolean("check_on_open", false).commit()
        val controller = TutorialController(TutorialSettingsStore(context))
        assertTrue(controller.state.value.visible)
        controller.close()
        assertFalse(TutorialController(TutorialSettingsStore(context)).state.value.visible)
        assertArrayEquals(encryptedFixture, account.readBytes())
        assertEquals("GITHUB", updates.getString("channel", ""))
        assertFalse(updates.getBoolean("check_on_open", true))
        account.delete()
    }
    @Test fun savedStateRestoresUnfinishedMainDetailAndImageAcrossViewModels() {
        val saved = SavedStateHandle()
        val first = TutorialViewModel(context, saved).controller
        first.selectPage(4); first.detail(TutorialSection.WIDGET); first.selectPage(3)
        first.enlarge(TutorialImage.WIDGET_PICKER)
        assertEquals(first.state.value, TutorialViewModel(context, saved).controller.state.value)
        assertFalse(TutorialSettingsStore(context).hasDismissed())
    }
    @Test fun closedAndManuallyReopenedStateHasCorrectRestorationPriority() {
        val saved = SavedStateHandle()
        val first = TutorialViewModel(context, saved).controller
        first.close()
        assertFalse(TutorialViewModel(context, saved).controller.state.value.visible)
        first.open(); first.selectPage(2)
        assertEquals(first.state.value, TutorialViewModel(context, saved).controller.state.value)
    }
    @Test fun malformedSavedNavigationFallsBackToSafeTutorialState() {
        val saved = SavedStateHandle(mapOf("tutorial.visible" to true, "tutorial.section" to "UNKNOWN"))
        assertEquals(TutorialState(), TutorialViewModel(context, saved).controller.state.value)
    }
    @Test fun allBundledImagesAreReadableOfflineJpegs() {
        for (image in TutorialImage.entries) {
            context.resources.openRawResource(image.resource).use { input ->
                assertEquals(0xff, input.read()); assertEquals(0xd8, input.read())
            }
        }
    }
    @Test fun projectIntentOnlyOpensTheFixedPublicProjectPage() {
        val intent = tutorialProjectIntent()
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals(TutorialContent.PROJECT_URL, intent.dataString)
        assertNull(intent.extras)
    }
    @Test @Config(sdk = [34]) fun realHomeActivityUsesTheSavedStateViewModelAndKeepsDismissalOnRecreation() {
        context.getSharedPreferences("update_settings", 0).edit().putBoolean("check_on_open", false).commit()
        val activity = Robolectric.buildActivity(MainActivity::class.java).setup()
        try {
            val controller = ViewModelProvider(activity.get())[TutorialViewModel::class.java].controller
            assertTrue(controller.state.value.visible)
            controller.close()
            activity.recreate()
            assertFalse(ViewModelProvider(activity.get())[TutorialViewModel::class.java].controller.state.value.visible)
        } finally { activity.pause().stop().destroy() }
    }
}
