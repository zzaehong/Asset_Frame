import Foundation

public struct MacroStatus: Equatable {
    public let series: String
    public let observations: Int
    public let latestObservation: String
    public let latestRelease: String
}

public struct RunStatus: Equatable {
    public let source: String
    public let kind: String
    public let status: String
    public let startedAt: String
    public let accepted: Int
    public let error: String?
}

public struct DataStatus {
    public let latestPriceDate: String?
    public let latestReturnMonth: String?
    public let tickers: Int
    public let macro: [MacroStatus]
    public let recentRuns: [RunStatus]
}

public enum DataStatusReader {
    public static func read(_ db: ReadOnlyDatabase) throws -> DataStatus {
        let price = try scalar(db, "price_observations", "SELECT max(trading_date) FROM price_observations")
        let returns = try db.tableExists("monthly_return")
            ? try db.rows(
                "SELECT max(month_end), count(DISTINCT ticker) FROM monthly_return "
                    + "WHERE computed_at = (SELECT max(computed_at) FROM monthly_return)")
            : []
        let macro = try db.tableExists("macro_observation")
            ? try db.rows(
                "SELECT series_id, count(*), max(observation_date), max(realtime_start) "
                    + "FROM macro_observation GROUP BY series_id ORDER BY series_id")
            : []
        let runs = try db.tableExists("ingestion_runs")
            ? try db.rows(
                "SELECT source_id, data_kind, status, started_at, records_accepted, error_message "
                    + "FROM ingestion_runs ORDER BY started_at DESC LIMIT 8")
            : []
        return DataStatus(
            latestPriceDate: price,
            latestReturnMonth: returns.first?[0].string,
            tickers: returns.first?[1].int ?? 0,
            macro: macro.compactMap { row in
                guard let series = row[0].string, let count = row[1].int,
                    let observed = row[2].string, let release = row[3].string
                else { return nil }
                return MacroStatus(
                    series: series, observations: count, latestObservation: observed,
                    latestRelease: release)
            },
            recentRuns: runs.compactMap { row in
                guard let source = row[0].string, let kind = row[1].string,
                    let status = row[2].string, let started = row[3].string
                else { return nil }
                return RunStatus(
                    source: source, kind: kind, status: status, startedAt: started,
                    accepted: row[4].int ?? 0, error: row[5].string)
            })
    }

    private static func scalar(_ db: ReadOnlyDatabase, _ table: String, _ sql: String) throws -> String? {
        guard try db.tableExists(table) else { return nil }
        return try db.rows(sql).first?.first?.string
    }
}
