"""Service discovery uses only synthetic responses and temporary settings."""
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch

import requests

from campus_login.models import (Settings, ServiceOption, ServiceCatalogEvent, Status,
                                 PortalError, Cancelled, NetworkSnapshot, valid_service_name)
from campus_login.portal import PortalClient, parse_services, require_service, component
from campus_login.engine import LoginEngine
from campus_login.storage import SettingsStore
from campus_login.notifications import NotificationController, MESSAGES
from test_portal import Session, URL
from test_engine import WIFI, WIRED, ONLINE, PORTAL, UNKNOWN
import test_notifications
import test_interfaces


def services(*names):
    return {"serviceJson": [{"serviceName": name} for name in names]}


class ServiceParsingTests(unittest.TestCase):
    def test_list_and_json_string_and_new_name(self):
        for payload in (services("新版移动服务", "另一项"),
                        {"serviceJson": json.dumps(services("新版移动服务", "另一项")["serviceJson"])}):
            self.assertEqual(parse_services(payload), (ServiceOption("新版移动服务"), ServiceOption("另一项")))

    def test_same_configuration_deduplicated_independent_of_key_order(self):
        options = parse_services({"serviceJson": [
            {"serviceName": "A", "domainName": False}, {"domainName": False, "serviceName": "A"}]})
        self.assertEqual(options, (ServiceOption("A"),))

    def test_conflicting_duplicate_stays_blocked_after_third_duplicate(self):
        for items in ([{"serviceName": "A", "id": 1}, {"serviceName": "A", "id": 2}],
                      [{"serviceName": "A"}, {"serviceName": "A", "domainName": True}, {"serviceName": "A"}]):
            options = parse_services({"serviceJson": items})
            self.assertFalse(options[0].available)
            with self.assertRaises(PortalError):
                require_service(options, "A")

    def test_hidden_extra_info_or_unknown_flag_cannot_auto_login(self):
        for flags in ({"aceNotShow": True}, {"aceNotShow": "true"},
                      {"domainName": "true"}, {"domainName": "unexpected"}):
            with self.subTest(flags=flags):
                options = parse_services({"serviceJson": [{"serviceName": "A", **flags}]})
                self.assertFalse(options[0].available)
                with self.assertRaises(PortalError):
                    require_service(options, "A")

    def test_empty_and_malformed_lists_fail_closed(self):
        for payload in ({}, {"serviceJson": []}, {"serviceJson": "[]"}, {"serviceJson": "bad"},
                        {"serviceJson": {}}, {"serviceJson": [None]},
                        {"serviceJson": [{"serviceName": 123}]},
                        {"serviceJson": [{"serviceName": "good"}, {"serviceName": "bad\n"}]}):
            with self.subTest(payload=payload), self.assertRaises(PortalError) as error:
                parse_services(payload)
            self.assertEqual(error.exception.kind, "service_required")

    def test_exact_match_only_no_keyword_or_whitespace_guess(self):
        options = parse_services(services("移动新套餐A", "移动新套餐B", " 宜宾移动"))
        with self.assertRaises(PortalError):
            require_service(options, "宜宾移动")
        self.assertEqual(require_service(options, "移动新套餐B").name, "移动新套餐B")

    def test_name_validation(self):
        for name in (None, 1, "", " ", "a" * 201, "a\n", "a\0", "a\x7f", "a\u200b"):
            self.assertFalse(valid_service_name(name))
        self.assertTrue(valid_service_name("新服务+&汉字"))
        self.assertTrue(valid_service_name("a" * 200))


