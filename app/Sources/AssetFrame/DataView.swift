import SwiftUI

struct DataView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let status = model.status {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Card(title: "가격·수익률") {
                        Line(label: "마지막 가격일", value: status.latestPriceDate ?? "—")
                        Line(label: "마지막 월간 수익률", value: status.latestReturnMonth ?? "—")
                        Line(label: "월간 수익률이 있는 티커", value: "\(status.tickers)")
                    }
                    Card(title: "거시 시리즈 (FRED, 최초 발표값 기준)") {
                        Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 6) {
                            GridRow { Text("시리즈"); Text("관측 수"); Text("최근 관측월"); Text("최근 발표일") }
                                .font(.caption).foregroundStyle(.secondary)
                            ForEach(status.macro, id: \.series) { item in
                                GridRow {
                                    Text(item.series); Text("\(item.observations)")
                                    Text(item.latestObservation); Text(item.latestRelease)
                                }.monospacedDigit()
                            }
                        }
                    }
                    Card(title: "최근 수집 실행") {
                        ForEach(Array(status.recentRuns.enumerated()), id: \.offset) { _, run in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack {
                                    Text("\(run.source) · \(run.kind)")
                                    Spacer()
                                    Text(run.status).foregroundStyle(run.status == "failed" ? .red : .primary)
                                }
                                Text("\(run.startedAt) · 수용 \(run.accepted)건" + (run.error.map { " · \($0)" } ?? ""))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                .padding(20)
            }
        } else {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}
