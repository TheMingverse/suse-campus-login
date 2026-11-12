import queue
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from campus_login.engine import LoginEngine
from campus_login.gui import Application
from campus_login.models import Settings, Status
from campus_login.notifications import MESSAGES, TITLE, NotificationController


def event(kind, number, *, code=None, key="wifi", generation=1):
    return Status(code or ("online" if kind in ("available", "connected") else kind),
                  "private-account secret http://example/?mac=private", "private-label",
                  kind, number, key, generation)


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.send, self.remove = Mock(), Mock()
        self.now = 100.
        self.controller = NotificationController(self.send, self.remove, generation=1, clock=lambda: self.now)
        self.controller.set_ready(True)

    def observe(self, kind, number, **kwargs):
        self.controller.observe(event(kind, number, **kwargs))

    def test_initial_online_only_once_across_checks_reconnects_and_connections(self):
        self.observe("available", 1)
        self.controller.observe(Status("checking", "checking"))
        self.observe("available", 2)
        self.controller.observe(Status("outside", "outside"))
        self.observe("available", 3, key="wired")
        self.send.assert_called_once_with(MESSAGES["available"], TITLE)

    def test_login_success_throttled_per_connection_and_no_redundant_available(self):
        self.observe("connected", 1)
        self.now += 59
        self.observe("connected", 2)
        self.assertEqual(self.send.call_count, 1)
        self.observe("connected", 3, key="wired")
        self.now += 1
        self.observe("connected", 4)
        self.observe("available", 5)
        self.assertEqual(self.send.call_count, 3)

    def test_same_fault_survives_pause_retry_and_unchanged_settings(self):
        self.observe("credentials", 1)
        for number, code in enumerate(("checking", "retry", "paused", "changed"), 2):
            self.controller.observe(Status(code, "ignored"))
            self.observe("credentials", number, key="another-interface")
        self.controller.configure(True, 2)
        self.observe("credentials", 10, generation=2)
        self.send.assert_called_once()

    def test_online_or_changed_credentials_rearms_fault(self):
        self.observe("manual", 1)
        self.observe("available", 2)
        self.observe("manual", 3)
        self.controller.configure(True, 2, credentials_changed=True)
        self.observe("manual", 4, generation=2)
        self.assertEqual(self.send.call_count, 4)

    def test_fixed_messages_do_not_leak_status_text_or_claim_wrong_password(self):
        for number, kind in enumerate(MESSAGES, 1):
            self.observe(kind, number, key=kind)
        for call in self.send.call_args_list:
            self.assertNotIn("private", str(call))
            self.assertNotIn("secret", str(call))
            self.assertNotIn("http://", str(call))
        self.assertNotIn("密码错误", MESSAGES["credentials"])
        self.assertIn("尚未确认", MESSAGES["campus_only"])
        self.assertNotIn("已自动连接", MESSAGES["campus_only"])

    def test_routine_and_unknown_events_are_silent(self):
        for number, code in enumerate(("checking", "retry", "outside", "uncertain", "setup", "error"), 1):
            self.controller.observe(event("unknown", number, code=code))
        self.send.assert_not_called()

    def test_delayed_tray_keeps_valid_first_success_across_checks(self):
        self.controller.set_ready(False)
        self.observe("available", 1)
        self.controller.observe(Status("checking", "checking"))
        self.observe("available", 2)
        self.send.assert_not_called()
        self.controller.set_ready(True)
        self.send.assert_called_once_with(MESSAGES["available"], TITLE)

    def test_delayed_tray_replaces_error_with_recovery(self):
        self.controller.set_ready(False)
        self.observe("credentials", 1)
        self.observe("connected", 2)
        self.controller.set_ready(True)
        self.send.assert_called_once_with(MESSAGES["connected"], TITLE)

    def test_pending_discarded_on_pause_leave_change_settings_or_tray_failure(self):
        for code in ("paused", "outside", "changed", "saved", "logging_in", "uncertain"):
            with self.subTest(code=code):
                controller = NotificationController(self.send, self.remove, generation=1)
                controller.observe(event("manual", 1))
                controller.observe(Status(code, "state changed"))
                controller.set_ready(True)
                self.send.assert_not_called()
        self.controller.set_ready(False)
        self.observe("connected", 1)
        self.controller.set_ready(False)
        self.controller.set_ready(True)
        self.send.assert_not_called()

    def test_disabled_events_consumed_no_history_when_reenabled(self):
        self.controller.configure(False, 1)
        self.remove.assert_called_once()
        self.observe("available", 1)
        self.observe("credentials", 2)
        self.controller.configure(True, 2)
        self.observe("credentials", 3, generation=2)
        self.observe("available", 4, generation=2)
        self.send.assert_not_called()
        self.observe("connected", 5, generation=2)
        self.send.assert_called_once_with(MESSAGES["connected"], TITLE)

    def test_disabled_pending_and_old_generation_never_reappear(self):
        self.controller.set_ready(False)
        self.observe("manual", 1)
        self.controller.configure(False, 2)
        self.controller.configure(True, 3)
        self.observe("connected", 2, generation=1)
        self.controller.set_ready(True)
        self.send.assert_not_called()

    def test_duplicate_event_does_not_clear_new_fault_or_redisplay(self):
        success = event("connected", 1)
        self.controller.observe(success)
        self.observe("manual", 2)
        self.controller.observe(success)
        self.observe("manual", 3)
        self.assertEqual(self.send.call_count, 2)

    def test_backend_failure_or_unsupported_notifications_do_not_raise(self):
        self.send.side_effect = OSError("backend failure")
        self.observe("credentials", 1)
        self.observe("credentials", 2)
        self.assertEqual(self.send.call_count, 1)
        self.send.side_effect = None
        self.send.return_value = False
        self.observe("connected", 3)
        self.assertFalse(self.controller.last_success)

    def test_close_clears_pending_removes_and_stops_callbacks(self):
        self.controller.set_ready(False)
        self.observe("manual", 1)
        self.remove.side_effect = RuntimeError("already destroyed")
        self.controller.close()
        self.controller.set_ready(True)
        self.observe("connected", 2)
        self.send.assert_not_called()
        self.assertIsNone(self.controller.pending)