class ServicePortalTests(unittest.TestCase):
    def test_prepare_has_no_credentials_and_authentication_reuses_two_requests(self):
        session = Session([{}, services("新服务+&汉字"), {"result": "success"}])
        client = PortalClient(session)
        prepared = client.prepare(URL)
        self.assertEqual(len(session.calls), 2)
        self.assertNotIn("wlanuserip", repr(prepared))
        self.assertNotIn("private", str(session.calls))
        client.authenticate(URL, Settings("synthetic-user", "synthetic-password", "新服务+&汉字"), prepared=prepared)
        self.assertEqual(len(session.calls), 3)
        wire = session.calls[-1][1]["data"].decode()
        self.assertIn("service=" + component(component("新服务+&汉字")), wire)
        for _, kwargs in session.calls[:2]:
            self.assertNotIn(b"synthetic-user", kwargs["data"])
            self.assertNotIn(b"synthetic-password", kwargs["data"])

    def test_prepared_data_cannot_cross_client_url_or_be_reused(self):
        session = Session([{}, services("宜宾移动"), {"result": "success"}])
        client = PortalClient(session)
        prepared = client.prepare(URL)
        with self.assertRaises(PortalError):
            PortalClient(Session([])).authenticate(URL, Settings("u", "p"), prepared=prepared)
        with self.assertRaises(PortalError):
            client.authenticate(URL + "&different=1", Settings("u", "p"), prepared=prepared)
        client.authenticate(URL, Settings("u", "p"), prepared=prepared)
        with self.assertRaises(PortalError):
            client.authenticate(URL, Settings("u", "p"), prepared=prepared)
        self.assertEqual(len(session.calls), 3)

    def test_renamed_hidden_ambiguous_empty_never_submit(self):
        payloads = [services("移动新服务"), services(),
                    {"serviceJson": [{"serviceName": "宜宾移动", "aceNotShow": True}]},
                    {"serviceJson": [{"serviceName": "宜宾移动", "id": 1}, {"serviceName": "宜宾移动", "id": 2}]}]
        for payload in payloads:
            session = Session([{}, payload])
            with self.subTest(payload=payload), self.assertRaises(PortalError):
                PortalClient(session).authenticate(URL, Settings("u", "secret"))
            self.assertEqual(len(session.calls), 2)

    def test_untrusted_or_missing_connection_parameters_do_not_prepare(self):
        for url in (URL.replace("10.23.2.4", "evil.example"), "http://10.23.2.4/eportal/index.jsp"):
            session = Session([])
            with self.assertRaises(PortalError):
                PortalClient(session).prepare(url)
            self.assertEqual(session.calls, [])

    def test_network_change_before_login_cancels_submission(self):
        session = Session([{}, services("宜宾移动")])
        client = PortalClient(session)
        prepared = client.prepare(URL)
        with self.assertRaises(Cancelled):
            client.authenticate(URL, Settings("u", "p"), lambda: (_ for _ in ()).throw(Cancelled()), prepared=prepared)
        self.assertEqual(len(session.calls), 2)

    def test_new_preparation_supersedes_old_one_even_for_same_url(self):
        session = Session([{}, services("宜宾移动"), {}, services("新服务")])
        client = PortalClient(session)
        old = client.prepare(URL)
        client.prepare(URL)
        with self.assertRaises(PortalError):
            client.authenticate(URL, Settings("u", "p"), prepared=old)
        self.assertEqual(len(session.calls), 4)


class ServiceEngineTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.snapshot = NetworkSnapshot((WIFI,))
        self.session = Session([{}, services("宜宾移动", "新服务"), {"result": "success"}])
        self.context = MagicMock()
        self.context.__enter__.return_value = self.context
        self.context.portal = PortalClient(self.session)
        self.context.probe.check.return_value = PORTAL
        self.events = []
        self.factory = Mock(return_value=self.context)
        self.engine = LoginEngine(lambda: self.snapshot, self.factory, self.events.append, lambda: self.now)
        self.engine.update_settings(Settings("test-user", "test-password"))

    def catalogs(self):
        return [event for event in self.events if isinstance(event, ServiceCatalogEvent) and event.outcome == "ready"]

    def test_missing_credentials_discovers_once_without_login(self):
        self.engine.update_settings(Settings())
        self.engine.step()
        self.assertEqual(len(self.session.calls), 2)
        self.assertEqual(len(self.catalogs()), 1)
        self.now += 15
        self.engine.step()
        self.assertEqual(len(self.session.calls), 2)
        self.assertEqual(self.events[-1].code, "setup")

    def test_normal_login_uses_same_preparation_and_verifies(self):
        self.context.probe.check.side_effect = [PORTAL, ONLINE]
        self.engine.step()
        self.assertEqual(len(self.session.calls), 3)
        self.assertEqual(self.events[-1].notice_kind, "connected")

    def test_refresh_is_read_only_preserves_password_block_and_pause(self):
        self.engine.snapshot = self.snapshot
        self.engine.blocked = "credentials"
        self.engine.blocked_notice = "credentials"
        self.engine.set_paused(True)
        self.engine.next_check = 800.
        self.engine.request_services()
        self.engine.step()
        self.assertEqual(len(self.session.calls), 2)
        self.assertTrue(self.engine.paused)
        self.assertEqual(self.engine.blocked, "credentials")
        self.assertEqual(self.engine.next_check, 800.)
        self.assertEqual(len(self.catalogs()), 1)

    def test_refresh_online_never_calls_school_endpoints(self):
        self.context.probe.check.return_value = ONLINE
        self.engine.request_services()
        self.engine.step()
        self.assertEqual(self.session.calls, [])
        self.assertIn("当前已在线", self.events[-1].text)
        self.assertEqual(self.events[-1].outcome, "unavailable")

    def test_online_automatic_never_fetches_services(self):
        self.context.probe.check.return_value = ONLINE
        self.engine.step()
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.events[-1].code, "online")

    def test_refresh_unknown_no_school_requests(self):
        self.context.probe.check.return_value = UNKNOWN
        self.engine.request_services()
        self.engine.step()
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.events[-1].outcome, "unavailable")

    def test_refresh_no_connection_has_final_event(self):
        self.snapshot = NetworkSnapshot()
        self.engine.request_services()
        self.engine.step()
        self.factory.assert_not_called()
        self.assertTrue(any(isinstance(e, ServiceCatalogEvent) and e.outcome == "unavailable" for e in self.events))

    def test_renamed_service_blocks_until_saved_not_check_or_pause(self):
        self.session.replies = iter([{}, services("移动新名称")])
        self.engine.step()
        self.assertEqual(self.engine.blocked, "service_required")
        self.assertEqual(self.events[-1].notice_kind, "service_required")
        self.engine.check_now()
        self.engine.step()
        self.engine.set_paused(True)
        self.engine.set_paused(False)
        self.engine.step()
        self.assertEqual(len(self.session.calls), 2)
        self.engine.update_settings(Settings("test-user", "test-password", "移动新名称"))
        self.session.replies = iter([{}, services("移动新名称"), {"result": "success"}])
        self.context.probe.check.side_effect = [PORTAL, ONLINE]
        self.engine.step()
        self.assertEqual(self.events[-1].notice_kind, "connected")
        self.assertEqual(len(self.session.calls), 5)

    def test_new_service_accepted_without_online_stops_repeated_submission(self):
        self.engine.update_settings(Settings("u", "p", "新服务"))
        self.engine.step()
        self.assertEqual(self.engine.blocked, "manual")
        self.now += 15
        self.engine.step()
        self.assertEqual(len(self.session.calls), 3)
        self.assertFalse(any(isinstance(e, Status) and e.notice_kind == "connected" for e in self.events))

    def test_malformed_list_clears_old_cache_without_login(self):
        self.engine.request_services()
        self.engine.step()
        self.session.replies = iter([{}, services()])
        self.engine.request_services()
        self.engine.step()
        self.assertEqual(self.engine.catalog_options, ())
        self.assertEqual(self.catalogs()[-1].options, ())
        self.assertEqual(len(self.session.calls), 4)

    def test_refresh_timeout_preserves_block_and_retry_schedule(self):
        self.engine.snapshot = self.snapshot
        self.engine.blocked = "credentials"
        self.engine.next_check = 500.
        self.session.post = Mock(side_effect=requests.Timeout())
        self.engine.request_services()
        self.engine.step()
        self.assertEqual(self.engine.blocked, "credentials")
        self.assertEqual(self.engine.next_check, 500.)
        self.assertEqual(self.events[-1].outcome, "unavailable")
        self.assertEqual(self.engine.failures, 0)

    def test_preparation_timeout_uses_original_retry_schedule(self):
        self.session.post = Mock(side_effect=requests.Timeout())
        self.engine.step()
        self.assertEqual(self.engine.next_check, self.now + 5)
        self.assertEqual(self.events[-1].code, "retry")

    def test_queued_catalog_invalidated_by_settings_pause_new_request_and_stop(self):
        self.engine.request_services()
        self.engine.step()
        event = self.catalogs()[-1]
        self.assertTrue(self.engine.catalog_event_current(event))
        for change in (lambda: self.engine.update_settings(Settings("new", "p")),
                       lambda: self.engine.set_paused(True), self.engine.request_services, self.engine.stop):
            change()
            self.assertFalse(self.engine.catalog_event_current(event))

    def test_connection_change_during_preparation_cancels_and_closes(self):
        original = self.session.post
        def post(url, **kwargs):
            result = original(url, **kwargs)
            if "getServices" in url:
                self.snapshot = NetworkSnapshot((replace(WIFI, ipv4="10.0.0.3"),))
            return result
        self.session.post = post
        self.engine.set_paused(True)
        self.engine.request_services()
        self.engine.step()
        self.assertEqual(self.catalogs(), [])
        self.context.__exit__.assert_called_once()
        self.assertEqual(len(self.session.calls), 2)
        self.assertTrue(self.engine.paused)

    def test_refresh_priority_and_no_fallback_after_portal(self):
        self.snapshot = NetworkSnapshot((WIFI, WIRED))
        self.engine.request_services()
        self.engine.step()
        self.factory.assert_called_once_with(WIRED)
        self.assertEqual(self.catalogs()[-1].connection, WIRED)
        self.assertEqual(len(self.session.calls), 2)

    def test_refresh_requested_during_prepare_cancels_old_login(self):
        original = self.session.post
        def post(url, **kwargs):
            result = original(url, **kwargs)
            if "getServices" in url:
                self.engine.request_services()
            return result
        self.session.post = post
        self.engine.step()
        self.assertEqual(len(self.session.calls), 2)
        self.assertTrue(self.engine.refresh_pending)
        self.assertEqual(self.catalogs(), [])

    def test_malformed_catalog_never_falls_back_to_other_adapter(self):
        self.snapshot = NetworkSnapshot((WIFI, WIRED))
        self.session.replies = iter([{}, services()])
        self.engine.step()
        self.factory.assert_called_once_with(WIRED)
        self.assertEqual(self.engine.blocked, "service_required")
        self.assertEqual(len(self.session.calls), 2)

    def test_network_change_invalidates_previous_catalog(self):
        self.engine.request_services()
        self.engine.step()
        event = self.catalogs()[-1]
        self.snapshot = NetworkSnapshot()
        self.engine.step()
        self.assertFalse(self.engine.catalog_event_current(event))
        self.assertIsNone(self.engine.catalog_options)


