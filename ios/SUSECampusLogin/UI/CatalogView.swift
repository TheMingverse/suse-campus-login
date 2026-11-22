import SwiftUI

struct CatalogView: View {
    @EnvironmentObject private var service: LoginService
    @Environment(\.dismiss) private var dismiss
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Group {
                if service.services.isEmpty {
                    ContentUnavailableView(
                        "还没有服务列表",
                        systemImage: "list.bullet.rectangle",
                        description: Text("先连接校园 Wi-Fi，然后点击“刷新服务”从学校获取。")
                    )
                } else {
                    List {
                        ForEach(service.services) { option in
                            Button {
                                select(option)
                            } label: {
                                HStack(alignment: .firstTextBaseline) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(option.name)
                                            .foregroundStyle(.primary)
                                        if !option.reason.isEmpty {
                                            Text(option.reason)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    Spacer(minLength: 12)
                                    if option.name == service.configuration.service {
                                        Image(systemName: "checkmark")
                                            .foregroundStyle(Color.accentColor)
                                    } else if !option.available {
                                        Image(systemName: "lock")
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                            .disabled(!option.available)
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("上网服务")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        Task { await service.refreshServices() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("刷新")
                    .disabled(service.isBusy)
                }
            }
            .alert("无法保存", isPresented: errorBinding) {
                Button("好", role: .cancel) { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
        }
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { errorMessage != nil },
            set: { if !$0 { errorMessage = nil } }
        )
    }

    private func select(_ option: ServiceOption) {
        do {
            try service.selectService(option.name)
            dismiss()
        } catch let failure as Failure {
            errorMessage = failure.message
        } catch {
            errorMessage = "无法保存服务选择，请重试。"
        }
    }
}
