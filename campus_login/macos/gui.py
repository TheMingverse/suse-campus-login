"""AppKit owns the main thread; the shared login engine runs in one worker."""
import json
import logging
from logging.handlers import RotatingFileHandler
import queue
import threading
from pathlib import Path

import objc
import AppKit as A
import Foundation as F
import CoreLocation as CL

from ..engine import LoginEngine
from ..models import Settings, Status, ServiceCatalogEvent, PORTAL_HOME, NetworkSnapshot
from ..notifications import NotificationController
from . import VERSION
from .network import network_snapshot
from .transport import NetworkContext
from .storage import SettingsStore, data_dir
from .system import NotificationBackend, set_autostart, startup_status


class Delegate(F.NSObject):
    @objc.python_method
    def configure(self, smoke=None):
        self.smoke = smoke
        self.events = queue.Queue()
        self.exiting = False
        self.paused = False
        self.catalog = None
        self.options = []
        self.store = SettingsStore()
        self.settings = Settings()
        self.load_error = False
        if not smoke:
            try:
                self.settings = self.store.load()
            except (OSError, ValueError, KeyError, TypeError):
                self.load_error = True
        self.engine = LoginEngine((lambda: NetworkSnapshot()) if smoke else network_snapshot,
                                  NetworkContext, self.events.put)
        self.engine.update_settings(self.settings)
        self.backend = None if smoke else NotificationBackend()
        self.notices = NotificationController(
            self.backend.send if self.backend else lambda *a: False,
            self.backend.remove if self.backend else lambda: None,
            enabled=self.settings.notifications_enabled, generation=self.engine.generation)
        self.logger = logging.getLogger('campus_macos')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if not smoke:
            handler = RotatingFileHandler(data_dir() / 'status.log', maxBytes=128000, backupCount=2, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            self.logger.addHandler(handler)
        self.last_log = None

    def applicationDidFinishLaunching_(self, notification):
        self.build()
        self.timer = F.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, 'tick:', None, True)
        self.notices.set_ready(True)
        self.engine.start()
        if self.smoke:
            self.window.makeKeyAndOrderFront_(None)
            A.NSApp.activateIgnoringOtherApps_(True)
            F.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                3.0, self, 'smokeFinish:', None, False)
        else:
            self.location = CL.CLLocationManager.alloc().init()
            self.location.setDelegate_(self)
            # Only the app requests authorization, on the main thread.
            self.location.requestWhenInUseAuthorization()
            if self.settings.notifications_enabled:
                self.backend.authorize()
            if self.load_error:
                self.status.setStringValue_('无法读取原设置，请重新填写账号密码并保存。')
            self.window.makeKeyAndOrderFront_(None)
            A.NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def label(self, text, x, y, width, height=24):
        field = A.NSTextField.labelWithString_(text)
        field.setFrame_(((x, y), (width, height)))
        self.window.contentView().addSubview_(field)
        return field

    @objc.python_method
    def button(self, text, action, x, y, width=125):
        b = A.NSButton.buttonWithTitle_target_action_(text, self, action)
        b.setFrame_(((x, y), (width, 32)))
        self.window.contentView().addSubview_(b)
        return b

    @objc.python_method
    def build(self):
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (720, 590)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable |
            A.NSWindowStyleMaskMiniaturizable, A.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_('SUSE 校园网助手 · Mac')
        self.window.center()
        self.window.setDelegate_(self)
        title = self.label('连上校园网，登录交给它。', 28, 530, 650, 38)
        title.setFont_(A.NSFont.boldSystemFontOfSize_(26))
        self.label('校园网线 · SUSE_Hostel / SUSE · 网线优先', 28, 500, 660)
        self.status = self.label('请填写自己的校园网账号、密码和上网服务。', 28, 435, 660, 54)
        self.username = A.NSTextField.alloc().initWithFrame_(((145, 391), (540, 28)))
        self.password = A.NSSecureTextField.alloc().initWithFrame_(((145, 346), (540, 28)))
        for view, name, y, value in ((self.username, '校园网账号', 395, self.settings.username),
                                     (self.password, '校园网密码', 350, self.settings.password)):
            self.label(name, 28, y, 110)
            view.setStringValue_(value)
            self.window.contentView().addSubview_(view)
        self.label('上网服务', 28, 305, 110)
        self.service = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((145, 298), (390, 32)), False)
        self.service.addItemWithTitle_(self.settings.service)
        self.window.contentView().addSubview_(self.service)
        self.refresh_button = self.button('刷新服务列表', 'refresh:', 545, 298, 140)
        self.hint = self.label('连接校园网后获取服务列表。', 145, 251, 540, 42)
        self.autostart = A.NSButton.checkboxWithTitle_target_action_('登录 Mac 时自动运行', None, None)
        self.notifications = A.NSButton.checkboxWithTitle_target_action_('显示系统通知', None, None)
        for b, y, enabled in ((self.autostart, 219, self.settings.autostart),
                               (self.notifications, 187, self.settings.notifications_enabled)):
            b.setFrame_(((28, y), (620, 28)))
            b.setState_(A.NSControlStateValueOn if enabled else A.NSControlStateValueOff)
            self.window.contentView().addSubview_(b)
        self.label('密码保存在 Mac 钥匙串中。', 28, 158, 650)
        self.button('保存并测试', 'save:', 28, 111)
        self.button('立即检查', 'check:', 165, 111)
        self.pause_button = self.button('暂停自动登录', 'pause:', 302, 111, 150)
        self.button('连接诊断', 'diagnose:', 464, 111, 105)
        self.button('退出程序', 'quit:', 581, 111, 105)
        self.button('打开官方登录页', 'portal:', 28, 66, 165)
        self.button('打开记录文件夹', 'folder:', 205, 66, 165)
        self.label(f'版本 {VERSION} · 关闭窗口后在菜单栏继续运行', 28, 23, 660)
        self.status_item = A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
        self.status_item.button().setTitle_('校园网')
        menu = A.NSMenu.alloc().init()
        for title, action in [('打开设置', 'show:'), ('立即检查', 'check:'),
                              ('暂停 / 恢复', 'pause:'), ('退出程序', 'quit:')]:
            item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
            item.setTarget_(self)
            menu.addItem_(item)
        self.status_item.setMenu_(menu)

    def windowShouldClose_(self, window):
        window.orderOut_(None)
        return False

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return False

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
        self.show_(None)
        return True

    def locationManagerDidChangeAuthorization_(self, manager):
        self.engine.check_now()

    def tick_(self, timer):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, ServiceCatalogEvent):
                if not self.engine.catalog_event_current(event):
                    continue
                self.catalog = event
                self.refresh_button.setEnabled_(True)
                self.hint.setStringValue_(event.text)
                if event.outcome == 'ready':
                    previous = self.service.titleOfSelectedItem()
                    self.options = [o.name for o in event.options if o.available]
                    self.service.removeAllItems()
                    if previous not in self.options:
                        self.service.addItemWithTitle_(previous)
                    self.service.addItemsWithTitles_(self.options)
                    self.service.selectItemWithTitle_(previous)
                elif event.outcome == 'invalidated':
                    previous = self.service.titleOfSelectedItem()
                    self.options = []
                    self.service.removeAllItems()
                    self.service.addItemWithTitle_(previous)
            elif isinstance(event, Status):
                if event.generation is not None and event.generation != self.engine.generation:
                    continue
                text = event.text.replace('Windows 11', 'macOS').replace('Windows', '系统')
                if (event.code == 'wifi_error' or (event.code == 'outside'
                        and self.engine.snapshot and self.engine.snapshot.wifi_unavailable)):
                    text = '无法读取校园 Wi-Fi 名称，请在系统设置 → 隐私与安全性 → 定位服务中允许本应用。'
                self.status.setStringValue_(text)
                if event.code != self.last_log:
                    self.logger.info('state=%s', event.code)
                    self.last_log = event.code
                self.notices.observe(event)
            elif isinstance(event, str):
                self.report(event)

    @objc.python_method
    def alert(self, text):
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_('校园网助手')
        alert.setInformativeText_(text)
        alert.runModal()

    def save_(self, sender):
        if self.smoke:
            return
        username, password = self.username.stringValue().strip(), self.password.stringValue()
        if not username or not password or len(username) > 200 or len(password) > 1000:
            self.alert('请填写有效的校园网账号和密码。')
            return
        name = self.service.titleOfSelectedItem()
        current = self.catalog is not None and self.engine.catalog_event_current(self.catalog)
        if ((current and self.catalog.outcome == 'ready' and name not in self.options)
                or (name != self.settings.service and (not current or name not in self.options))):
            self.alert('请刷新服务列表，选择服务后保存。')
            return
        settings = Settings(username, password, name, bool(self.autostart.state()), bool(self.notifications.state()))
        try:
            self.store.save(settings)
        except (OSError, ValueError):
            self.alert('无法保存设置，请检查钥匙串访问权限后重试。')
            return
        startup_message = ''
        try:
            status = set_autostart(settings.autostart)
            if settings.autostart and status != 1:
                startup_message = '登录时启动需要在系统设置 → 通用 → 登录项中确认。'
        except Exception:
            startup_message = '设置已保存；登录时启动未设置成功，请检查系统登录项。'
        changed = (self.settings.username, self.settings.password, self.settings.service) != (username, password, name)
        self.settings = settings
        self.paused = False
        self.pause_button.setTitle_('暂停自动登录')
        self.engine.set_paused(False)
        self.engine.update_settings(settings)
        self.notices.configure(settings.notifications_enabled, self.engine.generation, credentials_changed=changed)
        if settings.notifications_enabled:
            self.backend.authorize()
        self.status.setStringValue_('设置已保存，正在检查网络。')
        if startup_message:
            self.alert(startup_message)

    def refresh_(self, sender):
        self.refresh_button.setEnabled_(False)
        self.engine.request_services()

    def check_(self, sender):
        if self.paused:
            self.pause_(None)
        self.engine.check_now()

    def pause_(self, sender):
        self.paused = not self.paused
        self.pause_button.setTitle_('恢复自动登录' if self.paused else '暂停自动登录')
        self.engine.set_paused(self.paused)
        self.notices.configure(self.settings.notifications_enabled, self.engine.generation)

    def show_(self, sender):
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)

    def portal_(self, sender):
        A.NSWorkspace.sharedWorkspace().openURL_(F.NSURL.URLWithString_(PORTAL_HOME))

    def folder_(self, sender):
        A.NSWorkspace.sharedWorkspace().openURL_(F.NSURL.fileURLWithPath_(str(data_dir())))

    def diagnose_(self, sender):
        def run():
            lines = [f'SUSE Mac {VERSION}', '连接诊断']
            try:
                snapshot = network_snapshot()
                for number, connection in enumerate(snapshot.connections, 1):
                    lines.append(f'连接 {number}：{connection.kind}；地址就绪：{connection.ready}')
                    if connection.eligible and connection.ready:
                        with NetworkContext(connection) as context:
                            def guard():
                                if network_snapshot() != snapshot:
                                    from ..models import Cancelled
                                    raise Cancelled()
                            result = context.probe.check(guard)
                        lines.append(f'网络状态：{result.state.value}')
                if snapshot.wifi_unavailable:
                    lines.append('无法读取 Wi-Fi 名称，请检查定位服务权限。')
            except Exception:
                lines.append('连接已变化或读取失败，请稍后重试。')
            self.events.put('\n'.join(lines))
        threading.Thread(target=run, daemon=True).start()

    @objc.python_method
    def report(self, text):
        pasteboard = A.NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, A.NSPasteboardTypeString)
        self.alert(text + '\n\n诊断结果已复制。')

    def smokeFinish_(self, timer):
        from ..models import ServiceOption
        # Exercise the native service picker with the same events as the worker.
        self.engine.set_paused(True)
        self.engine.thread.join(timeout=0.1)
        sequence = self.engine.catalog_sequence
        event = ServiceCatalogEvent(self.engine.generation, sequence, self.engine.snapshot,
                                    options=(ServiceOption('新服务'),), outcome='ready', text='合成列表')
        previous = self.service.titleOfSelectedItem()
        self.events.put(event)
        self.tick_(None)
        assert self.service.titleOfSelectedItem() == previous
        self.service.selectItemWithTitle_('新服务')
        self.events.put(event)
        self.tick_(None)
        assert self.service.titleOfSelectedItem() == '新服务'
        self.engine.set_paused(False)
        self.events.put(event)  # Obsolete generation must not replace a selection.
        self.tick_(None)
        assert self.service.titleOfSelectedItem() == '新服务'
        bounds = self.window.contentView().bounds()
        for control in self.window.contentView().subviews():
            frame = control.frame()
            assert frame.origin.x >= 0 and frame.origin.y >= 0
            assert frame.origin.x + frame.size.width <= bounds.size.width
            assert frame.origin.y + frame.size.height <= bounds.size.height
        startup = {}
        try:
            startup['before'] = startup_status()
            try:
                startup['registered'] = set_autostart(True)
            except OSError:
                startup['registration_requires_system_approval'] = True
        finally:
            try:
                startup['after_cleanup'] = set_autostart(False)
            except OSError:
                startup['cleanup_status'] = startup_status()
        assert all(isinstance(value, (int, bool)) for value in startup.values())
        self.engine.stop()
        self.engine.thread.join(timeout=5)
        assert not self.engine.thread.is_alive()
        assert self.window.isVisible() and self.status_item.menu().numberOfItems() == 4
        self.window.performClose_(None)
        assert not self.window.isVisible()
        self.show_(None)
        assert self.window.isVisible()
        self.pause_(None)
        assert self.engine.paused
        self.check_(None)
        assert not self.engine.paused
        rect = self.window.frame()
        Path(self.smoke).write_text(json.dumps(dict(
            window_visible=True, menu_items=4, close_keeps_app=True,
            pause_resume=True, engine_stopped=True, version=VERSION,
            frame=[rect.size.width, rect.size.height], controls=len(self.window.contentView().subviews()),
            service_selection_preserved=True, stale_service_ignored=True,
            controls_within_window=True, startup=startup)), encoding='utf-8')
        self.quit_(None)

    def quit_(self, sender):
        self.engine.stop()
        self.notices.close()
        self.timer.invalidate()
        A.NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
        A.NSApp.terminate_(None)
