import AppKit
import AssetFrameCore
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var location: ProjectLocation? = ProjectLocation.saved()
    @Published var ledger: LedgerSnapshot?
    @Published var status: DataStatus?
    @Published var error: String?
    @Published var loadedAt: Date?
    @Published var webReloadToken = 0
    @Published var screen: Screen = Screen.initial
    /// Runs `asset-frame update --steps stocks,dashboard` for the 개별주 선택 screen (ADR-0013).
    let collector = CollectRunner()

    func load() {
        guard let location else { return }
        do {
            let database = try ReadOnlyDatabase(path: location.databasePath)
            ledger = try LedgerReader.read(database)
            status = try DataStatusReader.read(database)
            error = nil
            loadedAt = Date()
            webReloadToken += 1
        } catch {
            ledger = nil
            status = nil
            self.error = error.localizedDescription
        }
    }

    func chooseProject() {
        let panel = NSOpenPanel()
        panel.message = "Asset_Frame 프로젝트 폴더(var/ 폴더가 있는 곳)를 선택하세요"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let chosen = ProjectLocation(root: url)
        chosen.save()
        location = chosen
        load()
    }

    func copyToPasteboard(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}
