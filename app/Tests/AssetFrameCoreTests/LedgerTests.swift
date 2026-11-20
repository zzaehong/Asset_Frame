import XCTest
import SQLite3

@testable import AssetFrameCore

final class LedgerTests: XCTestCase {
    private var fixture: String {
        Bundle.module.url(forResource: "Fixtures/ledger", withExtension: "sqlite3")!.path
    }

    private func snapshot(_ path: String) throws -> LedgerSnapshot {
        try LedgerReader.read(ReadOnlyDatabase(path: path))
    }

    func testPythonWrittenChainVerifies() throws {
        // The fixture was written by src/asset_frame/storage/ledger.py, including a payload with
        // quotes, a backslash, a newline, a tab and Korean text.
        let result = try snapshot(fixture)
        XCTAssertEqual(result.entries.count, 4)
        XCTAssertNil(result.brokenAt)
        XCTAssertEqual(result.headHash, result.entries.last?.entryHash)
    }

    func testTamperedPayloadIsReportedAtThatEntry() throws {
        let copy = try writableCopy()
        try execute(copy, "DROP TRIGGER ledger_entry_no_update;"
            + "UPDATE ledger_entry SET payload = '{}' WHERE seq = 2")

        XCTAssertEqual(try snapshot(copy).brokenAt, 2)
    }

    func testDeletedEntryIsReportedAsAGap() throws {
        let copy = try writableCopy()
        try execute(copy, "DROP TRIGGER ledger_entry_no_delete; DELETE FROM ledger_entry WHERE seq = 2")

        XCTAssertEqual(try snapshot(copy).brokenAt, 3)
    }

    func testEntriesAreDecodedIntoRecords() throws {
        let result = try snapshot(fixture)

        XCTAssertEqual(result.latestLiveRegime?.monthEnd, "2026-10-30")
        XCTAssertEqual(result.latestLiveRegime?.indproSahm, false)
        XCTAssertEqual(result.latestLiveRegime?.quadrant, "growth_up_inflation_up")
        XCTAssertEqual(result.predictions.count, 2)
        XCTAssertTrue(result.predictions[0].note.contains("\"금리\""))
        XCTAssertEqual(result.predictions[0].probabilityPositive, 0.7, accuracy: 1e-12)
        XCTAssertEqual(result.pending.map(\.model), ["equal_rank"])
    }

    func testBoardAveragesOnlyAvailableValues() throws {
        let board = try XCTUnwrap(snapshot(fixture).boards.first)

        XCTAssertEqual(board.model, "human")
        XCTAssertEqual(board.scored, 1)
        XCTAssertEqual(try XCTUnwrap(board.meanIC), 0.4, accuracy: 1e-12)
        XCTAssertNil(board.meanBrier)  // the only score had no correlation outcome
    }

    func testMissingLedgerTableGivesAnEmptySnapshot() throws {
        let path = NSTemporaryDirectory() + UUID().uuidString + ".sqlite3"
        try execute(path, "CREATE TABLE x (a)")

        let result = try snapshot(path)
        XCTAssertTrue(result.entries.isEmpty)
        XCTAssertNil(result.brokenAt)
        XCTAssertNil(result.headHash)
    }

    func testDatabaseIsOpenedReadOnly() throws {
        let database = try ReadOnlyDatabase(path: writableCopy())
        XCTAssertThrowsError(try database.rows("CREATE TABLE y (a)"))
        XCTAssertThrowsError(try ReadOnlyDatabase(path: "/nonexistent/db.sqlite3"))
    }

    func testJSONStringEscapingMatchesPython() {
        // json.dumps("a\"b\\c\n\t/é\u{01}", ensure_ascii=False)
        XCTAssertEqual(HashChain.jsonString("a\"b\\c\n\t/é\u{01}"), "\"a\\\"b\\\\c\\n\\t/é\\u0001\"")
    }

    func testDataStatusReadsLatestDatesAndRuns() throws {
        let path = NSTemporaryDirectory() + UUID().uuidString + ".sqlite3"
        try execute(
            path,
            """
            CREATE TABLE price_observations (trading_date TEXT);
            INSERT INTO price_observations VALUES ('2026-11-16'), ('2026-11-17');
            CREATE TABLE monthly_return (ticker TEXT, month_end TEXT, computed_at TEXT);
            INSERT INTO monthly_return VALUES ('SPY','2026-09-30','a'), ('SPY','2026-10-30','b'),
              ('IEF','2026-10-30','b'), ('SPY','2026-08-31','a');
            CREATE TABLE macro_observation (series_id TEXT, observation_date TEXT, realtime_start TEXT);
            INSERT INTO macro_observation VALUES ('UNRATE','2026-09-01','2026-10-02'),
              ('UNRATE','2026-10-01','2026-11-06'), ('INDPRO','2026-10-01','2026-11-17');
            CREATE TABLE ingestion_runs (source_id, data_kind, status, started_at,
              records_accepted INTEGER, error_message);
            INSERT INTO ingestion_runs VALUES ('fred','macro','failed','2026-11-18T01:00','0','HTTP 429'),
              ('tiingo-eod','price','succeeded','2026-11-17T01:00','5',NULL);
            """)

        let status = try DataStatusReader.read(ReadOnlyDatabase(path: path))

        XCTAssertEqual(status.latestPriceDate, "2026-11-17")
        XCTAssertEqual(status.latestReturnMonth, "2026-10-30")  // only the latest build ('b')
        XCTAssertEqual(status.tickers, 2)
        XCTAssertEqual(status.macro.map(\.series), ["INDPRO", "UNRATE"])
        XCTAssertEqual(status.macro[1].observations, 2)
        XCTAssertEqual(status.macro[1].latestRelease, "2026-11-06")
        XCTAssertEqual(status.recentRuns.first?.error, "HTTP 429")
    }

    // MARK: helpers

    private func writableCopy() throws -> String {
        let path = NSTemporaryDirectory() + UUID().uuidString + ".sqlite3"
        try FileManager.default.copyItem(atPath: fixture, toPath: path)
        return path
    }

    private func execute(_ path: String, _ sql: String) throws {
        var handle: OpaquePointer?
        XCTAssertEqual(sqlite3_open(path, &handle), SQLITE_OK)
        defer { sqlite3_close(handle) }
        XCTAssertEqual(sqlite3_exec(handle, sql, nil, nil, nil), SQLITE_OK, "SQL failed: \(sql)")
    }
}