class NotificationGuiTests(unittest.TestCase):
    def app(self):
        app = Application.__new__(Application)
        app.root = Mock()
        app.queue = queue.Queue()
        app.engine = LoginEngine(Mock(), Mock(), app.queue.put)
        app.engine.update_settings(Settings("test-student", "test-password"))
        app.icon = Mock(HAS_NOTIFICATION=True)
        app.ui_check, app.exiting, app.tray_ready, app.paused = False, False, False, False
        app.network_text, app.status_text, app.updated, app.logger = Mock(), Mock(), Mock(), Mock()
        app.last_status, app.last_log = None, None
        app.notifications = NotificationController(app._send_notification, app._remove_notification,
                                                   generation=app.engine.generation)
        app.username, app.password, app.service = Mock(), Mock(), Mock()
        app.username.get.return_value, app.password.get.return_value = "test-student", "test-password"
        app.service.get.return_value = "宜宾移动校园宽带"
        app.service_choices = {"宜宾移动校园宽带": "宜宾移动"}
        app.catalog_event = None
        app.refresh_button, app.service_hint, app.service_box = Mock(), Mock(), Mock()
        app.autostart, app.notifications_enabled, app.pause_button, app.store = Mock(), Mock(), Mock(), Mock()
        app.autostart.get.return_value = True
        app.notifications_enabled.get.return_value = False
        return app

    def test_queued_result_before_tray_ready_is_delivered_once(self):
        app = self.app()
        app.queue.put(event("available", 1))
        app.queue.put("tray_ready")
        app._drain()
        app.icon.notify.assert_called_once_with(MESSAGES["available"], TITLE)

    def test_ui_check_diagnostic_and_unsupported_backend_are_silent(self):
        app = self.app()
        app.ui_check, app.tray_ready = True, True
        app.notifications.set_ready(True)
        app._status(event("connected", 1))
        app.icon.notify.assert_not_called()
        self.assertFalse(app._send_notification("message", TITLE))
        app.ui_check = False
        app.icon.HAS_NOTIFICATION = False
        self.assertFalse(app._send_notification("message", TITLE))
        app.icon.notify.assert_not_called()

    def test_save_failure_keeps_effective_notification_setting(self):
        app = self.app()
        app.store.save.side_effect = OSError("synthetic failure")
        before = app.engine.settings
        with patch("campus_login.gui.messagebox.showerror") as error, \
             patch("campus_login.gui.set_autostart") as autostart:
            app.save()
        self.assertEqual(app.engine.settings, before)
        self.assertTrue(app.notifications.enabled)
        error.assert_called_once()
        autostart.assert_not_called()

    def test_saved_disable_updates_controller_and_dismisses_current_notification(self):
        app = self.app()
        app.tray_ready = True
        with patch("campus_login.gui.set_autostart"):
            app.save()
        self.assertFalse(app.engine.settings.notifications_enabled)
        self.assertFalse(app.notifications.enabled)
        app.icon.remove_notification.assert_called_once()
        saved = app.store.save.call_args.args[0]
        self.assertFalse(saved.notifications_enabled)

    def test_stale_queued_status_cannot_show_or_overwrite_current_ui(self):
        app = self.app()
        app.engine.update_settings(replace(app.engine.settings, password="changed"))
        app._status(event("connected", 1))
        app.status_text.set.assert_not_called()
        app.icon.notify.assert_not_called()

    def test_pause_clears_pending_but_preserves_fault_latch(self):
        app = self.app()
        app._status(event("credentials", 1))
        self.assertIsNotNone(app.notifications.pending)
        app.toggle_pause()
        self.assertIsNone(app.notifications.pending)
        self.assertIn("credentials", app.notifications.faults)

    def test_tray_failure_keeps_window_and_never_uses_blocking_notification_fallback(self):
        app = self.app()
        icon = app.icon
        app.queue.put(event("connected", 1))
        app.queue.put("tray_error")
        with patch("campus_login.gui.messagebox.showwarning") as warning:
            app._drain()
        warning.assert_not_called()
        icon.stop.assert_called_once()
        app.root.deiconify.assert_called_once()
        self.assertIsNone(app.notifications.pending)
        self.assertIsNone(app.icon)

    def test_notification_backend_exception_does_not_stop_status_updates(self):
        app = self.app()
        app.tray_ready = True
        app.notifications.set_ready(True)
        app.icon.notify.side_effect = RuntimeError("synthetic API error")
        app._status(event("connected", 1))
        app._status(Status("checking", "still checking"))
        self.assertEqual(app.status_text.set.call_args.args[0], "still checking")

    def test_changing_only_switch_preserves_fault_but_new_password_rearms(self):
        app = self.app()
        app._status(event("credentials", 1))
        with patch("campus_login.gui.set_autostart"):
            app.save()
            self.assertIn("credentials", app.notifications.faults)
            app.password.get.return_value = "changed-password"
            app.save()
        self.assertFalse(app.notifications.faults)


if __name__ == "__main__":
    unittest.main()
