package io.github.themingverse.susecampus.tutorial

import androidx.annotation.DrawableRes
import io.github.themingverse.susecampus.R

enum class TutorialImage(@get:DrawableRes val resource: Int, val description: String) {
    ACCOUNT(R.drawable.tutorial_account, "填写校园网账号和密码"),
    SERVICE(R.drawable.tutorial_service, "刷新后选择自己的上网服务"),
    TILE_CONFIRM(R.drawable.tutorial_tile_confirm, "系统确认添加 SUSE 登录磁贴"),
    TILE_EDIT(R.drawable.tutorial_tile_edit, "在控制中心编辑并排列 SUSE 登录磁贴"),
    QUICK_ENTRIES(R.drawable.tutorial_quick_entries, "首页的桌面小组件和磁贴入口"),
    WIDGET_DESKTOP(R.drawable.tutorial_widget_desktop, "长按桌面空白处后点击小部件"),
    WIDGET_CATALOG(R.drawable.tutorial_widget_catalog, "在小部件面板中打开全部应用"),
    WIDGET_ANDROID(R.drawable.tutorial_widget_android, "在应用列表底部打开安卓小部件"),
    WIDGET_PICKER(R.drawable.tutorial_widget_picker, "找到 SUSE 校园网并选择小组件尺寸"),
    WIDGET_PLACED(R.drawable.tutorial_widget_placed, "将 SUSE 登录小组件放到桌面"),
}

enum class TutorialSection { MAIN, TILE, WIDGET }

data class TutorialPage(
    val title: String,
    val paragraphs: List<String>,
    val image: TutorialImage? = null,
    val detail: TutorialSection? = null,
    val detailLabel: String = "",
    val showProject: Boolean = false,
)

object TutorialContent {
    const val PROJECT_URL = "https://github.com/TheMingverse/suse-campus-login"
    const val DEVICE_NOTE = "图示为小米手机，其他手机请查找对应入口。"
    val main = listOf(
        TutorialPage("首次配置前，先看这里", listOf(
            "首次配置时，请连接尚未登录认证的校园 Wi-Fi。",
            "已联网时可能无法刷新上网服务，可先保存账号草稿，等下次认证时补全。",
            "在系统设置中开启校园 Wi-Fi 的“自动连接”，搭配“SUSE 登录”磁贴使用更方便。",
        )),
        TutorialPage("填写你的校园网账号", listOf(
            "连接 SUSE 或 SUSE_Hostel，填写自己的校园网账号和密码。",
            "操作时按提示允许精确位置权限，并开启系统定位，以识别校园 Wi-Fi。密码仅加密保存在此设备。",
        ), TutorialImage.ACCOUNT),
        TutorialPage("选择运营商，保存并登录", listOf(
            "点击“只读刷新上网服务”，再从“上网服务”中选择自己使用的服务。",
            "点击“保存设置”，最后点击“立即检查并登录”。",
            "暂时无法刷新时，可先“保存加密草稿”，以后再补全服务。",
        ), TutorialImage.SERVICE),
        TutorialPage("推荐：添加登录磁贴", listOf(
            "在首页点击“添加快捷设置磁贴”，按提示添加“SUSE 登录”。",
            "连接校园 Wi-Fi 后，下拉控制中心，点击“SUSE 登录”即可检查并登录。",
        ), TutorialImage.TILE_CONFIRM, TutorialSection.TILE, "没有弹出？查看手动添加方法"),
        TutorialPage("也可以添加桌面小组件", listOf(
            "在首页点击“添加 1×1 小组件”或“添加 2×1 小组件”，按提示放到桌面。",
            "点击小组件即可检查并登录，显示上次检查结果。",
        ), TutorialImage.QUICK_ENTRIES, TutorialSection.WIDGET, "查看手动添加图解"),
        TutorialPage("感谢使用", listOf(
            "感谢使用 SUSE 校园网！希望它能让你连接校园网更省心。",
            "如果觉得好用，欢迎到 GitHub 为项目点一颗 Star，感谢你的支持。",
        ), showProject = true),
    )
    val tile = listOf(TutorialPage("手动添加登录磁贴", listOf(
        "下拉控制中心 → 编辑 → 将“SUSE 登录”加入快捷区域 → 保存。", DEVICE_NOTE,
    ), TutorialImage.TILE_EDIT))
    val widget = listOf(
        TutorialPage("1. 长按桌面空白处", listOf("进入桌面编辑模式，点击底部的“小部件”。", DEVICE_NOTE), TutorialImage.WIDGET_DESKTOP),
        TutorialPage("2. 打开全部应用", listOf("在小部件面板中，点击“全部应用”。"), TutorialImage.WIDGET_CATALOG),
        TutorialPage("3. 找到安卓小部件", listOf("向下滑到应用列表底部，打开“安卓小部件”。"), TutorialImage.WIDGET_ANDROID),
        TutorialPage("4. 选择 SUSE 小组件", listOf("找到“SUSE 校园网”，选择 1×1 或 2×1 的“SUSE 登录”小组件。"), TutorialImage.WIDGET_PICKER),
        TutorialPage("5. 放到桌面即可使用", listOf("将小组件放到桌面并结束编辑。连接校园 Wi-Fi 后，点击即可检查并登录。"), TutorialImage.WIDGET_PLACED),
    )
    fun pages(section: TutorialSection) = when (section) {
        TutorialSection.MAIN -> main
        TutorialSection.TILE -> tile
        TutorialSection.WIDGET -> widget
    }
}
