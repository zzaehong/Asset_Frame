import AssetFrameCore
import SwiftUI

/// Saves, replaces and removes API keys in the macOS Keychain. Values are typed into a secure
/// field, written once and never shown again; this screen only knows whether a key exists.
struct ApiKeysView: View {
    private let store = KeychainStore()
    @State private var saved: [ApiKeyName: Bool] = [:]
    @State private var editing: ApiKeyName?
    @State private var draft = ""
    @State private var message: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Card(title: "API 키 (macOS 키체인)") {
                    Text("키는 이 Mac의 키체인에만 저장하고 화면에 다시 보여 주지 않습니다. 터미널의 수집 명령은 환경변수가 있으면 그것을, 없으면 키체인을 읽습니다.")
                        .font(.callout).foregroundStyle(.secondary)
                    ForEach(ApiKeyName.allCases, id: \.self) { name in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(name.rawValue).font(.system(.body, design: .monospaced))
                                Text(name.purpose).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Label(saved[name] == true ? "저장됨" : "없음",
                                  systemImage: saved[name] == true ? "checkmark.circle.fill" : "minus.circle")
                                .foregroundStyle(saved[name] == true ? .green : .secondary)
                            Button(saved[name] == true ? "변경" : "입력") { draft = ""; editing = name }
                            Button("삭제", role: .destructive) { remove(name) }.disabled(saved[name] != true)
                        }
                        .padding(.vertical, 2)
                    }
                    if let message {
                        Label(message, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
                    }
                }
                Card(title: "알아 둘 점") {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("• 터미널이 키체인 키를 처음 읽을 때 접근 허용 창이 뜨면 \"항상 허용\"을 누르세요.")
                        Text("• 앱을 다시 빌드하면 서명이 바뀌어 이 화면에서 키를 바꿀 때 로그인 암호를 물을 수 있습니다.")
                        Text("• 앱은 수집을 실행하지 않습니다. 수집은 터미널의 asset-frame 명령으로 합니다.")
                        Text("• Linux·WSL에서는 키체인이 없으니 환경변수(.env)를 쓰세요.")
                    }.font(.callout).foregroundStyle(.secondary)
                }
            }
            .padding(20)
        }
        .onAppear(perform: refresh)
        .sheet(item: $editing) { name in
            VStack(alignment: .leading, spacing: 12) {
                Text("\(name.rawValue) 입력").font(.headline)
                SecureField("키를 붙여 넣으세요", text: $draft).textFieldStyle(.roundedBorder).frame(width: 360)
                Text("저장하면 키체인에 쓰고 화면에는 남기지 않습니다.").font(.caption).foregroundStyle(.secondary)
                HStack {
                    Spacer()
                    Button("취소") { draft = ""; editing = nil }
                    Button("저장") { save(name) }
                        .buttonStyle(.borderedProminent)
                        .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .padding(20)
        }
    }

    private func refresh() {
        for name in ApiKeyName.allCases {
            do { saved[name] = try store.contains(name.rawValue) } catch {
                saved[name] = false
                message = error.localizedDescription
            }
        }
    }

    private func save(_ name: ApiKeyName) {
        do {
            try store.save(draft, account: name.rawValue)
            message = nil
        } catch { message = error.localizedDescription }
        draft = ""
        editing = nil
        refresh()
    }

    private func remove(_ name: ApiKeyName) {
        do { try store.remove(name.rawValue); message = nil } catch { message = error.localizedDescription }
        refresh()
    }
}

extension ApiKeyName: Identifiable { public var id: String { rawValue } }
