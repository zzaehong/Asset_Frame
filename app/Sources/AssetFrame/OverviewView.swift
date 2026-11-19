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

struct SignalRow: View {
    let ok: Bool
    let text: String
    var body: some View {
        Label {
            Text(text)
        } icon: {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(ok ? Color.green : Color.orange)
        }
    }
}

struct RegimeTile: View {
    let title: String
    let value: String
    let detail: String
    let alert: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.caption).foregroundStyle(.secondary)
                Text(value).font(.title3.bold()).foregroundStyle(alert ? Color.red : Color.primary)
                Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, minHeight: 78, alignment: .topLeading)
            .padding(12)
            .background(.background.secondary, in: RoundedRectangle(cornerRadius: 10))
        }
        .buttonStyle(.plain)
    }
}

struct OverviewView: View {
    @EnvironmentObject var model: AppModel

    private var priceAge: (date: String, days: Int)? {
        guard let text = model.status?.latestPriceDate else { return nil }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = TimeZone(identifier: "UTC")
        guard let date = formatter.date(from: text) else { return nil }
        return (text, Calendar.current.dateComponents([.day], from: date, to: Date()).day ?? 0)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Card(title: "지금 확인할 것") {
                    if let age = priceAge {
                        SignalRow(ok: age.days <= 7,
                                  text: "가격 데이터는 \(age.date) 기준입니다(\(age.days)일 전)." + (age.days <= 7 ? "" : " 터미널에서 수집 후 `uv run asset-frame dashboard`를 다시 실행하세요."))
                    }
                    if let ledger = model.ledger {
                        SignalRow(ok: ledger.brokenAt == nil,
                                  text: ledger.brokenAt == nil ? "원장 해시 체인이 정상입니다(\(ledger.entries.count)건)." : "원장 체인이 \(ledger.brokenAt ?? 0)번 항목에서 깨졌습니다.")
                        if let regime = ledger.latestLiveRegime {
                            let mine = ledger.predictions.contains { $0.model == "human" && $0.asOf.prefix(7) == regime.monthEnd.prefix(7) }
                            SignalRow(ok: mine, text: mine ? "\(regime.monthEnd.prefix(7)) 내 예측을 입력했습니다." : "\(regime.monthEnd.prefix(7)) 내 예측이 아직 없습니다. 원장 화면에서 입력 명령을 복사하세요.")
                        }
                        SignalRow(ok: ledger.pending.isEmpty,
                                  text: ledger.pending.isEmpty ? "채점 대기 중인 예측이 없습니다." : "채점 대기 \(ledger.pending.count)건. 기준월 3개월 뒤 `uv run asset-frame ledger score`로 채점합니다.")
                    }
                }
                if let regime = model.ledger?.latestLiveRegime {
                    Card(title: "현재 국면 (\(regime.monthEnd) 월말)") {
                        HStack(alignment: .top, spacing: 10) {
                            RegimeTile(title: "성장×물가", value: Format.quadrant(regime.quadrant),
                                       detail: regime.cfnaiMA3.map { "CFNAI-MA3 \(Format.number($0))" } ?? "", alert: false) { model.screen = .regime }
                            RegimeTile(title: "침체 신호", value: Format.flag(regime.indproSahm),
                                       detail: "Sahm \(Format.number(regime.sahm))%p", alert: regime.indproSahm == true) { model.screen = .regime }
                            RegimeTile(title: "주식·채권 상관", value: regime.correlationRegime == "stock_bond_positive" ? "동행 (+)" : "헤지 (−)",
                                       detail: "SPY–IEF \(Format.number(regime.correlation))", alert: false) { model.screen = .regime }
                        }
                        HStack {
                            Button("① 시장 국면 보기") { model.screen = .regime }
                            Button("② 이 국면의 과거 성과") { model.screen = .history }
                        }
                        Text("규칙 \(regime.calcVersion). 침체 규칙은 표본이 2~3번뿐이라 참고용입니다.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                } else {
                    Card(title: "현재 국면") {
                        Text("원장에 live 국면 기록이 없습니다. 터미널에서 `uv run asset-frame ledger record-regime`")
                            .foregroundStyle(.secondary)
                    }
                }
                if let ledger = model.ledger { LedgerStatusCard(ledger: ledger) }
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
