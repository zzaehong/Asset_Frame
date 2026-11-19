import AssetFrameCore
import SwiftUI

struct LedgerView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let ledger = model.ledger {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    LedgerStatusCard(ledger: ledger)
                    Card(title: "모델별 성적표") {
                        if ledger.boards.isEmpty {
                            Text("채점된 예측이 아직 없습니다. 예측은 기준월 뒤 3개월이 지나야 채점됩니다.")
                                .foregroundStyle(.secondary)
                        } else {
                            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 6) {
                                GridRow {
                                    Text("모델"); Text("채점"); Text("평균 순위 IC"); Text("평균 상·하위 스프레드"); Text("평균 Brier")
                                }.font(.caption).foregroundStyle(.secondary)
                                ForEach(ledger.boards, id: \.model) { board in
                                    GridRow {
                                        Text(board.model)
                                        Text("\(board.scored)")
                                        Text(Format.number(board.meanIC))
                                        Text(Format.percent(board.meanSpread))
                                        Text(Format.number(board.meanBrier))
                                    }.monospacedDigit()
                                }
                            }
                            Text("건수가 5건 미만이면 우열을 판단할 수 없습니다. 최소 탐지 효과(MDE)는 `uv run asset-frame ledger scoreboard`에 있습니다.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Card(title: "예측 (\(ledger.predictions.count)건)") {
                        ForEach(ledger.predictions.reversed(), id: \.seq) { item in
                            DisclosureGroup("\(item.asOf) · \(item.model)" + (scored(item, ledger) ? " · 채점됨" : " · 대기")) {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("순위: " + item.ranking.joined(separator: " > "))
                                    Text("상관 양수 확률: \(Format.number(item.probabilityPositive))")
                                    if !item.note.isEmpty { Text("근거: \(item.note)") }
                                    if let score = ledger.scores.first(where: { $0.predictionSeq == item.seq }) {
                                        Text("채점(\(score.horizonEnd)): IC \(Format.number(score.rankIC)), 스프레드 \(Format.percent(score.spread)), Brier \(Format.number(score.brier))")
                                    }
                                }
                                .font(.callout).textSelection(.enabled).padding(.vertical, 4)
                            }
                        }
                    }
                    Card(title: "내 예측 입력") {
                        Text("앱은 읽기 전용이라 입력은 터미널에서 합니다. 한 달에 한 번만 입력할 수 있습니다.")
                            .font(.caption).foregroundStyle(.secondary)
                        let command = "uv run asset-frame ledger predict --ranking SPY,GLD,IEF,TLT,BIL,DBC --positive-prob 0.6 --note \"근거 한 줄\""
                        Text(command).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        Button("명령 복사") { model.copyToPasteboard(command) }
                    }
                    Card(title: "국면 판독 기록 (\(ledger.regimes.count)건)") {
                        ForEach(ledger.regimes.suffix(12).reversed(), id: \.seq) { regime in
                            Line(label: "\(regime.monthEnd) · \(regime.kind) · \(regime.calcVersion)",
                                 value: "INDPRO+Sahm \(Format.flag(regime.indproSahm))")
                        }
                    }
                }
                .padding(20)
            }
        } else {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func scored(_ item: PredictionRecord, _ ledger: LedgerSnapshot) -> Bool {
        ledger.scores.contains { $0.predictionSeq == item.seq }
    }
}
