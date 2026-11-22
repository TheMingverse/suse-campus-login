import SwiftUI

extension Stage {
    var title: String {
        switch self {
        case .idle: return "待检测"
        case .checking: return "检测网络"
        case .preparing: return "读取认证信息"
        case .authenticating: return "正在认证"
        case .verifying: return "确认外网连接"
        case .online: return "已联网"
        case .catalog: return "服务列表"
        case .setup: return "需要设置"
        case .blocked: return "已暂停"
        case .failed: return "未完成"
        case .cancelled: return "已取消"
        case .busy: return "进行中"
        }
    }

    var symbol: String {
        switch self {
        case .online: return "wifi"
        case .checking, .preparing, .authenticating, .verifying, .busy:
            return "arrow.triangle.2.circlepath"
        case .catalog: return "list.bullet.rectangle"
        case .setup: return "person.crop.circle.badge.questionmark"
        case .blocked: return "pause.circle"
        case .failed: return "exclamationmark.triangle"
        case .cancelled: return "xmark.circle"
        case .idle: return "wifi.slash"
        }
    }

    var tint: Color {
        switch self {
        case .online: return .green
        case .blocked, .failed: return .orange
        case .setup, .catalog: return .blue
        default: return .accentColor
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var service: LoginService
    @State private var showingSettings = false
    @State private var showingCatalog = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 18) {
                    statusCard
                    summaryCard
                    primaryButton
                    secondaryButtons
                    hintSection
                }
                .padding(20)
            }
            .background(Color(.systemGroupedBackground).ignoresSafeArea())
            .navigationTitle("校园网登录")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showingSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("设置")
                }
            }
            .sheet(isPresented: $showingSettings) {
                SettingsView()
                    .environmentObject(service)
            }
            .sheet(isPresented: $showingCatalog) {
                CatalogView()
                    .environmentObject(service)
            }
        }
    }

    private var statusCard: some View {
        VStack(spacing: 12) {
            Image(systemName: service.stage.symbol)
                .font(.system(size: 44, weight: .semibold))
                .foregroundStyle(service.stage.tint)
                .symbolEffect(.pulse, isActive: service.isBusy)
            Text(service.stage.title)
                .font(.headline)
            Text(service.message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 28)
        .padding(.horizontal, 20)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(Color(.secondarySystemGroupedBackground))
        )
    }

    private var summaryCard: some View {
        VStack(spacing: 0) {
            row(title: "账号", value: service.configuration.username.isEmpty ? "未填写" : service.configuration.username)
            Divider()
            row(title: "上网服务", value: service.configuration.service.isEmpty ? "未选择" : service.configuration.service)
            if let block = service.configuration.block {
                Divider()
                row(title: "自动登录", value: block.message, tint: .orange)
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(.secondarySystemGroupedBackground))
        )
    }

    private func row(title: String, value: String, tint: Color? = nil) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .foregroundStyle(.secondary)
            Spacer(minLength: 12)
            Text(value)
                .foregroundStyle(tint ?? .primary)
                .multilineTextAlignment(.trailing)
        }
        .font(.subheadline)
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    private var primaryButton: some View {
        Button {
            if service.canLogin {
                Task { await service.login() }
            } else {
                showingSettings = true
            }
        } label: {
            HStack(spacing: 8) {
                if service.isBusy {
                    ProgressView()
                        .tint(.white)
                }
                Text(service.canLogin ? "立即登录" : "填写账号并登录")
                    .font(.headline)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .disabled(service.isBusy)
    }

    private var secondaryButtons: some View {
        HStack(spacing: 12) {
            Button {
                Task { await service.refreshServices() }
            } label: {
                Label("刷新服务", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(service.isBusy)

            Button {
                showingCatalog = true
            } label: {
                Label("服务列表", systemImage: "list.bullet")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(service.services.isEmpty)
        }
    }

    private var hintSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("请先连接 SUSE 或 SUSE_Hostel Wi-Fi", systemImage: "wifi.exclamationmark")
            Label("iOS 无法读取 Wi-Fi 名称，登录时会自动只走 Wi-Fi", systemImage: "info.circle")
            Link(destination: service.portalHomeURL) {
                Label("打开学校认证页面", systemImage: "safari")
            }
            if service.configuration.block != nil {
                Button(role: .destructive) {
                    service.clearBlock()
                } label: {
                    Label("清除暂停状态", systemImage: "arrow.counterclockwise")
                }
            }
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, 4)
    }
}
