import AppIntents
import Foundation

/// Lets Shortcuts, the Action Button and personal automations ("when I join the
/// campus Wi-Fi") start one bounded login attempt. The app opens so the result
/// stays visible and the system can run the network requests in the foreground.
struct CampusLoginIntent: AppIntent {
    static var title: LocalizedStringResource = "校园网自动登录"

    static var description: IntentDescription? = IntentDescription(
        "连接 SUSE 校园 Wi-Fi 后执行一次认证；可在快捷指令自动化中使用。"
    )

    static var openAppWhenRun: Bool = true

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let message = await LoginService.shared.performLogin()
        return .result(dialog: IntentDialog(stringLiteral: message))
    }
}

struct CampusShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: CampusLoginIntent(),
            phrases: [
                "用 \(.applicationName) 登录校园网",
                "让 \(.applicationName) 连接校园网"
            ],
            shortTitle: "校园网登录",
            systemImageName: "wifi"
        )
    }
}
