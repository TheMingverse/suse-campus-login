"""One worker, ordered connections, a fresh interface-bound context per attempt."""

import threading
import time

from .models import (Cancelled, PortalError, ProbeState, Settings, Status,
                     SERVICES, ServiceCatalogEvent)
from .network import portal_diagnostic
from .portal import require_service


class LoginEngine:
    def __init__(self, connections, context_factory, notify, clock=time.monotonic):
        self.connections, self.context_factory = connections, context_factory
        self.notify, self.clock = notify, clock
        self.settings = Settings()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.generation = 0
        self.paused = False
        self.blocked = None
        self.blocked_notice = ""
        self.notice_sequence = 0
        self.snapshot = None
        self.failures = 0
        self.next_check = 0.0
        self.thread = None
        self.catalog_sequence = 0
        self.refresh_pending = False
        self.catalog_options = None
        self.catalog_connection = None

    def _invalidate_catalog(self):
        self.catalog_sequence += 1
        self.catalog_options = None
        self.catalog_connection = None
        self.notify(ServiceCatalogEvent(self.generation, self.catalog_sequence, self.snapshot,
                                       outcome="invalidated", text="连接或设置已变化，服务列表待更新。"))

    def catalog_event_current(self, event):
        with self.lock:
            return (not self.stop_event.is_set() and event.generation == self.generation
                    and event.request_id == self.catalog_sequence and event.snapshot == self.snapshot)

    def request_services(self):
        with self.lock:
            self.catalog_sequence += 1
            self.refresh_pending = True
        self.wake.set()

    def _catalog_event(self, snapshot, generation, request_id, connection=None,
                       options=(), outcome="ready", text="学校服务列表已更新，选择后点击“保存并测试”。"):
        with self.lock:
            if generation != self.generation or request_id != self.catalog_sequence:
                return
            if outcome == "ready":
                self.catalog_options, self.catalog_connection = options, connection
            self.notify(ServiceCatalogEvent(generation, request_id, snapshot, connection,
                                           options, outcome, text))

    def update_settings(self, settings):
        with self.lock:
            self.settings = settings
            self.generation += 1
            self.blocked = None
            self.blocked_notice = ""
            self.failures = 0
            self.next_check = 0
            self.refresh_pending = False
            self._invalidate_catalog()
        self.wake.set()

    def set_paused(self, paused):
        with self.lock:
            self.paused = paused
            self.generation += 1
            self.next_check = 0
            self.refresh_pending = False
            self._invalidate_catalog()
        self.wake.set()

    def check_now(self):
        with self.lock:
            if self.blocked == "manual":
                self.blocked = None
                self.blocked_notice = ""
            self.next_check = 0
        self.wake.set()

    def emit(self, code, text, connection=None, *, notice_kind="", generation=None):
        with self.lock:
            if generation is not None and generation != self.generation:
                return
            if notice_kind:
                self.notice_sequence += 1
            self.notify(Status(code, text, connection.label if connection else "等待连接",
                               notice_kind, self.notice_sequence if notice_kind else 0,
                               f"{connection.kind}:{connection.interface_id}:{connection.ssid}" if connection else "",
                               self.generation))

    def start(self):
        self.thread = threading.Thread(target=self._run, name="campus-network", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        with self.lock:
            self.generation += 1

    def _run(self):
        while not self.stop_event.is_set():
            self.wake.clear()
            try:
                self.step()
            except Exception:
                # Never leak exception repr: requests exceptions may include URLs.
                self.emit("error", "检查遇到异常，已停止本次操作。可稍后重试或查看使用说明。")
                with self.lock:
                    self.next_check = self.clock() + 15
                    self._catalog_event(self.snapshot, self.generation, self.catalog_sequence,
                                        outcome="unavailable", text="服务读取未完成，请稍后刷新。")
            self.wake.wait(1)

    def step(self):
        with self.lock:
            settings, generation, paused = self.settings, self.generation, self.paused
            refresh = self.refresh_pending
            self.refresh_pending = False
        if paused and not refresh:
            self.emit("paused", "自动登录已暂停，可点击“恢复自动登录”。")
            return
        try:
            snapshot = self.connections()
        except OSError:
            if refresh:
                self._catalog_event(self.snapshot, generation, self.catalog_sequence, outcome="unavailable",
                                    text="无法读取网卡状态，请稍后刷新服务列表。")
                return
            self.emit("network_error", "无法读取网卡状态，请检查网卡或稍后重试。")
            return
        with self.lock:
            if snapshot != self.snapshot:
                self.snapshot = snapshot
                self.next_check = 0
                self.failures = 0
                self._invalidate_catalog()
            catalog_request = self.catalog_sequence
            if not snapshot.candidates:
                if refresh:
                    self._catalog_event(snapshot, generation, catalog_request, outcome="unavailable",
                                        text="请先连接校园网并等待地址就绪，再刷新服务列表。")
                    return
                waiting = next((c for c in snapshot.connections if c.eligible), None)
                if waiting:
                    self.emit("address_wait", "已连接，正在等待 Windows 分配有效的 IPv4 地址和网关；暂不认证。", waiting)
                elif snapshot.wifi_unavailable:
                    if any(item.kind == "wifi" for item in snapshot.connections):
                        self.emit("outside", "部分无线接口暂时无法读取；其他已识别的 Wi-Fi 不在校园网名单中，暂不认证。")
                    else:
                        self.emit("wifi_error", "无线连接信息均无法读取。请检查网卡；Windows 11 可能需要允许桌面应用访问位置信息。")
                else:
                    self.emit("outside", "等待连接网线、SUSE_Hostel 或 SUSE；其他 Wi-Fi 不会提交登录信息。")
                return
            if not refresh and self.clock() < self.next_check:
                return
            if not refresh:
                self.next_check = self.clock() + 15

        def guard():
            with self.lock:
                if (self.stop_event.is_set() or (self.paused and not refresh)
                        or self.generation != generation or catalog_request != self.catalog_sequence
                        or (not refresh and self.refresh_pending)):
                    raise Cancelled()
            try:
                current = self.connections()
            except OSError:
                raise Cancelled() from None
            if current != snapshot:
                raise Cancelled()

        connection = None
        prepared = None
        try:
            for connection in snapshot.candidates:
                guard()
                if not refresh:
                    self.emit("checking", "正在单独检查这条连接是否可以上网……", connection)
                # Cookies and pooled sockets never survive this connection's cycle.
                with self.context_factory(connection) as context:
                    result = context.probe.check(guard)
                    guard()
                    if result.state is ProbeState.ONLINE:
                        if refresh:
                            self._catalog_event(snapshot, generation, catalog_request, connection,
                                                outcome="unavailable", text="当前已在线，暂无法更新服务列表。原选择已保留。")
                            return
                        with self.lock:
                            self.failures = 0
                        self.emit("online", "这条连接已能上网，无需重复登录。", connection,
                                  notice_kind="available", generation=generation)
                        return
                    if result.state is ProbeState.UNKNOWN:
                        continue
                    if result.state is ProbeState.UNSUPPORTED:
                        if refresh:
                            self._catalog_event(snapshot, generation, catalog_request, connection,
                                                outcome="unavailable", text="认证参数暂不支持，请打开官方登录页。未提交账号密码。")
                            return
                        with self.lock:
                            self.blocked = self.blocked or "manual"
                            self.blocked_notice = self.blocked_notice or "unsupported"
                        prefix = "有线认证参数需要适配" if connection.kind == "ethernet" else "校园 Wi-Fi 认证参数需要适配"
                        self.emit("unsupported", prefix + "，未提交账号密码。请使用“连接诊断”并打开官方页面。" +
                                  portal_diagnostic(result.portal_url), connection,
                                  notice_kind="unsupported", generation=generation)
                        return
                    with self.lock:
                        blocked = self.blocked
                    if refresh:
                        prepared = context.portal.prepare(result.portal_url, guard)
                        guard()
                        self._catalog_event(snapshot, generation, catalog_request, connection, prepared.services)
                        return
                    if blocked:
                        text = ("认证未通过，自动尝试已停止。请检查账号密码后点击“保存并测试”。"
                                if blocked == "credentials" else
                                "请刷新服务列表，重新选择上网服务后点击“保存并测试”。"
                                if blocked == "service_required" else
                                "需要手动处理，请打开官方登录页面；处理后点击“立即检查”。")
                        self.emit(blocked, text, connection,
                                  notice_kind=self.blocked_notice or blocked, generation=generation)
                        return
                    missing_credentials = not settings.username or not settings.password
                    if (missing_credentials and self.catalog_options is not None
                            and self.catalog_connection == connection):
                        self.emit("setup", "校园网要求登录。请填写账号、密码和运营商，再点击“保存并测试”。", connection)
                        return
                    with self.lock:
                        if (self.refresh_pending or self.generation != generation
                                or catalog_request != self.catalog_sequence):
                            raise Cancelled()
                        self.catalog_sequence += 1
                        catalog_request = self.catalog_sequence
                    guard()
                    prepared = context.portal.prepare(result.portal_url, guard)
                    guard()
                    self._catalog_event(snapshot, generation, catalog_request, connection, prepared.services)
                    if missing_credentials:
                        self.emit("setup", "学校服务列表已获取，请填写账号密码、选择服务后保存并测试。", connection)
                        return
                    require_service(prepared.services, settings.service)
                    guard()
                    self.emit("logging_in", "已确认这条连接要求校园网认证，正在登录……", connection)
                    context.portal.authenticate(result.portal_url, settings, guard, prepared=prepared)
                    guard()
                    verified = context.probe.check(guard)
                    guard()
                    if verified.state is ProbeState.ONLINE:
                        with self.lock:
                            self.failures = 0
                        self.emit("online", "登录成功，已确认这条连接可以上网。", connection,
                                  notice_kind="connected", generation=generation)
                    elif settings.service == "校园网":
                        with self.lock:
                            self.blocked = "manual"
                            self.blocked_notice = "campus_only"
                        self.emit("manual", "学校已接受校内网登录；该服务可能只开放校内资源。请打开校内网站确认。", connection,
                                  notice_kind="campus_only", generation=generation)
                    elif settings.service not in SERVICES.values():
                        raise PortalError("manual", "学校已接受新服务认证，但尚未确认互联网可用；请打开官方页面确认服务范围，暂不重复提交。")
                    else:
                        raise PortalError("temporary", "学校已接受登录，但尚未确认这条连接能够上网。")
                    return
            if refresh:
                self._catalog_event(snapshot, generation, catalog_request, outcome="unavailable",
                                    text="未发现明确的学校认证跳转，暂无法更新服务列表。原选择已保留。")
            else:
                self.emit("uncertain", "暂时无法确认上网状态，也未发现明确的学校登录要求；稍后再检查。", connection)
        except Cancelled:
            with self.lock:
                if not refresh:
                    self.next_check = 0
                if generation == self.generation and catalog_request == self.catalog_sequence:
                    self._invalidate_catalog()
            self.emit("changed", "网络或设置已变化，旧请求会话已结束，正在重新检查。")
        except PortalError as error:
            try:
                guard()
            except Cancelled:
                return
            if refresh:
                self._catalog_event(snapshot, generation, catalog_request, connection,
                                    outcome="ready" if error.kind == "service_required" else "unavailable",
                                    text=str(error))
                return
            if error.kind == "service_required":
                # A malformed/empty response must not leave an old list selectable.
                if prepared is None:
                    self._catalog_event(snapshot, generation, catalog_request, connection, (),
                                        text=str(error))
            with self.lock:
                if generation != self.generation or catalog_request != self.catalog_sequence:
                    return
                if error.kind == "temporary":
                    self.failures += 1
                    if self.failures <= 3:
                        delay = (5, 15, 30)[self.failures - 1]
                        self.next_check = self.clock() + delay
                        text = f"{error} {delay} 秒后重新检查（重试 {self.failures}/3）。"
                    else:
                        self.failures = 0
                        self.next_check = self.clock() + 300
                        text = "连续尝试未成功，暂停五分钟；也可以点击“立即检查”。"
                    self.emit("retry", text, connection)
                else:
                    self.blocked = error.kind
                    self.blocked_notice = error.kind
                    self.emit(error.kind, str(error), connection,
                              notice_kind=error.kind, generation=generation)
