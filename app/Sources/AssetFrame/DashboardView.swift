import SwiftUI
import WebKit

/// Shows the offline dashboard that `asset-frame dashboard` writes (all analysis stays in Python).
struct DashboardView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let location = model.location, FileManager.default.fileExists(atPath: location.dashboardURL.path) {
            WebView(file: location.dashboardURL, readAccess: location.reportsDirectory, token: model.webReloadToken)
        } else {
            VStack(spacing: 10) {
                Image(systemName: "chart.xyaxis.line").font(.system(size: 40)).foregroundStyle(.secondary)
                Text("대시보드 파일이 없습니다").font(.title3.bold())
                Text("터미널에서 `uv run asset-frame dashboard`를 실행한 뒤 새로고침(⌘R)하세요.")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

struct WebView: NSViewRepresentable {
    let file: URL
    let readAccess: URL
    let token: Int

    final class Coordinator { var loadedToken = -1 }
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let view = WKWebView(frame: .zero)
        view.setValue(false, forKey: "drawsBackground")
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        guard context.coordinator.loadedToken != token else { return }
        context.coordinator.loadedToken = token
        view.loadFileURL(file, allowingReadAccessTo: readAccess)
    }
}
