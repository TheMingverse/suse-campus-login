import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var service: LoginService
    @Environment(\.dismiss) private var dismiss

    @State private var username = ""
    @State private var password = ""
    @State private var selectedService = ""
    @State private var autoLogin = true
    @State private var errorMessage: String?
    @State private var loaded = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("学号", text: $username)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("密码", text: $password)
                        .textContentType(.password)
                } header: {
                    Text("账号")
                } footer: {
                    Text("账号与密码只保存在本机钥匙串，除学校认证服务器外不会发送到任何地方。")
                }

                Section {
                    if service.services.isEmpty {
                        TextField("服务名称（可点击下方刷新获取）", text: $selectedService)
                    } else {
                        Picker("上网服务", selection: $selectedService) {
                            if !selectedService.isEmpty,
                               !service.services.contains(where: { $0.name == selectedService }) {
                                Text(selectedService).tag(selectedService)
                            }
                            ForEach(service.services) { option in
                                Text(option.available ? option.name : "\(option.name)（不可自动登录）")
                                    .tag(option.name)
                            }
                        }
                    }
                    Button {
                        Task { await service.refreshServices() }
                    } label: {
                        Label("从学校获取最新服务列表", systemImage: "arrow.clockwise")
                    }
                } header: {
                    Text("上网服务")
                }

                Section {
                    Toggle("异常时暂停自动登录", isOn: $autoLogin)
                } footer: {
                    Text("学校返回需要人工处理的信息时，App 会记下原因并停止反复尝试；清除原因后可重新登录。")
                }
            }
            .navigationTitle("设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { save() }
                        .disabled(username.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onAppear(perform: load)
            .alert("保存失败", isPresented: errorBinding) {
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

    private func load() {
        guard !loaded else { return }
        loaded = true
        username = service.configuration.username
        password = service.configuration.password
        selectedService = service.configuration.service
        autoLogin = service.configuration.autoLogin
    }

    private func save() {
        do {
            try service.save(
                username: username,
                password: password,
                service: selectedService,
                autoLogin: autoLogin
            )
            dismiss()
        } catch let failure as Failure {
            errorMessage = failure.message
        } catch {
            errorMessage = "无法保存设置，请重试。"
        }
    }
}
