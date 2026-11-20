import Foundation
import SQLite3

public enum SQLValue: Equatable {
    case null
    case integer(Int64)
    case real(Double)
    case text(String)

    public var string: String? { if case .text(let value) = self { return value } else { return nil } }
    public var int: Int? { if case .integer(let value) = self { return Int(value) } else { return nil } }
    public var double: Double? {
        switch self {
        case .real(let value): return value
        case .integer(let value): return Double(value)
        default: return nil
        }
    }
}

public struct DatabaseError: Error, LocalizedError {
    public let message: String
    public var errorDescription: String? { message }
}

/// A connection opened with SQLITE_OPEN_READONLY: the app can never change the operating data.
public final class ReadOnlyDatabase {
    private var handle: OpaquePointer?

    public init(path: String) throws {
        guard FileManager.default.fileExists(atPath: path) else {
            throw DatabaseError(message: "데이터베이스 파일이 없습니다: \(path)")
        }
        guard sqlite3_open_v2(path, &handle, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
            let reason = handle.map { String(cString: sqlite3_errmsg($0)) } ?? "알 수 없는 오류"
            sqlite3_close(handle)
            throw DatabaseError(message: "데이터베이스를 열 수 없습니다: \(reason)")
        }
    }

    deinit { sqlite3_close(handle) }

    public func tableExists(_ name: String) throws -> Bool {
        try rows("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", [name]).count == 1
    }

    public func rows(_ sql: String, _ arguments: [String] = []) throws -> [[SQLValue]] {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK else {
            throw DatabaseError(message: "SQL 오류: \(String(cString: sqlite3_errmsg(handle)))")
        }
        defer { sqlite3_finalize(statement) }
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)  // SQLITE_TRANSIENT
        for (index, argument) in arguments.enumerated() {
            sqlite3_bind_text(statement, Int32(index + 1), argument, -1, transient)
        }
        var result: [[SQLValue]] = []
        while true {
            let step = sqlite3_step(statement)
            if step == SQLITE_DONE { return result }
            guard step == SQLITE_ROW else {
                throw DatabaseError(message: "SQL 오류: \(String(cString: sqlite3_errmsg(handle)))")
            }
            result.append((0..<sqlite3_column_count(statement)).map { column in
                switch sqlite3_column_type(statement, column) {
                case SQLITE_INTEGER: return .integer(sqlite3_column_int64(statement, column))
                case SQLITE_FLOAT: return .real(sqlite3_column_double(statement, column))
                case SQLITE_TEXT: return .text(String(cString: sqlite3_column_text(statement, column)))
                default: return .null
                }
            })
        }
    }
}