class DynamicServiceStorageTests(unittest.TestCase):
    def test_new_name_roundtrip_password_and_switches_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            settings = Settings("synthetic", "test-only", "新服务+&汉字", False, False)
            store.save(settings)
            self.assertEqual(store.load(), settings)
            self.assertNotIn("test-only", store.path.read_text(encoding="utf-8"))

    def test_invalid_service_rejected_on_save_and_load(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            for name in (None, "", " ", "a" * 201, "a\n"):
                with self.assertRaises(ValueError):
                    store.save(Settings("s", "test-only", name))
            store.save(Settings("s", "test-only"))
            data = json.loads(store.path.read_text(encoding="utf-8"))
            data["service"] = "bad\0"
            store.path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()


class ServiceGuiTests(unittest.TestCase):
    def app(self):
        app = test_notifications.NotificationGuiTests().app()
        app.refresh_button, app.service_box, app.service_hint = Mock(), Mock(), Mock()
        app.service.set.side_effect = lambda value: setattr(app.service.get, "return_value", value)
        return app

    def publish(self, app, names, *, unavailable=()):
        event = ServiceCatalogEvent(app.engine.generation, app.engine.catalog_sequence, app.engine.snapshot,
                                    options=tuple(ServiceOption(name, name not in unavailable) for name in names))
        app._show_services(event)
        return event

    def test_update_keeps_choice_not_first_and_saves_exact_new_name(self):
        app = self.app()
        self.publish(app, ("A", "新移动服务", "宜宾移动"))
        self.assertEqual(app.service.get(), "宜宾移动")
        app.service.get.return_value = "新移动服务"
        with patch("campus_login.gui.set_autostart"):
            app.save()
        self.assertEqual(app.store.save.call_args.args[0].service, "新移动服务")

    def test_unsaved_choice_survives_second_list(self):
        app = self.app()
        self.publish(app, ("宜宾移动", "新服务"))
        app.service.get.return_value = "新服务"
        self.publish(app, ("另一服务", "新服务"))
        self.assertEqual(app.service.get(), "新服务")
        self.assertEqual(app.engine.settings.service, "宜宾移动")

    def test_missing_choice_not_replaced_and_save_rejected(self):
        app = self.app()
        self.publish(app, ("移动新套餐A", "移动新套餐B"))
        self.assertEqual(app.service.get(), "宜宾移动")
        with patch("campus_login.gui.messagebox.showwarning") as warning:
            app.save()
        warning.assert_called_once()
        app.store.save.assert_not_called()

    def test_unavailable_services_not_in_selectable_values(self):
        app = self.app()
        self.publish(app, ("宜宾移动", "需额外账号"), unavailable=("需额外账号",))
        app.service_box.configure.assert_called_with(values=["宜宾移动"])

    def test_new_raw_name_equal_to_old_friendly_label_can_be_selected(self):
        app = self.app()
        self.publish(app, ("宜宾移动校园宽带",))
        self.assertEqual(app.service.get(), "宜宾移动")
        app.service.get.return_value = "宜宾移动校园宽带"
        with patch("campus_login.gui.set_autostart"):
            app.save()
        self.assertEqual(app.store.save.call_args.args[0].service, "宜宾移动校园宽带")

    def test_stale_event_does_not_replace_options_or_hint(self):
        app = self.app()
        event = self.publish(app, ("宜宾移动", "新服务"))
        app.service_box.reset_mock()
        app.service_hint.reset_mock()
        app.engine.request_services()
        app._show_services(event)
        app.service_box.configure.assert_not_called()
        app.service_hint.set.assert_not_called()

    def test_saved_settings_invalidates_unsaved_catalog_choice(self):
        app = self.app()
        self.publish(app, ("宜宾移动", "新服务"))
        app.service.get.return_value = "新服务"
        app.engine.update_settings(app.engine.settings)
        with patch("campus_login.gui.messagebox.showwarning") as warning:
            app.save()
        warning.assert_called_once()
        app.store.save.assert_not_called()

    def test_offline_preserves_original_and_can_save_other_options(self):
        app = self.app()
        with patch("campus_login.gui.set_autostart"):
            app.save()
        self.assertEqual(app.store.save.call_args.args[0].service, "宜宾移动")

    def test_failed_save_of_new_service_keeps_effective_settings(self):
        app = self.app()
        self.publish(app, ("新服务",))
        app.service.get.return_value = "新服务"
        before = app.engine.settings
        app.store.save.side_effect = OSError("synthetic")
        with patch("campus_login.gui.messagebox.showerror"), patch("campus_login.gui.set_autostart") as autostart:
            app.save()
        self.assertEqual(app.engine.settings, before)
        autostart.assert_not_called()

    def test_refresh_button_does_not_call_save_or_resume(self):
        app = self.app()
        app.engine.set_paused(True)
        app.engine.blocked = "credentials"
        app.refresh_services()
        self.assertTrue(app.engine.refresh_pending)
        self.assertTrue(app.engine.paused)
        self.assertEqual(app.engine.blocked, "credentials")
        app.store.save.assert_not_called()

    def test_new_service_notice_fixed_and_deduplicated(self):
        send = Mock()
        notifications = NotificationController(send, Mock(), generation=1)
        notifications.set_ready(True)
        for index in (1, 2):
            notifications.observe(Status("service_required", "secret raw response", notice_kind="service_required",
                                         notice_id=index, generation=1))
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], MESSAGES["service_required"])
        self.assertNotIn("secret", str(send.call_args))


