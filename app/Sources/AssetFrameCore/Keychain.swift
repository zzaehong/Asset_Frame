import Foundation
import Security

/// The API keys the Python CLI can use. The Keychain account is the environment variable name.
public enum ApiKeyName: String, CaseIterable, Sendable {
    case tiingo = "TIINGO_API_KEY"
    case fred = "FRED_API_KEY"
    case krx = "KRX_API_KEY"
    case ecos = "ECOS_API_KEY"

    public var purpose: String {
        switch self {
        case .tiingo: "미국 ETF·주식 가격(Tiingo)"
        case .fred: "거시 지표(FRED)"
        case .krx: "한국거래소(아직 쓰는 곳 없음)"
        case .ecos: "한국은행 ECOS(아직 쓰는 곳 없음)"
        }
    }
}

public enum KeychainError: Error, LocalizedError {
    case emptyValue
    case status(OSStatus)

    public var errorDescription: String? {
        switch self {
        case .emptyValue: "키가 비어 있습니다."
        case .status(let code):
            "키체인 오류 \(code): " + ((SecCopyErrorMessageString(code, nil) as String?) ?? "알 수 없음")
        }
    }
}

/// Stores API keys in the login Keychain. This is the only thing the app writes (ADR-0011); the
/// project's database and files stay read-only. A stored value is never returned to the UI: the
/// screen only asks whether a key exists, and the CLI reads the value itself.
public struct KeychainStore {
    /// Must match KEYCHAIN_SERVICE in src/asset_frame/secrets.py.
    public static let defaultService = "local.assetframe.api-keys"
    public let service: String

    public init(service: String = KeychainStore.defaultService) { self.service = service }

    private func query(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    /// Whether an item exists. Asks for attributes only, so it does not read the secret.
    public func contains(_ account: String) throws -> Bool {
        var request = query(account)
        request[kSecReturnAttributes as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        let status = SecItemCopyMatching(request as CFDictionary, nil)
        switch status {
        case errSecSuccess: return true
        case errSecItemNotFound: return false
        default: throw KeychainError.status(status)
        }
    }

    /// Adds or replaces the value. Surrounding whitespace and newlines (a pasted key often has
    /// one) are removed.
    public func save(_ value: String, account: String) throws {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw KeychainError.emptyValue }
        let data = Data(trimmed.utf8)
        var item = query(account)
        item[kSecValueData as String] = data
        item[kSecAttrLabel as String] = "Asset Frame API key"
        var status = SecItemAdd(item as CFDictionary, nil)
        if status == errSecDuplicateItem {
            status = SecItemUpdate(query(account) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        }
        guard status == errSecSuccess else { throw KeychainError.status(status) }
    }

    public func remove(_ account: String) throws {
        let status = SecItemDelete(query(account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError.status(status)
        }
    }

    /// For tests only: reading a secret back is not exposed to the app.
    func value(for account: String) throws -> String? {
        var request = query(account)
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(request as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw KeychainError.status(status) }
        return String(data: data, encoding: .utf8)
    }
}
