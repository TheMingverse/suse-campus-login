"""Main-thread macOS services and per-user single instance lock."""
import fcntl
from pathlib import Path
from .storage import data_dir


def acquire_instance():
    stream = (data_dir() / 'instance.lock').open('a')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        return None
    return stream


def set_autostart(enabled):
    import ServiceManagement as SM
    service = SM.SMAppService.mainAppService()
    if enabled:
        success, error = service.registerAndReturnError_(None)
    else:
        success, error = service.unregisterAndReturnError_(None)
    if not success:
        raise OSError('无法设置登录时启动，请在系统设置中检查登录项')
    return int(service.status())


def startup_status():
    import ServiceManagement as SM
    return int(SM.SMAppService.mainAppService().status())


class NotificationBackend:
    def __init__(self):
        import UserNotifications as UN
        self.center = UN.UNUserNotificationCenter.currentNotificationCenter()
        self.allowed = False

    def authorize(self):
        import UserNotifications as UN
        self.center.requestAuthorizationWithOptions_completionHandler_(
            UN.UNAuthorizationOptionAlert | UN.UNAuthorizationOptionSound,
            self._authorized)

    def _authorized(self, allowed, error):
        self.allowed = bool(allowed) and error is None

    def send(self, message, title):
        import UserNotifications as UN
        import uuid
        if not self.allowed:
            return False
        content = UN.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(message)
        request = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(str(uuid.uuid4()), content, None)
        self.center.addNotificationRequest_withCompletionHandler_(request, None)
        return True

    def remove(self):
        self.center.removeAllDeliveredNotifications()
        self.center.removeAllPendingNotificationRequests()
