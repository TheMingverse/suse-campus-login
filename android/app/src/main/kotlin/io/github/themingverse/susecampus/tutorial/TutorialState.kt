package io.github.themingverse.susecampus.tutorial

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

interface TutorialPreferences {
    fun hasDismissed(): Boolean
    fun markDismissed()
}

data class TutorialState(
    val visible: Boolean = true,
    val mainPage: Int = 0,
    val section: TutorialSection = TutorialSection.MAIN,
    val detailPage: Int = 0,
    val image: TutorialImage? = null,
    val manuallyOpened: Boolean = false,
) {
    val currentPage get() = if (section == TutorialSection.MAIN) mainPage else detailPage
    val blocksUpdatePrompt get() = visible
    fun normalized() = copy(
        mainPage = mainPage.coerceIn(TutorialContent.main.indices),
        detailPage = detailPage.coerceIn(TutorialContent.pages(section).indices),
    )
}

/** No account, authentication, update transport, Activity or image decoding dependencies. */
class TutorialController(
    private val preferences: TutorialPreferences,
    restored: TutorialState? = null,
    private val saveState: (TutorialState) -> Unit = {},
) {
    private val dismissed = runCatching { preferences.hasDismissed() }.getOrDefault(false)
    private val initial = restored?.normalized()?.let {
        if (dismissed && !it.manuallyOpened) it.copy(visible = false, image = null) else it
    } ?: TutorialState(visible = !dismissed)
    private val mutable = MutableStateFlow(initial)
    val state = mutable.asStateFlow()
    private fun update(value: TutorialState) { mutable.value = value; saveState(value) }

    fun open() = update(TutorialState(manuallyOpened = true))
    fun selectPage(page: Int) {
        val value = state.value
        if (!value.visible) return
        val selected = page.coerceIn(TutorialContent.pages(value.section).indices)
        update(if (value.section == TutorialSection.MAIN) value.copy(mainPage = selected) else value.copy(detailPage = selected))
    }
    fun detail(section: TutorialSection) {
        if (!state.value.visible || section == TutorialSection.MAIN) return
        update(state.value.copy(section = section, detailPage = 0, image = null))
    }
    fun enlarge(image: TutorialImage) {
        if (state.value.visible) update(state.value.copy(image = image))
    }
    fun back() {
        val value = state.value
        when {
            !value.visible -> Unit
            value.image != null -> update(value.copy(image = null))
            value.section != TutorialSection.MAIN -> update(value.copy(section = TutorialSection.MAIN, detailPage = 0))
            else -> close()
        }
    }
    fun close() {
        // A storage error must not trap the user in the tutorial. A future launch can retry it.
        runCatching { preferences.markDismissed() }
        update(state.value.copy(visible = false, image = null, section = TutorialSection.MAIN))
    }
}
