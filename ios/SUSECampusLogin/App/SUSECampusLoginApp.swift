import SwiftUI

@main
struct SUSECampusLoginApp: App {
    @StateObject private var service = LoginService.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(service)
                .task {
                    await service.bootstrap()
                }
        }
    }
}
