import Foundation

public struct RegimeReading: Equatable {
    public let seq: Int
    public let kind: String  // live | replay
    public let calcVersion: String
    public let monthEnd: String
    public let sahm: Double?
    public let indproYoY: Double?
    public let cfnaiMA3: Double?
    public let indproSahm: Bool?
    public let cfnaiSahm: Bool?
    public let quadrant: String?
    public let correlation: Double?
    public let correlationRegime: String?
    public let nberRecession: Bool
}

public struct PredictionRecord: Equatable {
    public let seq: Int
    public let model: String
    public let asOf: String
    public let ranking: [String]
    public let probabilityPositive: Double
    public let note: String
    public let createdAt: String
}

public struct ScoreRecord: Equatable {
    public let seq: Int
    public let predictionSeq: Int
    public let model: String
    public let asOf: String
    public let horizonEnd: String
    public let assets: Int
    public let rankIC: Double?
    public let spread: Double?
    public let brier: Double?
}

public struct ModelBoard: Equatable {
    public let model: String
    public let scored: Int
    public let meanIC: Double?
    public let meanSpread: Double?
    public let meanBrier: Double?
}

public struct LedgerSnapshot {
    public let entries: [LedgerEntry]
    public let brokenAt: Int?
    public let regimes: [RegimeReading]
    public let predictions: [PredictionRecord]
    public let scores: [ScoreRecord]

    public var headHash: String? { entries.last?.entryHash }
    public var latestLiveRegime: RegimeReading? { regimes.last { $0.kind == "live" } }

    /// Predictions whose 3-month horizon has not been scored yet.
    public var pending: [PredictionRecord] {
        let scored = Set(scores.map(\.predictionSeq))
        return predictions.filter { !scored.contains($0.seq) }
    }

    /// Means per model. A rank IC or Brier is averaged over the scores that have one.
    public var boards: [ModelBoard] {
        Dictionary(grouping: scores, by: \.model).keys.sorted().map { model in
            let items = scores.filter { $0.model == model }
            return ModelBoard(
                model: model, scored: items.count,
                meanIC: Self.mean(items.compactMap(\.rankIC)),
                meanSpread: Self.mean(items.compactMap(\.spread)),
                meanBrier: Self.mean(items.compactMap(\.brier)))
        }
    }

    static func mean(_ values: [Double]) -> Double? {
        values.isEmpty ? nil : values.reduce(0, +) / Double(values.count)
    }
}

public enum LedgerReader {
    public static func read(_ database: ReadOnlyDatabase) throws -> LedgerSnapshot {
        guard try database.tableExists("ledger_entry") else {
            return LedgerSnapshot(entries: [], brokenAt: nil, regimes: [], predictions: [], scores: [])
        }
        let rows = try database.rows(
            "SELECT seq, entry_type, payload, created_at, prev_hash, entry_hash "
                + "FROM ledger_entry ORDER BY seq")
        let entries = rows.compactMap { row -> LedgerEntry? in
            guard let seq = row[0].int, let type = row[1].string, let payload = row[2].string,
                let created = row[3].string, let prev = row[4].string, let hash = row[5].string
            else { return nil }
            return LedgerEntry(
                seq: seq, entryType: type, payload: payload, createdAt: created, prevHash: prev,
                entryHash: hash)
        }
        // A row that cannot be read at all is treated like a gap, so the chain check reports it.
        let broken = entries.count == rows.count ? HashChain.firstBrokenSeq(entries) : 0

        var regimes: [RegimeReading] = [], predictions: [PredictionRecord] = []
        var scores: [ScoreRecord] = []
        for entry in entries {
            guard
                let object = try? JSONSerialization.jsonObject(with: Data(entry.payload.utf8))
                    as? [String: Any]
            else { continue }
            switch entry.entryType {
            case "regime_observation":
                regimes.append(regime(entry.seq, object))
            case "prediction":
                if let item = prediction(entry, object) { predictions.append(item) }
            case "score":
                if let item = score(entry.seq, object) { scores.append(item) }
            default:
                break
            }
        }
        return LedgerSnapshot(
            entries: entries, brokenAt: broken, regimes: regimes, predictions: predictions,
            scores: scores)
    }

    private static func regime(_ seq: Int, _ o: [String: Any]) -> RegimeReading {
        RegimeReading(
            seq: seq, kind: o["kind"] as? String ?? "", calcVersion: o["calc_version"] as? String ?? "",
            monthEnd: o["month_end"] as? String ?? "", sahm: o["sahm"] as? Double,
            indproYoY: o["indpro_yoy"] as? Double, cfnaiMA3: o["cfnai_ma3"] as? Double,
            indproSahm: o["indpro_sahm"] as? Bool, cfnaiSahm: o["cfnai_sahm"] as? Bool,
            quadrant: o["quadrant"] as? String, correlation: o["stock_bond_correlation"] as? Double,
            correlationRegime: o["correlation_regime"] as? String,
            nberRecession: o["nber_recession"] as? Bool ?? false)
    }

    private static func prediction(_ entry: LedgerEntry, _ o: [String: Any]) -> PredictionRecord? {
        guard let model = o["model"] as? String, let asOf = o["as_of"] as? String,
            let ranking = o["ranking"] as? [String],
            let probability = (o["p_correlation_positive"] as? NSNumber)?.doubleValue
        else { return nil }
        return PredictionRecord(
            seq: entry.seq, model: model, asOf: asOf, ranking: ranking,
            probabilityPositive: probability, note: o["note"] as? String ?? "",
            createdAt: entry.createdAt)
    }

    private static func score(_ seq: Int, _ o: [String: Any]) -> ScoreRecord? {
        guard let predictionSeq = (o["prediction_seq"] as? NSNumber)?.intValue,
            let model = o["model"] as? String, let asOf = o["as_of"] as? String,
            let end = o["horizon_end"] as? String
        else { return nil }
        return ScoreRecord(
            seq: seq, predictionSeq: predictionSeq, model: model, asOf: asOf, horizonEnd: end,
            assets: (o["n_assets"] as? NSNumber)?.intValue ?? 0, rankIC: o["ic"] as? Double,
            spread: o["spread"] as? Double, brier: o["brier"] as? Double)
    }
}
