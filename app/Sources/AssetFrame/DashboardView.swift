import AssetFrameCore
import SwiftUI
import WebKit

/// Shows the offline dashboard that `asset-frame dashboard` writes (all analysis stays in Python).
struct DashboardView: View {
    @EnvironmentObject var model: AppModel
    let tab: String

    var body: some View {
        if let location = model.location, FileManager.default.fileExists(atPath: location.dashboardURL.path) {
            WebView(file: location.dashboardURL, readAccess: location.reportsDirectory, token: model.webReloadToken, tab: tab,
                    root: location.root, runner: model.collector, onFinished: { model.load() })
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
    /// One of the dashboard's fixed tab ids (regime|history|compare|lab); never user input.
    let tab: String
    let root: URL
    let runner: CollectRunner
    /// Called on the main queue when a collection run ends, so the dashboard is read again.
    let onFinished: () -> Void

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var loadedToken = -1
        var shownTab = ""
        var tab = ""
        var root = URL(fileURLWithPath: "/")
        var runner = CollectRunner()
        var onFinished: () -> Void = {}

        /// Messages from the dashboard page (the 개별주 선택 tab). Only the actions below are
        /// understood; tickers are validated again before anything is written.
        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let action = body["action"] as? String,
                  let view = message.webView else { return }
            let tickers = (body["tickers"] as? [String]) ?? []
            do {
                switch action {
                case "save":
                    try StockSelection.save(tickers, root: root)
                    reply(view, "saved", "선택 \(tickers.count)종목을 config/stocks.toml에 저장했습니다.")
                    alert("저장 완료", "선택 \(tickers.count)종목을 저장했습니다. 다음 갱신부터 수집됩니다.")
                case "collect":
                    guard !tickers.isEmpty else { return reply(view, "error", "수집할 종목을 먼저 고르세요.") }
                    try StockSelection.save(tickers, root: root)
                    try runner.start(root: root) { [weak self] _ in DispatchQueue.main.async { self?.onFinished() } }
                    reply(view, "started", "저장하고 수집을 시작했습니다.")
                case "cancel":
                    let stopped = runner.cancel()
                    reply(view, stopped ? "progress" : "error", stopped ? "수집을 중단했습니다." : "이 앱이 시작한 수집이 없습니다(스케줄 실행은 건드리지 않습니다).")
                case "status":
                    reply(view, "progress", "")
                default:
                    break
                }
            } catch {
                reply(view, "error", error.localizedDescription)
                alert("저장하지 못했습니다", error.localizedDescription)
            }
        }

        private func alert(_ title: String, _ text: String) {
            let box = NSAlert()
            box.messageText = title
            box.informativeText = text
            box.addButton(withTitle: "확인")
            box.runModal()
        }

        private func reply(_ view: WKWebView, _ kind: String, _ text: String) {
            let status = runner.status(root: root)
            var payload: [String: Any] = ["kind": kind, "message": text, "running": status.running, "own": status.ownRun, "lines": status.lines]
            if let code = status.exitCode { payload["exitCode"] = Int(code) }
            guard let data = try? JSONSerialization.data(withJSONObject: payload), let json = String(data: data, encoding: .utf8) else { return }
            view.evaluateJavaScript("window.stocksEvent && window.stocksEvent(\(json))")
        }

        func show(_ view: WKWebView) {
            shownTab = tab
            view.evaluateJavaScript("document.body.classList.add('embedded'); showTab('\(tab)')")
        }
        func webView(_ view: WKWebView, didFinish navigation: WKNavigation!) { show(view) }
    }
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(context.coordinator, name: "assetFrame")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.setValue(false, forKey: "drawsBackground")
        view.navigationDelegate = context.coordinator
        return view
    }

    static func dismantleNSView(_ view: WKWebView, coordinator: Coordinator) {
        view.configuration.userContentController.removeScriptMessageHandler(forName: "assetFrame")
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        context.coordinator.tab = tab
        context.coordinator.root = root
        context.coordinator.runner = runner
        context.coordinator.onFinished = onFinished
        if context.coordinator.loadedToken != token {
            context.coordinator.loadedToken = token
            view.loadFileURL(file, allowingReadAccessTo: readAccess)
        } else if context.coordinator.shownTab != tab {
            context.coordinator.show(view)
        }
    }
}
