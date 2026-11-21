import Foundation

public enum StockSelectionError: Error, LocalizedError, Equatable {
    case invalidTicker(String)
    case duplicate(String)
    case tooMany(Int)

    public var errorDescription: String? {
        switch self {
        case .invalidTicker(let ticker): "잘못된 티커입니다: \(ticker)"
        case .duplicate(let ticker): "티커가 중복됩니다: \(ticker)"
        case .tooMany(let count): "\(count)종목을 골랐습니다. 최대 \(StockSelection.limit)종목입니다."
        }
    }
}

/// The watchlist file `config/stocks.toml` (ADR-0010). The app validates the tickers and writes
/// this one file; collection itself is always done by the Python CLI (ADR-0013).
public enum StockSelection {
    /// Must match LIMIT and TICKER in src/asset_frame/stocks.py.
    public static let limit = 50
    private static let pattern = try! NSRegularExpression(pattern: "^[A-Z]{1,5}(-[A-Z])?$")

    public static func validate(_ tickers: [String]) throws -> [String] {
        var seen = Set<String>()
        for ticker in tickers {
            let range = NSRange(ticker.startIndex..., in: ticker)
            guard pattern.firstMatch(in: ticker, range: range) != nil else {
                throw StockSelectionError.invalidTicker(ticker)
            }
            guard seen.insert(ticker).inserted else { throw StockSelectionError.duplicate(ticker) }
        }
        guard tickers.count <= limit else { throw StockSelectionError.tooMany(tickers.count) }
        return tickers
    }

    /// Same text as Engine.stocksToml in the dashboard (a golden test keeps them equal).
    public static func toml(_ tickers: [String]) -> String {
        var lines = ["# 수집할 개별주 목록 (ADR-0010). 대시보드 \"개별주 선택\" 탭에서 만든 내용이다.", "schema_version = 1"]
        for ticker in tickers { lines += ["", "[[stocks]]", "ticker = \"\(ticker)\""] }
        return lines.joined(separator: "\n") + "\n"
    }

    /// Validates, then replaces config/stocks.toml atomically. Nothing is written on invalid input.
    @discardableResult
    public static func save(_ tickers: [String], root: URL) throws -> [String] {
        let valid = try validate(tickers)
        let file = root.appendingPathComponent("config/stocks.toml")
        try Data(toml(valid).utf8).write(to: file, options: .atomic)
        return valid
    }
}
