import Foundation

/// The Asset_Frame folder that holds var/ (database and reports). It is chosen once by the user
/// (or given by ASSET_FRAME_HOME) so no personal path is compiled into the app.
public struct ProjectLocation: Equatable {
    public let root: URL

    public init(root: URL) { self.root = root }

    public var databasePath: String { root.appendingPathComponent("var/asset_frame.sqlite3").path }
    public var dashboardURL: URL { root.appendingPathComponent("var/reports/dashboard.html") }
    public var reportsDirectory: URL { root.appendingPathComponent("var/reports") }

    public var looksValid: Bool { FileManager.default.fileExists(atPath: databasePath) }

    private static let defaultsKey = "projectRoot"

    public static func saved(defaults: UserDefaults = .standard, environment: [String: String] = ProcessInfo.processInfo.environment) -> ProjectLocation? {
        if let path = environment["ASSET_FRAME_HOME"], !path.isEmpty {
            return ProjectLocation(root: URL(fileURLWithPath: path))
        }
        return defaults.string(forKey: defaultsKey).map { ProjectLocation(root: URL(fileURLWithPath: $0)) }
    }

    public func save(defaults: UserDefaults = .standard) {
        defaults.set(root.path, forKey: Self.defaultsKey)
    }
}
