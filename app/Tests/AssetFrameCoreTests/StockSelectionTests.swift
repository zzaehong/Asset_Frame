import XCTest

@testable import AssetFrameCore

final class StockSelectionTests: XCTestCase {
    private func project() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root.appendingPathComponent("config"), withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    /// The same literal is asserted in tests/test_dashboard_engine.py for the dashboard's JavaScript.
    static let golden = """
        # 수집할 개별주 목록 (ADR-0010). 대시보드 "개별주 선택" 탭에서 만든 내용이다.
        schema_version = 1

        [[stocks]]
        ticker = "NVDA"

        [[stocks]]
        ticker = "BRK-B"

        """

    func testTomlMatchesTheDashboardAndPythonFormat() {
        XCTAssertEqual(StockSelection.toml(["NVDA", "BRK-B"]), Self.golden)
        XCTAssertTrue(StockSelection.toml([]).hasSuffix("schema_version = 1\n"))
    }

    func testValidationRejectsBadDuplicateAndTooManyTickers() {
        XCTAssertThrowsError(try StockSelection.validate(["nvda"])) {
            XCTAssertEqual($0 as? StockSelectionError, .invalidTicker("nvda"))
        }
        XCTAssertThrowsError(try StockSelection.validate(["NVDA\"\n[[x]]"]))  // no TOML injection
        XCTAssertThrowsError(try StockSelection.validate(["AAPL", "AAPL"])) {
            XCTAssertEqual($0 as? StockSelectionError, .duplicate("AAPL"))
        }
        let many = (0..<51).map { i in String(UnicodeScalar(65 + i / 26)!) + String(UnicodeScalar(65 + i % 26)!) }
        XCTAssertThrowsError(try StockSelection.validate(many)) {
            XCTAssertEqual($0 as? StockSelectionError, .tooMany(51))
        }
        XCTAssertEqual(try StockSelection.validate(["BRK-B", "A"]), ["BRK-B", "A"])
    }

    func testSaveWritesTheFileAndInvalidInputLeavesItUntouched() throws {
        let root = try project()
        try StockSelection.save(["NVDA", "BRK-B"], root: root)
        let file = root.appendingPathComponent("config/stocks.toml")
        XCTAssertEqual(try String(contentsOf: file, encoding: .utf8), Self.golden)
        XCTAssertThrowsError(try StockSelection.save(["bad"], root: root))
        XCTAssertEqual(try String(contentsOf: file, encoding: .utf8), Self.golden)
        try StockSelection.save([], root: root)  // clearing the selection is allowed
        XCTAssertFalse(try String(contentsOf: file, encoding: .utf8).contains("[[stocks]]"))
    }
}
