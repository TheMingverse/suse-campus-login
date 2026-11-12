import unittest
from unittest.mock import Mock, MagicMock
from dataclasses import replace
from types import SimpleNamespace

from campus_login.engine import LoginEngine
from campus_login.models import Cancelled, PortalError, ProbeResult, ProbeState, Settings, NetworkConnection, NetworkSnapshot, ServiceOption, Status

WIFI = NetworkConnection("adapter", 17, "wifi", "WLAN", "10.0.0.2", "10.0.0.1", "SUSE_Hostel", "ap1")
CLASSROOM = replace(WIFI, ssid="SUSE", bssid="ap2")
WIRED = NetworkConnection("ethernet", 8, "ethernet", "USB Ethernet", "10.0.1.2", "10.0.1.1")
ONLINE = ProbeResult(ProbeState.ONLINE)
PORTAL = ProbeResult(ProbeState.PORTAL, "http://10.23.2.4/eportal/index.jsp?wlanuserip=new&wlanacname=new&mac=new")
UNKNOWN = ProbeResult(ProbeState.UNKNOWN)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.wifi = Mock(return_value=NetworkSnapshot((WIFI,)))
        self.probe = Mock()
        self.portal = Mock()
        self.portal.prepare.return_value = SimpleNamespace(services=tuple(
            ServiceOption(name) for name in ("宜宾移动", "宜宾电信", "宜宾联通", "校园网")))
        self.status = []
        self.context = MagicMock()
        self.context.__enter__.return_value = self.context
        self.context.probe, self.context.portal = self.probe, self.portal
        self.factory = Mock(return_value=self.context)
        self.engine = LoginEngine(self.wifi, self.factory, self.status.append, lambda: self.now)
        self.engine.update_settings(Settings("student", "private"))

    def step(self, result=ONLINE, seconds=15):
        self.now += seconds
        self.probe.check.return_value = result
        self.engine.step()

    def test_online_and_short_reconnect_never_login(self):
        self.step()
        self.wifi.return_value = NetworkSnapshot()
        self.step()
        self.wifi.return_value = NetworkSnapshot((WIFI,))
        self.step()
        self.portal.authenticate.assert_not_called()
        self.assertEqual(self.status[-1].code, "online")

    def test_notice_distinguishes_already_online_from_verified_login(self):
        self.step()
        first = self.status[-1]
        self.assertEqual(first.notice_kind, "available")
        self.assertEqual(first.generation, self.engine.generation)
        self.probe.check.side_effect = [PORTAL, ONLINE]
        self.step()
        success = self.status[-1]
        self.assertEqual(success.notice_kind, "connected")
        self.assertGreater(success.notice_id, first.notice_id)
        self.assertEqual(success.connection_key, first.connection_key)
        self.assertNotIn(WIFI.ipv4, repr(success))

    def test_unverified_or_cancelled_login_never_announces_success(self):
        self.probe.check.side_effect = [PORTAL, UNKNOWN]
        self.step()
        self.assertEqual(self.status[-1].code, "retry")
        self.assertFalse(any(item.notice_kind == "connected" for item in self.status if isinstance(item, Status)))
        self.engine.emit("online", "stale result", WIFI, notice_kind="connected",
                         generation=self.engine.generation - 1)
        self.assertFalse(any(item.notice_kind == "connected" for item in self.status if isinstance(item, Status)))

    def test_campus_only_notice_survives_blocked_checks_without_becoming_generic_error(self):
        self.engine.update_settings(Settings("student", "private", "校园网"))
        self.step(PORTAL)
        self.assertEqual(self.status[-1].notice_kind, "campus_only")
        self.step(PORTAL)
        self.assertEqual(self.status[-1].notice_kind, "campus_only")

    def test_fault_events_have_explicit_safe_categories_and_temporary_is_silent(self):
        for kind in ("credentials", "manual", "temporary"):
            with self.subTest(kind=kind):
                self.engine.update_settings(Settings("student", "private"))
                self.portal.authenticate.side_effect = PortalError(kind, "synthetic server message")
                self.step(PORTAL)
                self.assertEqual(self.status[-1].notice_kind, "" if kind == "temporary" else kind)
        self.engine.update_settings(Settings("student", "private"))
        self.step(ProbeResult(ProbeState.UNSUPPORTED, PORTAL.portal_url))
        self.assertEqual(self.status[-1].notice_kind, "unsupported")

    def test_unrelated_wifi_and_uncertain_detection_never_login(self):
        self.step(UNKNOWN)
        self.portal.authenticate.assert_not_called()
        self.wifi.return_value = NetworkSnapshot((replace(WIFI, ssid="Home"),))
        self.probe.reset_mock()
        self.step(PORTAL)
        self.probe.check.assert_not_called()
        self.portal.authenticate.assert_not_called()

    def test_portal_login_and_verification_then_reauthentication(self):
        self.probe.check.side_effect = [PORTAL, ONLINE, PORTAL, ONLINE]
        self.step()
        self.step()
        self.assertEqual(self.portal.authenticate.call_count, 2)
        self.assertEqual(self.status[-1].code, "online")

    def test_network_changes_before_submission_cancel_operation(self):
        def check(guard):
            self.wifi.return_value = NetworkSnapshot((CLASSROOM,))
            guard()
        self.probe.check.side_effect = check
        self.step()
        self.portal.authenticate.assert_not_called()
        self.assertEqual(self.status[-1].code, "changed")

    def test_pause_cancels_inflight_operation(self):
        def check(guard):
            self.engine.set_paused(True)
            guard()
        self.probe.check.side_effect = check
        self.step()
        self.portal.authenticate.assert_not_called()

    def test_wrong_credentials_stay_blocked_until_settings_saved(self):
        self.portal.authenticate.side_effect = PortalError("credentials", "账号或密码错误")
        self.step(PORTAL)
        self.engine.check_now()
        self.step(PORTAL)
        self.wifi.return_value = NetworkSnapshot((CLASSROOM,))
        self.step(PORTAL)
        self.assertEqual(self.portal.authenticate.call_count, 1)
        self.engine.update_settings(Settings("student", "new"))
        self.step(PORTAL)
        self.assertEqual(self.portal.authenticate.call_count, 2)

    def test_retry_delays_and_five_minute_backoff(self):
        self.portal.authenticate.side_effect = PortalError("temporary", "暂时不可用")
        for delay in (5, 15, 30, 300):
            self.step(PORTAL, seconds=0)
            self.assertEqual(self.engine.next_check, self.now + delay)
            self.now += delay
        self.assertEqual(self.portal.authenticate.call_count, 4)

    def test_unknown_network_during_retry_does_not_login(self):
        self.portal.authenticate.side_effect = PortalError("temporary", "暂时不可用")
        self.step(PORTAL)
        self.step(UNKNOWN, seconds=5)
        self.assertEqual(self.portal.authenticate.call_count, 1)

    def test_captcha_stops_and_online_can_still_be_detected(self):
        self.portal.authenticate.side_effect = PortalError("manual", "需要验证码")
        self.step(PORTAL)
        self.step(PORTAL)
        self.assertEqual(self.portal.authenticate.call_count, 1)
        self.step(ONLINE)
        self.assertEqual(self.status[-1].code, "online")

    def test_wired_only_authenticates_and_checks_same_context(self):
        self.wifi.return_value = NetworkSnapshot((WIRED,))
        self.probe.check.side_effect = [PORTAL, ONLINE]
        self.step()
        self.factory.assert_called_once_with(WIRED)
        self.portal.authenticate.assert_called_once()
        self.assertEqual(self.probe.check.call_count, 2)
        self.assertEqual(self.status[-1].connection_label, WIRED.label)
        self.context.__exit__.assert_called_once()

    def test_wired_online_short_reconnect_skips_login(self):
        for connections in [(WIRED,), (), (WIRED,)]:
            self.wifi.return_value = NetworkSnapshot(connections)
            self.step()
        self.portal.authenticate.assert_not_called()

    def test_wired_priority_when_wifi_also_connected(self):
        self.wifi.return_value = NetworkSnapshot((WIFI, WIRED))
        self.step()
        self.factory.assert_called_once_with(WIRED)
        self.portal.authenticate.assert_not_called()

    def test_wired_portal_does_not_use_online_wifi_to_verify(self):
        self.wifi.return_value = NetworkSnapshot((WIFI, WIRED))
        self.probe.check.side_effect = [PORTAL, UNKNOWN]
        self.step()
        self.factory.assert_called_once_with(WIRED)
        self.assertEqual(self.status[-1].code, "retry")

    def test_uncertain_wired_falls_back_to_wifi_with_new_context(self):
        self.wifi.return_value = NetworkSnapshot((WIFI, WIRED))
        self.probe.check.side_effect = [UNKNOWN, ONLINE]
        self.step()
        self.assertEqual([call.args[0] for call in self.factory.call_args_list], [WIRED, WIFI])
        self.assertEqual(self.context.__exit__.call_count, 2)

    def test_address_wait_never_creates_session_or_authenticates(self):
        self.wifi.return_value = NetworkSnapshot((replace(WIRED, ipv4="", gateway=""),))
        self.step(PORTAL)
        self.factory.assert_not_called()
        self.assertEqual(self.status[-1].code, "address_wait")
        self.wifi.return_value = NetworkSnapshot((replace(WIRED, ipv4="169.254.1.2"), WIFI))
        self.step()
        self.factory.assert_called_once_with(WIFI)

    def test_unplug_address_change_and_settings_change_cancel_close(self):
        for change in (lambda: setattr(self.wifi, "return_value", NetworkSnapshot((WIFI,))),
                       lambda: setattr(self.wifi, "return_value", NetworkSnapshot((replace(WIRED, ipv4="10.0.1.3"),))),
                       lambda: self.engine.update_settings(Settings("new", "new"))):
            with self.subTest(change=change):
                self.wifi.return_value = NetworkSnapshot((WIRED, WIFI))
                self.factory.reset_mock()
                self.context.__exit__.reset_mock()

                def check(guard):
                    change()
                    guard()

                self.probe.check.side_effect = check
                self.step()
                self.portal.authenticate.assert_not_called()
                self.context.__exit__.assert_called_once()
                self.assertEqual(self.status[-1].code, "changed")

    def test_unplug_then_wifi_is_checked_on_next_step(self):
        self.wifi.return_value = NetworkSnapshot((WIRED, WIFI))
        self.step()
        self.wifi.return_value = NetworkSnapshot((WIFI,))
        self.step(seconds=0)
        self.assertEqual(self.factory.call_args.args[0], WIFI)

    def test_unknown_wired_parameters_block_without_falling_back(self):
        self.wifi.return_value = NetworkSnapshot((WIRED, WIFI))
        unsupported = ProbeResult(ProbeState.UNSUPPORTED, "http://10.23.2.4/eportal/index.jsp?userip=secret&nas=hidden")
        self.step(unsupported)
        self.factory.assert_called_once_with(WIRED)
        self.portal.authenticate.assert_not_called()
        self.assertIn("有线认证参数需要适配", self.status[-1].text)
        self.assertNotIn("secret", self.status[-1].text)
        self.assertNotIn("hidden", self.status[-1].text)

    def test_error_or_manual_state_never_hops_connections(self):
        for kind in ("credentials", "manual", "temporary"):
            with self.subTest(kind=kind):
                self.engine.update_settings(Settings("student", "private"))
                self.wifi.return_value = NetworkSnapshot((WIRED, WIFI))
                self.factory.reset_mock()
                self.portal.authenticate.side_effect = PortalError(kind, "test error")
                self.step(PORTAL)
                self.factory.assert_called_once_with(WIRED)

    def test_wired_still_works_when_wifi_permission_unavailable(self):
        self.wifi.return_value = NetworkSnapshot((WIRED,), wifi_unavailable=True)
        self.step()
        self.assertEqual(self.status[-1].code, "online")

    def test_campus_only_service_accepted_without_external_access_not_retried(self):
        self.engine.update_settings(Settings("student", "private", "校园网"))
        self.step(PORTAL)
        self.step(PORTAL)
        self.assertEqual(self.portal.authenticate.call_count, 1)
        self.assertEqual(self.status[-1].code, "manual")

    def test_readable_wifi_authenticates_despite_partial_failure(self):
        self.wifi.return_value = NetworkSnapshot((WIFI,), wifi_unavailable=True)
        self.probe.check.side_effect = [PORTAL, ONLINE]
        self.step()
        self.factory.assert_called_once_with(WIFI)
        self.portal.authenticate.assert_called_once()
        self.assertEqual(self.status[-1].code, "online")

    def test_two_campus_wifi_have_independent_ordered_contexts(self):
        other = replace(CLASSROOM, interface_id="other", interface_index=7, ipv4="10.2.0.2")
        contexts = []
        def make_context(connection):
            context = MagicMock()
            context.__enter__.return_value = context
            context.probe.check.return_value = UNKNOWN if connection == other else ONLINE
            contexts.append(context)
            return context
        self.wifi.return_value = NetworkSnapshot((WIFI, other))
        self.factory.side_effect = make_context
        self.step()
        self.assertEqual([call.args[0] for call in self.factory.call_args_list], [other, WIFI])
        for context in contexts:
            context.__exit__.assert_called_once()
            context.portal.authenticate.assert_not_called()
        self.assertEqual(self.status[-1].connection_label, WIFI.label)

    def test_first_online_wifi_ends_cycle_and_home_wifi_is_ignored(self):
        other = replace(CLASSROOM, interface_id="other", interface_index=20)
        home = replace(WIFI, interface_id="home", interface_index=1, ssid="Home")
        self.wifi.return_value = NetworkSnapshot((other, home, WIFI))
        self.step()
        self.factory.assert_called_once_with(WIFI)

    def test_wifi_failures_do_not_mislabel_readable_unrelated_wifi(self):
        self.wifi.return_value = NetworkSnapshot((), wifi_unavailable=True)
        self.step()
        self.assertEqual(self.status[-1].code, "wifi_error")
        self.wifi.return_value = NetworkSnapshot((replace(WIFI, ssid="Home"),), wifi_unavailable=True)
        self.step()
        self.assertEqual(self.status[-1].code, "outside")
        self.assertIn("部分无线接口", self.status[-1].text)
        self.factory.assert_not_called()

    def test_wifi_changes_cancel_close_and_authentication_errors_do_not_hop(self):
        other = replace(CLASSROOM, interface_id="other", interface_index=20)
        snapshot = NetworkSnapshot((WIFI, other))
        for changed in (NetworkSnapshot((other,)),
                        NetworkSnapshot((replace(WIFI, ipv4="10.0.0.3"), other))):
            with self.subTest(changed=changed):
                self.wifi.return_value = snapshot
                self.context.__exit__.reset_mock()
                def check(guard):
                    self.wifi.return_value = changed
                    guard()
                self.probe.check.side_effect = check
                self.step()
                self.portal.authenticate.assert_not_called()
                self.context.__exit__.assert_called_once()
                self.assertEqual(self.status[-1].code, "changed")
        self.probe.check.side_effect = None
        self.wifi.return_value = snapshot
        for kind in ("credentials", "manual", "temporary"):
            with self.subTest(kind=kind):
                self.engine.update_settings(Settings("student", "private"))
                self.factory.reset_mock()
                self.portal.authenticate.side_effect = PortalError(kind, "test error")
                self.step(PORTAL)
                self.factory.assert_called_once_with(WIFI)


if __name__ == "__main__":
    unittest.main()

