"""Read-only report: no settings access, login calls, IP/MAC values or raw URLs."""

from . import __version__
from .adapters import network_snapshot
from .models import Cancelled, ProbeState
from .network import portal_diagnostic
from .transport import NetworkContext


def connection_report(read=network_snapshot, context_factory=NetworkContext):
    lines = [f"校园网连接诊断 · {__version__}", "此检查不提交账号密码；可复制以下内容给维护者。", ""]
    try:
        snapshot = read()
    except OSError:
        return "\n".join(lines + ["无法读取 Windows 网卡状态。"])
    if not snapshot.connections:
        lines.append("未识别到可读取的网络连接。" if snapshot.wifi_unavailable else "未发现已连接的实体网卡。")
    for number, connection in enumerate(snapshot.connections, 1):
        kind = "网线" if connection.kind == "ethernet" else "Wi-Fi"
        lines.append(f"连接 {number}：{kind}；地址和网关{'已就绪' if connection.ready else '尚未就绪'}")
        if not connection.eligible:
            lines.append("该 Wi-Fi 不在校园网名单中，未发送检测请求。")
            continue
        if not connection.ready:
            lines.append("等待地址分配，未发送检测请求。")
            continue

        def guard():
            if read() != snapshot:
                raise Cancelled()

        try:
            guard()
            with context_factory(connection) as context:
                result = context.probe.check(guard)
            guard()
            descriptions = {ProbeState.ONLINE: "这条连接已能上网，无需认证。",
                            ProbeState.PORTAL: "发现学校认证跳转，参数格式可识别。",
                            ProbeState.UNSUPPORTED: "发现学校认证跳转，但参数需要适配；未提交密码。",
                            ProbeState.UNKNOWN: "状态不明确；超时或未知页面不会触发登录。"}
            lines.append(descriptions[result.state])
            if result.portal_url:
                lines.append(portal_diagnostic(result.portal_url))
        except (Cancelled, OSError):
            lines.append("连接已变化或无法读取，请重新诊断。")
            break
        except Exception:
            lines.append("这条连接的只读检查未完成，请稍后重试。")
    if snapshot.wifi_unavailable:
        if any(item.kind == "wifi" for item in snapshot.connections):
            lines.append("部分无线接口暂时无法读取，其他正常连接仍可使用。")
        else:
            lines.append("无线连接信息均无法读取；请检查网卡或 Windows 位置信息权限。网线识别不依赖该权限。")
    lines += ["", "报告不含账号、密码、IP/MAC 地址或认证参数值。",
              "所有检测请求固定使用对应网卡；不修改路由，不断开网络。",
              "诊断结果不代表真实有线账号登录已验证成功。"]
    return "\n".join(lines)
