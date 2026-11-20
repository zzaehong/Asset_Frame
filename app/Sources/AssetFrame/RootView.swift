import SwiftUI

enum Section: String, CaseIterable, Identifiable {
    case overview = "개요"
    case dashboard = "대시보드"
    case ledger = "원장"
    case data = "데이터"

    var id: String { rawValue }
    /// ASSET_FRAME_SECTION=개요|대시보드|원장|데이터 picks the first screen (used to check each screen).
    static var initial: Section {
        ProcessInfo.processInfo.environment["ASSET_FRAME_SECTION"].flatMap(Section.init(rawValue:)) ?? .overview
    }
    var icon: String {
        switch self {
        case .overview: "gauge.with.dots.needle.33percent"
        case .dashboard: "chart.xyaxis.line"
        case .ledger: "list.bullet.rectangle"
        case .data: "externaldrive"
        }
    }
}

struct RootView: View {
    @EnvironmentObject var model: AppModel
    @State private var selection: Section? = Section.initial

    var body: some View {
        if model.location == nil {
            ChooseProjectView()
        } else {
            NavigationSplitView {
                List(Section.allCases, selection: $selection) { section in
                    Label(section.rawValue, systemImage: section.icon).tag(section)
                }
                .navigationSplitViewColumnWidth(min: 150, ideal: 170)
            } detail: {
                VStack(spacing: 0) {
                    if let message = model.error {
                        Label(message, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(10)
                            .background(.red.opacity(0.1))
                    }
                    switch selection ?? .overview {
                    case .overview: OverviewView()
                    case .dashboard: DashboardView()
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
