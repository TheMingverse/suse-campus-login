"""Notification policy, independent of Tk/Windows and of private status text."""

import time


TITLE = "SUSE 校园网助手"
MESSAGES = {
    "available": "当前连接可以上网，无需重新登录。",
    "connected": "校园网已自动连接，已确认可以上网。",
    "credentials": "账号认证未通过，请检查账号、密码和运营商，再保存并测试。",
    "manual": "校园网需要手动处理，请打开官方登录页查看详情。",
    "unsupported": "校园网认证方式需要适配，请打开官方登录页，并查看连接诊断。",
    "campus_only": "校内网认证已接受，请打开校内网站确认；尚未确认可以访问互联网。",
    "service_required": "上网服务需要重新确认，请打开设置，刷新服务列表，选择后保存并测试。",
}
SUCCESS_KINDS = frozenset({"available", "connected"})
CLEAR_PENDING_CODES = frozenset({"paused", "outside", "changed", "saved", "address_wait",
                                "network_error", "wifi_error", "setup", "error", "uncertain",
                                "retry", "logging_in"})


class NotificationController:
    """Observe all events even when disabled, so enabling never replays history.

    All methods are called on the UI thread. The backend is best effort: a
    successful API call does not prove Windows displayed the notification.
    """

    def __init__(self, send, remove, *, enabled=True, generation=0, clock=time.monotonic):
        self.send, self.remove, self.clock = send, remove, clock
        self.enabled, self.generation = enabled, generation
        self.ready = False
        self.closed = False
        self.pending = None
        self.last_event_id = 0
        self.seen_online = False
        self.faults = set()
        self.last_success = {}

    def configure(self, enabled, generation, *, credentials_changed=False):
        self.pending = None
        self.generation = generation
        self.enabled = enabled
        if credentials_changed:
            self.faults.clear()
        if not enabled:
            self._remove()

    def set_ready(self, ready):
        if self.closed:
            return
        self.ready = ready
        if ready:
            self._flush()
        else:
            self.pending = None

    def observe(self, status):
        if self.closed or (status.generation is not None and status.generation != self.generation):
            return
        if status.notice_kind and status.notice_id <= self.last_event_id:
            return
        if status.code in CLEAR_PENDING_CODES:
            self.pending = None
        if status.code == "online":
            # Clear stale errors even if this is a silent repeat of ONLINE.
            if (self.pending is not None and
                    (self.pending.notice_kind not in SUCCESS_KINDS
                     or self.pending.connection_key != status.connection_key)):
                self.pending = None
            self.faults.clear()
        kind = status.notice_kind
        if kind not in MESSAGES or status.notice_id <= self.last_event_id:
            return
        self.last_event_id = status.notice_id
        if kind in SUCCESS_KINDS:
            first_online = not self.seen_online
            self.seen_online = True
            if kind == "available" and not first_online:
                # A newer ONLINE confirms a pending startup success is still valid.
                return
        else:
            if kind in self.faults:
                return
            self.faults.add(kind)
            self.pending = None
        if not self.enabled:
            return
        self.pending = status
        self._flush()

    def _flush(self):
        if self.closed or not self.ready or not self.enabled or self.pending is None:
            return
        status, self.pending = self.pending, None
        now = self.clock()
        if (status.notice_kind in SUCCESS_KINDS
                and now - self.last_success.get(status.connection_key, float("-inf")) < 60):
            return
        try:
            sent = self.send(MESSAGES[status.notice_kind], TITLE)
        except Exception:
            return
        if sent is not False and status.notice_kind in SUCCESS_KINDS:
            self.last_success[status.connection_key] = now

    def _remove(self):
        try:
            self.remove()
        except Exception:
            pass

    def close(self):
        self.pending = None
        self.ready = False
        self.closed = True
        self._remove()
