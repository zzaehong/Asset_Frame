import SwiftUI

@main
struct AssetFrameApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Asset Frame") {
            RootView()
                .environmentObject(model)
                .frame(minWidth: 900, minHeight: 600)
                .task { model.load() }
        }
        .commands {
            CommandGroup(after: .newItem) {
                Button("새로고침") { model.load() }.keyboardShortcut("r")
                Button("프로젝트 폴더 선택…") { model.chooseProject() }
            }
            CommandMenu("화면") {
                ForEach(Screen.sidebarOrder) { screen in
                    Button(screen.rawValue) { model.screen = screen }.keyboardShortcut(screen.shortcut)
                }
            }
        }
    }
}
