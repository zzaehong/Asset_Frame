import CryptoKit
import Foundation

public struct LedgerEntry: Equatable {
    public let seq: Int
    public let entryType: String
    public let payload: String  // canonical JSON text, exactly as stored
    public let createdAt: String
    public let prevHash: String
    public let entryHash: String
}

/// Same rule as src/asset_frame/ledger/chain.py (ADR-0007):
/// entry_hash = SHA-256 of the canonical JSON of [seq, prev_hash, entry_type, payload, created_at].
public enum HashChain {
    public static let genesisHash = String(repeating: "0", count: 64)

    public static func computeHash(
        seq: Int, prevHash: String, entryType: String, payload: String, createdAt: String
    ) -> String {
        let material =
            "[\(seq),\(jsonString(prevHash)),\(jsonString(entryType)),"
            + "\(jsonString(payload)),\(jsonString(createdAt))]"
        return SHA256.hash(data: Data(material.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    /// Sequence number of the first entry that does not match the chain; nil if intact.
    public static func firstBrokenSeq(_ entries: [LedgerEntry]) -> Int? {
        var previous = genesisHash
        var expected = 1
        for entry in entries {
            let recomputed = computeHash(
                seq: entry.seq, prevHash: entry.prevHash, entryType: entry.entryType,
                payload: entry.payload, createdAt: entry.createdAt)
            if entry.seq != expected || entry.prevHash != previous || entry.entryHash != recomputed {
                return entry.seq
            }
            previous = entry.entryHash
            expected = entry.seq + 1
        }
        return nil
    }

    /// Python json.dumps(ensure_ascii=False) string escaping.
    static func jsonString(_ text: String) -> String {
        var out = "\""
        for scalar in text.unicodeScalars {
            switch scalar {
            case "\"": out += "\\\""
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\u{08}": out += "\\b"
            case "\u{0C}": out += "\\f"
            default:
                if scalar.value < 0x20 {
                    out += String(format: "\\u%04x", scalar.value)
                } else {
                    out.unicodeScalars.append(scalar)
                }
            }
        }
        return out + "\""
    }
}
