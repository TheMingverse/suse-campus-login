package io.github.themingverse.susecampus.update

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun HomeUpdateNotice(checker: ForegroundUpdateChecker, blocked: Boolean, viewUpdate: () -> Unit) {
    val state by checker.state.collectAsStateWithLifecycle()
    if (state.showPrompt(blocked)) {
        val release = state.release!!
        AlertDialog(onDismissRequest = checker::dismiss,
            title = { Text("发现新版本") },
            text = { Text("新版本 ${release.versionName} 已发布。") },
            confirmButton = { TextButton(onClick = { checker.dismiss(); viewUpdate() }) { Text("查看更新") } },
            dismissButton = { TextButton(onClick = checker::dismiss) { Text("稍后") } })
    }
}
