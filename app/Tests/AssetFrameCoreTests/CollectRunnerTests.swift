import XCTest

@testable import AssetFrameCore

final class CollectRunnerTests: XCTestCase {
    private func project() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root.appendingPathComponent("var"), withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    private func runner(script: String, root: URL) throws -> CollectRunner {
        let file = root.appendingPathComponent("fake.sh")
        try script.write(to: file, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: file.path)
        return CollectRunner(command: { _ in (file, []) })
    }

    private func wait(for runner: CollectRunner, root: URL) {
        let deadline = Date().addingTimeInterval(10)
        while runner.status(root: root).running && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
    }

    func testARunWritesItsOutputToTheLogAndReportsTheExitCode() throws {
        let root = try project()
        let run = try runner(script: "#!/bin/sh\necho collecting\necho done\nexit 0\n", root: root)
        let exited = expectation(description: "exit")
        try run.start(root: root) { code in XCTAssertEqual(code, 0); exited.fulfill() }
        wait(for: [exited], timeout: 10)
        let status = run.status(root: root)
        XCTAssertFalse(status.running)
        XCTAssertEqual(status.exitCode, 0)
        XCTAssertEqual(status.lines, ["collecting", "done"])
    }

    func testAFailureKeepsItsExitCodeAndMessage() throws {
        let root = try project()
        let run = try runner(script: "#!/bin/sh\necho 'TIINGO_API_KEY is missing' >&2\nexit 3\n", root: root)
        let exited = expectation(description: "exit")
        try run.start(root: root) { _ in exited.fulfill() }
        wait(for: [exited], timeout: 10)
        XCTAssertEqual(run.status(root: root).exitCode, 3)
        XCTAssertEqual(run.status(root: root).lines, ["TIINGO_API_KEY is missing"])
    }

    func testALiveUpdateLockBlocksAStartAndAStaleOneDoesNot() throws {
        let root = try project()
        let lock = root.appendingPathComponent("var/update.lock")
        try "\(getpid())".write(to: lock, atomically: true, encoding: .utf8)
        XCTAssertTrue(CollectRunner.updateRunning(root: root))
        let run = try runner(script: "#!/bin/sh\nexit 0\n", root: root)
        XCTAssertThrowsError(try run.start(root: root)) {
            guard case CollectError.alreadyRunning = $0 else { return XCTFail("\($0)") }
        }
        try "999999".write(to: lock, atomically: true, encoding: .utf8)  // no such process
        XCTAssertFalse(CollectRunner.updateRunning(root: root))
        try "not a pid".write(to: lock, atomically: true, encoding: .utf8)
        XCTAssertFalse(CollectRunner.updateRunning(root: root))
    }

    func testCancelStopsOnlyARunTheAppStarted() throws {
        let root = try project()
        let run = try runner(script: "#!/bin/sh\nsleep 30\n", root: root)
        XCTAssertFalse(run.cancel())  // nothing started yet
        let exited = expectation(description: "exit")
        try run.start(root: root) { _ in exited.fulfill() }
        XCTAssertTrue(run.status(root: root).ownRun)
        XCTAssertTrue(run.cancel())
        wait(for: [exited], timeout: 10)
        XCTAssertFalse(run.status(root: root).running)
    }

    func testAMissingPythonIsReportedWithItsPath() throws {
        let root = try project()
        XCTAssertThrowsError(try CollectRunner().start(root: root)) {
            guard case CollectError.missingPython(let path) = $0 else { return XCTFail("\($0)") }
            XCTAssertTrue(path.hasSuffix(".venv/bin/python"))
        }
    }

    /// Opt-in (ASSET_FRAME_E2E=1): runs the real CLI's dashboard step through the runner. It only
    /// regenerates var/reports/dashboard.html and takes/releases var/update.lock.
    func testRealCliRunsThroughTheRunner() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["ASSET_FRAME_E2E"] == "1", "set ASSET_FRAME_E2E=1")
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let run = CollectRunner(command: { root in
            (root.appendingPathComponent(".venv/bin/python"), ["-m", "asset_frame", "update", "--steps", "dashboard"])
        })
        let exited = expectation(description: "exit")
        try run.start(root: root) { code in XCTAssertEqual(code, 0); exited.fulfill() }
        wait(for: [exited], timeout: 120)
        XCTAssertTrue(run.status(root: root).lines.contains("[dashboard] ok"), "\(run.status(root: root).lines)")
        XCTAssertFalse(CollectRunner.updateRunning(root: root))
    }
}
