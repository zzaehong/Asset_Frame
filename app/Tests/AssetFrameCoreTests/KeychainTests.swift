import XCTest

@testable import AssetFrameCore

final class KeychainTests: XCTestCase {
    private func store() -> KeychainStore {
        let store = KeychainStore(service: "local.assetframe.test.\(UUID().uuidString)")
        addTeardownBlock { for name in ApiKeyName.allCases { try? store.remove(name.rawValue) } }
        return store
    }

    /// The Keychain can be unavailable (locked, no GUI session); skip rather than fail then.
    private func skipIfUnavailable(_ body: () throws -> Void) throws {
        do { try body() } catch KeychainError.status(let code)
            where code == errSecNotAvailable || code == errSecInteractionNotAllowed {
            throw XCTSkip("Keychain unavailable (\(code))")
        }
    }

    func testSaveReplaceAndRemove() throws {
        let keys = store()
        try skipIfUnavailable {
            XCTAssertFalse(try keys.contains("TIINGO_API_KEY"))
            try keys.save("first", account: "TIINGO_API_KEY")
            XCTAssertTrue(try keys.contains("TIINGO_API_KEY"))
            try keys.save("second", account: "TIINGO_API_KEY")  // replaces, no duplicate error
            XCTAssertEqual(try keys.value(for: "TIINGO_API_KEY"), "second")
            try keys.remove("TIINGO_API_KEY")
            XCTAssertFalse(try keys.contains("TIINGO_API_KEY"))
            try keys.remove("TIINGO_API_KEY")  // removing a missing key is not an error
        }
    }

    func testPastedWhitespaceIsTrimmedAndEmptyIsRejected() throws {
        let keys = store()
        try skipIfUnavailable {
            try keys.save("  abc123\n", account: "FRED_API_KEY")
            XCTAssertEqual(try keys.value(for: "FRED_API_KEY"), "abc123")
        }
        XCTAssertThrowsError(try keys.save("  \n ", account: "FRED_API_KEY")) { error in
            guard case KeychainError.emptyValue = error else { return XCTFail("\(error)") }
        }
    }

    func testAccountsAreTheEnvironmentVariableNamesTheCLIReads() {
        XCTAssertEqual(
            ApiKeyName.allCases.map(\.rawValue),
            ["TIINGO_API_KEY", "FRED_API_KEY", "KRX_API_KEY", "ECOS_API_KEY"])
        XCTAssertEqual(KeychainStore.defaultService, "local.assetframe.api-keys")
    }
}
