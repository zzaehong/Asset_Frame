import SwiftUI

enum Screen: String, CaseIterable, Identifiable {
    case home = "홈"
    case regime = "① 시장 국면"
    case history = "② 국면별 과거 성과"
    case compare = "③ 전략 비교"
    case lab = "③ 포트폴리오 실험실"
    case ledger = "원장"
    case data = "데이터"

    var id: String { rawValue }
    /// Name of the dashboard tab this screen shows; nil for native screens.
    var webTab: String? {
        switch self {
        case .regime: "regime"
        case .history: "history"
        case .compare: "compare"
        case .lab: "lab"
        default: nil
        }
    }
    static let analysis: [Screen] = [.regime, .history, .compare, .lab]
    static let records: [Screen] = [.ledger, .data]
    /// ASSET_FRAME_SECTION=<screen title> picks the first screen (used to check each screen).
    static var initial: Screen {
        ProcessInfo.processInfo.environment["ASSET_FRAME_SECTION"].flatMap(Screen.init(rawValue:)) ?? .home
    }
    var icon: String {
        switch self {
        case .home: "house"
        case .regime: "globe.asia.australia"
        case .history: "clock.arrow.circlepath"
        case .compare: "chart.xyaxis.line"
        case .lab: "slider.horizontal.3"
        case .ledger: "list.bullet.rectangle"
        case .data: "externaldrive"
        }
    }
    /// ⌘1…⌘7 in sidebar order.
    var shortcut: KeyEquivalent { KeyEquivalent(Character(String(Screen.sidebarOrder.firstIndex(of: self)! + 1))) }
    static let sidebarOrder: [Screen] = [.home] + analysis + records
}

struct RootView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if model.location == nil {
            ChooseProjectView()
        } else {
            NavigationSplitView {
                List(selection: $model.screen) {
                    Label(Screen.home.rawValue, systemImage: Screen.home.icon).tag(Screen.home)
                    SwiftUI.Section("분석 흐름") {
                        ForEach(Screen.analysis) { screen in
                            Label(screen.rawValue, systemImage: screen.icon).tag(screen)
                        }
                    }
                    SwiftUI.Section("기록") {
                        ForEach(Screen.records) { screen in
                            Label(screen.rawValue, systemImage: screen.icon).tag(screen)
                        }
                    }
                }
                .navigationSplitViewColumnWidth(min: 190, ideal: 210)
            } detail: {
                VStack(spacing: 0) {
                    if let message = model.error {
                        Label(message, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(10)
                            .background(.red.opacity(0.1))
                    }
                    switch model.screen {
                    case .home: OverviewView()
                    case .regime, .history, .compare, .lab: DashboardView(tab: model.screen.webTab ?? "regime")
                    case .ledger: LedgerView()
                    case .data: DataView()
                    }
                }
            }
            .toolbar {
                ToolbarItem {
                    Button { model.load() } label: { Label("새로고침", systemImage: "arrow.clockwise") }
                        .help("데이터베이스를 다시 읽습니다 (⌘R)")
                }
            }
        }
    }
}

struct ChooseProjectView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "folder.badge.questionmark").font(.system(size: 44))
            Text("프로젝트 폴더를 선택하세요").font(.title2.bold())
            Text("Asset_Frame 폴더(var/ 안에 asset_frame.sqlite3가 있는 곳)를 가리키면 앱이 읽기 전용으로 엽니다.")
                .foregroundStyle(.secondary).multilineTextAlignment(.center).frame(maxWidth: 420)
            Button("폴더 선택…") { model.chooseProject() }.buttonStyle(.borderedProminent)
        }
        .padding(40)
    }
}
