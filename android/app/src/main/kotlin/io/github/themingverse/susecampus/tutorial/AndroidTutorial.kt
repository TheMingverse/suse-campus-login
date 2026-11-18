package io.github.themingverse.susecampus.tutorial

import android.app.Application
import android.content.Context
import android.content.Intent
import androidx.core.content.edit
import androidx.core.net.toUri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle

class TutorialSettingsStore(context: Context) : TutorialPreferences {
    private val preferences = context.getSharedPreferences("usage_tutorial", Context.MODE_PRIVATE)
    override fun hasDismissed() = preferences.getBoolean("dismissed", false)
    override fun markDismissed() { preferences.edit(commit = true) { putBoolean("dismissed", true) } }
}

class TutorialViewModel(application: Application, saved: SavedStateHandle) : AndroidViewModel(application) {
    val controller = TutorialController(TutorialSettingsStore(application), restore(saved)) { state ->
        saved["tutorial.visible"] = state.visible
        saved["tutorial.mainPage"] = state.mainPage
        saved["tutorial.section"] = state.section.name
        saved["tutorial.detailPage"] = state.detailPage
        saved["tutorial.image"] = state.image?.name
        saved["tutorial.manual"] = state.manuallyOpened
    }
    private fun restore(saved: SavedStateHandle): TutorialState? = runCatching {
        if (!saved.contains("tutorial.visible")) null else TutorialState(
            visible = saved["tutorial.visible"] ?: true,
            mainPage = saved["tutorial.mainPage"] ?: 0,
            section = TutorialSection.valueOf(saved["tutorial.section"] ?: "MAIN"),
            detailPage = saved["tutorial.detailPage"] ?: 0,
            image = saved.get<String>("tutorial.image")?.let(TutorialImage::valueOf),
            manuallyOpened = saved["tutorial.manual"] ?: false,
        )
    }.getOrNull()
}

fun tutorialProjectIntent() = Intent(Intent.ACTION_VIEW, TutorialContent.PROJECT_URL.toUri())
