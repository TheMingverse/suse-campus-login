package io.github.themingverse.susecampus.tutorial

import org.junit.Assert.*
import org.junit.Test

class TutorialControllerTest {
    private class Memory(var dismissed: Boolean = false) : TutorialPreferences {
        var failRead = false
        var failWrite = false
        override fun hasDismissed(): Boolean { check(!failRead); return dismissed }
        override fun markDismissed() { check(!failWrite); dismissed = true }
    }

    @Test fun unseenInstallationShowsTheTutorialWithoutVersionOrAccountConditions() {
        assertTrue(TutorialController(Memory()).state.value.visible)
        assertFalse(TutorialController(Memory(true)).state.value.visible)
    }
    @Test fun closingOnceSurvivesNewControllerInstancesAndDoesNotDependOnVersion() {
        val memory = Memory()
        val first = TutorialController(memory)
        first.selectPage(2)
        first.close()
        assertTrue(memory.dismissed)
        assertFalse(first.state.value.blocksUpdatePrompt)
        assertFalse(TutorialController(memory).state.value.visible)
    }
    @Test fun topEntryAlwaysStartsAtTheBeginningAfterDismissal() {
        val controller = TutorialController(Memory(true))
        controller.open(); controller.selectPage(4); controller.close(); controller.open()
        assertEquals(TutorialState(manuallyOpened = true), controller.state.value)
    }
    @Test fun systemBackExitsImageThenDetailsThenTheMainTutorial() {
        val memory = Memory()
        val controller = TutorialController(memory)
        controller.selectPage(4)
        controller.detail(TutorialSection.WIDGET)
        controller.selectPage(2)
        controller.enlarge(TutorialImage.WIDGET_ANDROID)
        controller.back()
        assertNull(controller.state.value.image)
        assertEquals(2, controller.state.value.detailPage)
        assertFalse(memory.dismissed)
        controller.back()
        assertEquals(TutorialSection.MAIN, controller.state.value.section)
        assertEquals(4, controller.state.value.mainPage)
        assertFalse(memory.dismissed)
        controller.back()
        assertTrue(memory.dismissed)
        assertFalse(controller.state.value.visible)
    }
    @Test fun explicitCloseFromAnyDetailEndsTheWholeTutorial() {
        val memory = Memory()
        val controller = TutorialController(memory)
        controller.detail(TutorialSection.TILE)
        controller.enlarge(TutorialImage.TILE_EDIT)
        controller.close()
        assertTrue(memory.dismissed)
        assertFalse(controller.state.value.visible)
        assertNull(controller.state.value.image)
    }
    @Test fun unfinishedReadingRestoresPageDetailAndImageAfterRecreation() {
        val memory = Memory()
        var saved: TutorialState? = null
        val first = TutorialController(memory, saveState = { saved = it })
        first.selectPage(4); first.detail(TutorialSection.WIDGET); first.selectPage(3)
        first.enlarge(TutorialImage.WIDGET_PICKER)
        assertEquals(first.state.value, TutorialController(memory, saved).state.value)
        assertFalse(memory.dismissed)
    }
    @Test fun persistedDismissalOverridesStaleAutomaticSavedState() {
        assertFalse(TutorialController(Memory(true), TutorialState(mainPage = 3)).state.value.visible)
    }
    @Test fun manualReadingCanBeRestoredEvenWhenAlreadyDismissed() {
        val reading = TutorialState(mainPage = 5, manuallyOpened = true)
        assertEquals(reading, TutorialController(Memory(true), reading).state.value)
    }
    @Test fun outOfRangeRestoredPagesAreClampedAndDetailsNeverChangeMainPosition() {
        val controller = TutorialController(Memory(), TutorialState(mainPage = 999))
        assertEquals(5, controller.state.value.mainPage)
        controller.selectPage(-100)
        controller.detail(TutorialSection.WIDGET); controller.selectPage(999)
        assertEquals(0, controller.state.value.mainPage)
        assertEquals(4, controller.state.value.detailPage)
    }
    @Test fun storageProblemsNeverTrapTheUserInAnOverlay() {
        val memory = Memory().apply { failRead = true; failWrite = true }
        val controller = TutorialController(memory)
        assertTrue(controller.state.value.visible)
        controller.close()
        assertFalse(controller.state.value.visible)
        assertTrue(TutorialController(memory).state.value.visible)
    }
    @Test fun hiddenTutorialIgnoresStalePagingAndImageEvents() {
        val controller = TutorialController(Memory(true))
        val original = controller.state.value
        controller.selectPage(4); controller.detail(TutorialSection.WIDGET)
        controller.enlarge(TutorialImage.ACCOUNT); controller.back()
        assertEquals(original, controller.state.value)
    }
    @Test fun everyScreenshotHasOneDefinedRoleAndOnlySixMainPagesAreRequired() {
        assertEquals(6, TutorialContent.main.size)
        assertEquals(5, TutorialContent.widget.size)
        val pages = TutorialContent.main + TutorialContent.tile + TutorialContent.widget
        assertEquals(TutorialImage.entries.toSet(), pages.mapNotNull { it.image }.toSet())
        assertEquals(10, pages.mapNotNull { it.image }.size)
        assertTrue(TutorialContent.main.first().paragraphs.any { "保存账号草稿" in it })
        assertTrue(TutorialContent.main.last().showProject)
    }
}