class ServiceTransportTests(unittest.TestCase):
    def test_read_only_refresh_uses_real_transport_bound_to_wired_interface(self):
        replies = [test_interfaces.http(status="302 Found", location=URL)] * 2 + [
            test_interfaces.http({}), test_interfaces.http(services("新服务"))]
        sockets = [test_interfaces.FakeSocket(reply) for reply in replies]
        import socket
        import struct
        from campus_login.transport import NetworkContext
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.23.2.4", 80))]
        events = []
        with patch("campus_login.transport.socket.getaddrinfo", return_value=addresses), \
             patch("campus_login.transport.socket.socket", side_effect=sockets):
            engine = LoginEngine(lambda: NetworkSnapshot((WIRED, WIFI)), NetworkContext, events.append)
            engine.update_settings(Settings("synthetic-user", "synthetic-password"))
            engine.set_paused(True)
            engine.blocked = "credentials"
            engine.request_services()
            engine.step()
        self.assertTrue(engine.paused)
        self.assertEqual(engine.blocked, "credentials")
        self.assertEqual(events[-1].options, (ServiceOption("新服务"),))
        for sock in sockets:
            self.assertIn(("bind", (WIRED.ipv4, 0)), sock.operations)
            self.assertIn(("option", (socket.IPPROTO_IP, 31, struct.pack("!I", WIRED.interface_index))), sock.operations)
            self.assertIn(("close",), sock.operations)
            for forbidden in (b"synthetic-user", b"synthetic-password", b"method=login"):
                self.assertNotIn(forbidden, sock.sent)


if __name__ == "__main__":
    unittest.main()
