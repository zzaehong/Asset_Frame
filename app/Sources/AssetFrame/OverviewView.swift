import AssetFrameCore
import SwiftUI

struct Card<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 10))
    }
}

struct Line: View {
    let label: String
    let value: String
    var body: some View {
        HStack {
            Text(label).foregroundStyle(.secondary)
            Spacer()
            Text(value).monospacedDigit()
        }
    }
}

enum Format {
    static func flag(_ value: Bool?) -> String {
        guard let value else { return "계산 불가" }
        return value ? "침체 신호" : "신호 없음"
    }

    static func number(_ value: Double?, _ digits: Int = 2) -> String {
        value.map { String(format: "%.\(digits)f", $0) } ?? "—"
    }

    static func percent(_ value: Double?) -> String {
        value.map { String(format: "%.1f%%", $0 * 100) } ?? "—"
    }

    static func quadrant(_ key: String?) -> String {
        switch key {
        case "growth_up_inflation_up": "성장 ↑ · 물가 ↑"
        case "growth_up_inflation_down": "성장 ↑ · 물가 ↓"
        case "growth_down_inflation_up": "성장 ↓ · 물가 ↑"
        case "growth_down_inflation_down": "성장 ↓ · 물가 ↓"
        default: "—"
        }
    }

    static func correlation(_ key: String?) -> String {
        switch key {
        case "stock_bond_positive": "주식·채권 상관 양(+): 채권이 헤지 못함"
        case "stock_bond_negative": "주식·채권 상관 음(−): 채권이 헤지함"
        default: "—"
        }
    }
}

struct OverviewView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let regime = model.ledger?.latestLiveRegime {
                    Card(title: "현재 국면 (\(regime.monthEnd) 월말 기준)") {
                        Line(label: "INDPRO + Sahm 침체 규칙", value: Format.flag(regime.indproSahm))
                        Line(label: "CFNAI-MA3 + Sahm 침체 규칙", value: Format.flag(regime.cfnaiSahm))
                        Line(label: "Sahm 지표(%p, 0.5 이상이면 신호)", value: Format.number(regime.sahm))
                        Line(label: "산업생산 전년비", value: Format.percent(regime.indproYoY))
                        Line(label: "CFNAI-MA3", value: Format.number(regime.cfnaiMA3))
                        Line(label: "성장 × 물가", value: Format.quadrant(regime.quadrant))
                        Line(label: "SPY–IEF 36개월 상관", value: Format.number(regime.correlation))
                        Text(Format.correlation(regime.correlationRegime)).font(.caption).foregroundStyle(.secondary)
                        Text("규칙 \(regime.calcVersion). 침체 규칙은 표본이 2~3번뿐이라 참고용입니다.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                } else {
                    Card(title: "현재 국면") {
                        Text("원장에 live 국면 기록이 없습니다. 터미널에서 `uv run asset-frame ledger record-regime`")
                            .foregroundStyle(.secondary)
                    }
                }
                if let ledger = model.ledger {
                    LedgerStatusCard(ledger: ledger)
                    if !ledger.pending.isEmpty {
                        Card(title: "채점 대기 (\(ledger.pending.count)건)") {
                            ForEach(ledger.pending, id: \.seq) { item in
                                Line(label: item.model, value: "\(item.asOf) 기준 → 3개월 뒤 채점")
                            }
                            Text("터미널에서 `uv run asset-frame ledger score`로 채점합니다.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                if let status = model.status {
                    Card(title: "데이터 최신성") {
                        Line(label: "마지막 가격일", value: status.latestPriceDate ?? "—")
                        Line(label: "마지막 월간 수익률", value: status.latestReturnMonth ?? "—")
                    }
                }
                if let loaded = model.loadedAt {
                    Text("읽은 시각 \(loaded.formatted(date: .abbreviated, time: .standard)) · 앱은 데이터를 읽기만 합니다")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(20)
        }
    }
}

struct LedgerStatusCard: View {
    @EnvironmentObject var model: AppModel
    let ledger: LedgerSnapshot

    var body: some View {
        Card(title: "원장") {
            Line(label: "항목 수", value: "\(ledger.entries.count)")
            if let broken = ledger.brokenAt {
                Label("해시 체인이 \(broken)번 항목에서 깨졌습니다. 원장이 변조되었거나 손상되었습니다.",
                      systemImage: "xmark.octagon.fill").foregroundStyle(.red)
            } else {
                Label("해시 체인 정상", systemImage: "checkmark.seal.fill").foregroundStyle(.green)
            }
            if let head = ledger.headHash {
                HStack {
                    Text("head").foregroundStyle(.secondary)
                    Text(head).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    Spacer()
                    Button("복사") { model.copyToPasteboard(head) }
                }
                Text("이 값을 가끔 DB 밖(노트 등)에 적어 두세요. DB를 가진 사람은 체인 전체를 다시 쓸 수 있습니다.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}
