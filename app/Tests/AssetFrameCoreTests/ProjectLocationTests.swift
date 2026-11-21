import XCTest

@testable import AssetFrameCore

final class ProjectLocationTests: XCTestCase {
    private func defaults() -> UserDefaults {
        let name = "ProjectLocationTests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        return defaults
    }

    private func project() throws -> String {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root.appendingPathComponent("var"), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: root.appendingPathComponent("var/asset_frame.sqlite3").path, contents: Data())
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root.path
    }

    func testBundledFolderIsUsedWhenNothingElseIsSet() throws {
        let path = try project()
        let found = ProjectLocation.saved(defaults: defaults(), environment: [:], bundled: path)
        XCTAssertEqual(found?.root.path, path)
    }

    func testBundledFolderWithoutDatabaseIsIgnored() {
        XCTAssertNil(ProjectLocation.saved(defaults: defaults(), environment: [:], bundled: "/no/such/folder"))
        XCTAssertNil(ProjectLocation.saved(defaults: defaults(), environment: [:], bundled: nil))
    }

    func testEnvironmentThenChosenFolderBeatTheBundledOne() throws {
        let store = defaults()
        let bundled = try project()
        ProjectLocation(root: URL(fileURLWithPath: "/chosen")).save(defaults: store)
        XCTAssertEqual(ProjectLocation.saved(defaults: store, environment: [:], bundled: bundled)?.root.path, "/chosen")
        let env = ["ASSET_FRAME_HOME": "/from-env"]
        XCTAssertEqual(ProjectLocation.saved(defaults: store, environment: env, bundled: bundled)?.root.path, "/from-env")
    }
}
