import Foundation

public enum CollectError: Error, LocalizedError {
    case alreadyRunning
    case missingPython(String)

    public var errorDescription: String? {
        switch self {
        case .alreadyRunning: "이미 갱신이 실행 중입니다(스케줄 또는 이전 실행). 끝난 뒤 다시 시도하세요."
        case .missingPython(let path): "파이썬 환경이 없습니다(\(path)). 터미널에서 `uv sync --dev --frozen`을 실행하세요."
        }
    }
}

public struct CollectStatus: Equatable {
    public var running: Bool
    public var ownRun: Bool
    public var exitCode: Int32?
    public var lines: [String]
    /// From `var/progress.json` (written by the CLI) while an update is live.
    public var progress: CollectProgress? = nil
}

public struct CollectProgress: Equatable {
    public var percent: Int
    public var step: String
    public var stepIndex: Int
    public var steps: Int
    public var stepDone: Int
    public var stepTotal: Int
}

/// Starts `asset-frame update --steps stocks,dashboard` as a child process (ADR-0013). The app never
/// writes the database itself: the CLI is still the only write path. Output goes to a log file, not
/// a pipe, so the run survives quitting the app. `var/update.lock` (written by the CLI) tells
/// whether any update, including the scheduled one, is running.
public final class CollectRunner: @unchecked Sendable {
    public typealias Command = (URL) -> (executable: URL, arguments: [String])
    public static let logRelative = "var/logs/collect-stocks.log"

    private let command: Command
    private let lock = NSLock()
    private var process: Process?
    private var exitCode: Int32?

    public init(command: @escaping Command = CollectRunner.defaultCommand) { self.command = command }

    public static func defaultCommand(root: URL) -> (executable: URL, arguments: [String]) {
        (root.appendingPathComponent(".venv/bin/python"),
         ["-m", "asset_frame", "update", "--steps", "stocks,dashboard"])
    }

    /// True when `var/update.lock` names a live process.
    public static func updateRunning(root: URL) -> Bool {
        let file = root.appendingPathComponent("var/update.lock")
        guard let text = try? String(contentsOf: file, encoding: .utf8),
              let pid = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines)), pid > 0
        else { return false }
        return kill(pid, 0) == 0 || errno == EPERM
    }

    /// Starts the run; `onExit` is called on a background queue with the exit code.
    public func start(root: URL, onExit: @escaping @Sendable (Int32) -> Void = { _ in }) throws {
        let (executable, arguments) = command(root)
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw CollectError.missingPython(executable.path)
        }
        lock.lock(); defer { lock.unlock() }
        if process?.isRunning == true || Self.updateRunning(root: root) { throw CollectError.alreadyRunning }
        let log = root.appendingPathComponent(Self.logRelative)
        try FileManager.default.createDirectory(at: log.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: log.path, contents: nil)
        let handle = try FileHandle(forWritingTo: log)
        let child = Process()
        child.executableURL = executable
        child.arguments = arguments
        child.currentDirectoryURL = root
        child.standardOutput = handle
        child.standardError = handle
        exitCode = nil
        child.terminationHandler = { [weak self] finished in
            try? handle.close()
            self?.lock.lock(); self?.exitCode = finished.terminationStatus; self?.lock.unlock()
            onExit(finished.terminationStatus)
        }
        try child.run()
        process = child
    }

    /// Stops a run this app started; false if there is none (a scheduled run is left alone).
    @discardableResult
    public func cancel() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard let child = process, child.isRunning else { return false }
        child.terminate()
        return true
    }

    public func status(root: URL, tail: Int = 12) -> CollectStatus {
        lock.lock()
        let own = process?.isRunning == true
        let code = exitCode
        lock.unlock()
        return CollectStatus(
            running: own || Self.updateRunning(root: root), ownRun: own, exitCode: own ? nil : code,
            lines: Self.tailLines(root.appendingPathComponent(Self.logRelative), count: tail),
            progress: (own || Self.updateRunning(root: root)) ? Self.readProgress(root: root) : nil)
    }

    static func readProgress(root: URL) -> CollectProgress? {
        guard let data = try? Data(contentsOf: root.appendingPathComponent("var/progress.json")),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let percent = json["percent"] as? Int, let step = json["step"] as? String,
              let index = json["step_index"] as? Int, let steps = json["steps"] as? Int,
              let done = json["step_done"] as? Int, let total = json["step_total"] as? Int
        else { return nil }
        return CollectProgress(percent: min(100, max(0, percent)), step: step, stepIndex: index, steps: steps, stepDone: done, stepTotal: total)
    }

    static func tailLines(_ file: URL, count: Int) -> [String] {
        guard let handle = try? FileHandle(forReadingFrom: file) else { return [] }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        try? handle.seek(toOffset: size > 65536 ? size - 65536 : 0)
        let text = String(decoding: (try? handle.readToEnd()) ?? Data(), as: UTF8.self)
        return Array(text.split(separator: "\n", omittingEmptySubsequences: true).suffix(count).map(String.init))
    }
}
