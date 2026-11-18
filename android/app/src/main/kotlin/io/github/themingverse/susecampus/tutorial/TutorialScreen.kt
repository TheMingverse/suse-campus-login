package io.github.themingverse.susecampus.tutorial

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun TutorialDialog(state: TutorialState, controller: TutorialController, openProject: () -> Unit) {
    val readingState = rememberSaveableStateHolder()
    Dialog(onDismissRequest = controller::back,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Box(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).padding(12.dp), contentAlignment = Alignment.Center) {
            Surface(Modifier.widthIn(max = 960.dp).fillMaxSize(), shape = MaterialTheme.shapes.extraLarge,
                tonalElevation = 6.dp) {
                if (state.image != null) TutorialImageViewer(state.image, controller::back)
                else Column {
                    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 8.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Text(when (state.section) {
                            TutorialSection.MAIN -> "使用教程"
                            TutorialSection.TILE -> "磁贴手动添加"
                            TutorialSection.WIDGET -> "小组件手动添加"
                        }, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                        TextButton(onClick = controller::close) { Text("关闭教程") }
                    }
                    if (state.section != TutorialSection.MAIN) {
                        TextButton(onClick = controller::back, modifier = Modifier.padding(horizontal = 8.dp)) { Text("返回主教程") }
                    }
                    HorizontalDivider()
                    key(state.section) {
                        readingState.SaveableStateProvider(state.section.name) {
                            TutorialPager(state.section, state.currentPage, controller::selectPage,
                                controller::enlarge, controller::detail, controller::close, controller::back, openProject)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ColumnScope.TutorialPager(
    section: TutorialSection, initialPage: Int, selected: (Int) -> Unit,
    enlarge: (TutorialImage) -> Unit, detail: (TutorialSection) -> Unit,
    close: () -> Unit, back: () -> Unit, openProject: () -> Unit,
) {
    val pages = TutorialContent.pages(section)
    val pager = rememberPagerState(initialPage = initialPage, pageCount = { pages.size })
    val scope = rememberCoroutineScope()
    val onSelected by rememberUpdatedState(selected)
    LaunchedEffect(pager) {
        snapshotFlow { pager.settledPage }.distinctUntilChanged().collect { onSelected(it) }
    }
    HorizontalPager(pager, modifier = Modifier.weight(1f).fillMaxWidth().testTag("tutorial-pager"),
        beyondViewportPageCount = 0, verticalAlignment = Alignment.Top) { index ->
        val page = pages[index]
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(page.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
            page.paragraphs.forEachIndexed { paragraphIndex, text ->
                if (section == TutorialSection.MAIN && index == 0 && paragraphIndex == 0) {
                    Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.large) {
                        Text(text, Modifier.padding(16.dp), fontWeight = FontWeight.SemiBold)
                    }
                } else Text(text, style = MaterialTheme.typography.bodyLarge)
            }
            page.image?.let { TutorialImagePreview(it, enlarge) }
            page.detail?.let { target ->
                OutlinedButton(onClick = { detail(target) }, modifier = Modifier.fillMaxWidth()) { Text(page.detailLabel) }
            }
            if (page.showProject) {
                androidx.compose.foundation.text.selection.SelectionContainer {
                    Text(TutorialContent.PROJECT_URL, style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.primary)
                }
                OutlinedButton(onClick = openProject, modifier = Modifier.fillMaxWidth()) { Text("前往 GitHub 点 Star") }
            }
            Spacer(Modifier.height(4.dp))
        }
    }
    HorizontalDivider()
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("${pager.currentPage + 1} / ${pages.size}", style = MaterialTheme.typography.labelLarge,
            modifier = Modifier.testTag("tutorial-page-number"))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedButton(onClick = { scope.launch { pager.animateScrollToPage(pager.currentPage - 1) } },
                enabled = pager.currentPage > 0 && !pager.isScrollInProgress, modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp)) { Text("上一步") }
            val last = pager.currentPage == pages.lastIndex
            Button(onClick = {
                if (last) { if (section == TutorialSection.MAIN) close() else back() }
                else scope.launch { pager.animateScrollToPage(pager.currentPage + 1) }
            }, enabled = !pager.isScrollInProgress, modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp)) {
                Text(if (!last) "下一步" else if (section == TutorialSection.MAIN) "开始使用" else "返回主教程")
            }
        }
    }
}

/** Preview resources are sampled to the visible area; only composed pager pages decode images. */
@Composable
private fun sampledBitmap(image: TutorialImage, width: Int, height: Int): Bitmap? {
    val resources = LocalResources.current
    val value by produceState<Bitmap?>(null, image, width, height, resources) {
        value = withContext(Dispatchers.IO) {
            runCatching {
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeResource(resources, image.resource, bounds)
                val options = BitmapFactory.Options()
                val shrink = maxOf(bounds.outWidth.toFloat() / width.coerceAtLeast(1),
                    bounds.outHeight.toFloat() / height.coerceAtLeast(1))
                while (options.inSampleSize.coerceAtLeast(1) * 2 <= shrink) {
                    options.inSampleSize = options.inSampleSize.coerceAtLeast(1) * 2
                }
                BitmapFactory.decodeResource(resources, image.resource, options)
            }.getOrNull()
        }
    }
    return value
}

@Composable
private fun TutorialImagePreview(image: TutorialImage, enlarge: (TutorialImage) -> Unit) {
    OutlinedCard(onClick = { enlarge(image) }, modifier = Modifier.fillMaxWidth()
        .testTag("tutorial-image-${image.name}")
        .semantics { contentDescription = "查看大图：${image.description}" }) {
        BoxWithConstraints(Modifier.fillMaxWidth().height(360.dp), contentAlignment = Alignment.Center) {
            val density = LocalDensity.current
            val bitmap = sampledBitmap(image, with(density) { maxWidth.roundToPx() }, with(density) { maxHeight.roundToPx() })
            if (bitmap != null) Image(bitmap.asImageBitmap(), contentDescription = null,
                modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
            else Text("正在载入图片…", Modifier.padding(16.dp))
        }
        Text("点击图片查看大图", Modifier.padding(12.dp), style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun TutorialImageViewer(image: TutorialImage, back: () -> Unit) {
    var scale by rememberSaveable(image.name) { mutableFloatStateOf(1f) }
    var offset by rememberSaveable(image.name, stateSaver = Saver<Offset, List<Float>>(
        save = { listOf(it.x, it.y) }, restore = { Offset(it[0], it[1]) },
    )) { mutableStateOf(Offset.Zero) }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(image.description, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = back) { Text("关闭大图") }
        }
        BoxWithConstraints(Modifier.fillMaxWidth().weight(1f).clipToBounds().testTag("tutorial-image-viewer"),
            contentAlignment = Alignment.Center) {
            val density = LocalDensity.current
            val width = with(density) { maxWidth.roundToPx() }
            val height = with(density) { maxHeight.roundToPx() }
            val bitmap = sampledBitmap(image, width, height)
            if (bitmap == null) CircularProgressIndicator()
            else Image(bitmap.asImageBitmap(), image.description, contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize().pointerInput(image) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        scale = (scale * zoom).coerceIn(1f, 4f)
                        val moved = offset + pan
                        offset = Offset(moved.x.coerceIn(-width * (scale - 1) / 2, width * (scale - 1) / 2),
                            moved.y.coerceIn(-height * (scale - 1) / 2, height * (scale - 1) / 2))
                    }
                }.graphicsLayer {
                    scaleX = scale; scaleY = scale
                    translationX = offset.x; translationY = offset.y
                    transformOrigin = TransformOrigin.Center
                })
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { scale = (scale / 1.5f).coerceAtLeast(1f); offset = Offset.Zero }, enabled = scale > 1f) { Text("缩小") }
            Text("${(scale * 100).toInt()}%", style = MaterialTheme.typography.labelLarge)
            TextButton(onClick = { scale = (scale * 1.5f).coerceAtMost(4f) }, enabled = scale < 4f) { Text("放大") }
            TextButton(onClick = { scale = 1f; offset = Offset.Zero }) { Text("重置") }
        }
    }
}
