// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "AssetFrame",
    platforms: [.macOS(.v14)],
    targets: [
        // Read-only access to the operating SQLite file and the ledger hash chain. No third-party
        // packages: SQLite3 and CryptoKit ship with macOS.
        .target(name: "AssetFrameCore"),
        .executableTarget(name: "AssetFrame", dependencies: ["AssetFrameCore"]),
        .testTarget(
            name: "AssetFrameCoreTests",
            dependencies: ["AssetFrameCore"],
            resources: [.copy("Fixtures")]
        ),
    ],
    swiftLanguageModes: [.v5]
)
