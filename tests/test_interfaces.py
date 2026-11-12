import ctypes as c
import io
import json
import socket
import struct
import unittest
import uuid
from dataclasses import replace
from unittest.mock import Mock, patch

import requests

from campus_login import adapters
from campus_login.diagnostics import connection_report
from campus_login.engine import LoginEngine
from campus_login.models import (Cancelled, NetworkConnection, NetworkSnapshot,
                                 ProbeResult, ProbeState, Settings, WifiConnection, WifiReadResult)
from campus_login.network import NetworkProbe
from campus_login.portal import PortalClient
from campus_login.transport import NetworkContext, interface_session, connect_ipv4

WIRED = NetworkConnection("ethernet", 8, "ethernet", "USB Ethernet", "10.0.1.2", "10.0.1.1")
WIFI = NetworkConnection("wifi", 17, "wifi", "WLAN", "10.0.0.2", "10.0.0.1", "SUSE_Hostel")
PORTAL = "http://10.23.2.4/eportal/index.jsp?wlanuserip=fresh&wlanacname=ac&mac=example"


def http(body=b"", status="200 OK", location=None):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    header = f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n"
    if location:
        header += "Location: " + location + "\r\n"
    return header.encode() + b"\r\n" + body


class FakeSocket:
    """Keep requests + urllib3 real, replace only the operating-system socket."""
    def __init__(self, response):
        self.response = response
        self.operations = []
        self.sent = bytearray()

    def settimeout(self, timeout):
        pass

    def setsockopt(self, *args):
        self.operations.append(("option", args))

    def bind(self, address):
        self.operations.append(("bind", address))

    def connect(self, address):
        self.operations.append(("connect", address))

    def makefile(self, *args):
        return io.BytesIO(self.response)

    def sendall(self, content):
        self.sent.extend(content)

    def close(self):
        self.operations.append(("close",))


class TransportTests(unittest.TestCase):
    def test_two_campus_wifi_requests_stay_on_their_own_interfaces(self):
        first = NetworkConnection("wifi-first", 7, "wifi", "WLAN2", "10.2.0.2", "10.2.0.1", "SUSE")
        sockets = [FakeSocket(http(b"unknown")), FakeSocket(http(b"unknown")),
                   FakeSocket(http(b"Microsoft Connect Test"))]
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 80))]
        status = []
        with patch("campus_login.transport.socket.getaddrinfo", return_value=addresses), \
             patch("campus_login.transport.socket.socket", side_effect=sockets):
            engine = LoginEngine(lambda: NetworkSnapshot((WIFI, first)), NetworkContext, status.append)
            engine.step()
        self.assertEqual(status[-1].code, "online")
        for sock, connection in zip(sockets, (first, first, WIFI)):
            self.assertIn(("bind", (connection.ipv4, 0)), sock.operations)
            self.assertIn(("option", (socket.IPPROTO_IP, 31, struct.pack("!I", connection.interface_index))), sock.operations)
            self.assertIn(("close",), sock.operations)
            self.assertNotIn(b"POST", sock.sent)

    def test_full_authentication_all_requests_bound_to_selected_interface(self):
        replies = [http(status="302 Found", location=PORTAL)] * 2 + [
            http({"passwordEncrypt": "false"}),
            http({"serviceJson": [{"serviceName": "宜宾移动"}]}),
            http({"result": "success"}), http(b"Microsoft Connect Test")]
        sockets = [FakeSocket(reply) for reply in replies]
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.23.2.4", 80))]
        status = []
        with patch("campus_login.transport.socket.getaddrinfo", return_value=addresses), \
             patch("campus_login.transport.socket.socket", side_effect=sockets):
            engine = LoginEngine(lambda: NetworkSnapshot((WIFI, WIRED)), NetworkContext, status.append)
            engine.update_settings(Settings("example-student", "test-only"))
            engine.step()
        self.assertEqual(status[-1].code, "online")
        self.assertEqual(status[-1].connection_label, WIRED.label)
        for sock in sockets:
            self.assertIn(("bind", (WIRED.ipv4, 0)), sock.operations)
            self.assertIn(("option", (socket.IPPROTO_IP, 31, struct.pack("!I", WIRED.interface_index))), sock.operations)
            self.assertLess(sock.operations.index(("bind", (WIRED.ipv4, 0))),
                            sock.operations.index(("connect", ("10.23.2.4", 80))))
            self.assertIn(("close",), sock.operations)
        self.assertIn(b"method=pageInfo", sockets[2].sent)
        self.assertIn(b"method=getServices", sockets[3].sent)
        self.assertIn(b"method=login", sockets[4].sent)
        for number in (0, 1, 2, 3, 5):
            self.assertNotIn(b"example-student", sockets[number].sent)
            self.assertNotIn(b"test-only", sockets[number].sent)

    def test_distinct_sessions_have_distinct_pools_and_no_cookie_leak(self):
        with NetworkContext(WIRED) as wired, NetworkContext(WIFI) as wifi:
            self.assertIs(wired.probe.session, wired.portal.session)
            self.assertIs(wifi.probe.session, wifi.portal.session)
            self.assertIsNot(wired.session, wifi.session)
            wired.session.cookies.set("example", "wired")
            self.assertNotIn("example", wifi.session.cookies)
            for context, connection in [(wired, WIRED), (wifi, WIFI)]:
                self.assertFalse(context.session.trust_env)
                manager = context.session.adapters["http://"].poolmanager
                self.assertEqual(manager.connection_pool_kw["source_address"], (connection.ipv4, 0))
                with self.assertRaises(requests.exceptions.InvalidSchema):
                    context.session.get("https://10.23.2.4/eportal/index.jsp")
        with NetworkContext(WIRED) as fresh:
            self.assertNotIn("example", fresh.session.cookies)

    def test_binding_failure_closes_socket_and_never_falls_back_to_default(self):
        sock = Mock()
        sock.bind.side_effect = OSError("adapter removed")
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.23.2.4", 80))]
        with patch("campus_login.transport.socket.getaddrinfo", return_value=addresses), \
             patch("campus_login.transport.socket.socket", return_value=sock):
            with self.assertRaises(OSError):
                connect_ipv4("10.23.2.4", 80, 1, (WIRED.ipv4, 0), [])
        sock.close.assert_called_once()
        sock.connect.assert_not_called()

    def test_unknown_parameters_never_reach_config_or_login(self):
        unknown = "http://10.23.2.4/eportal/index.jsp?userip=secret-ip&nas=secret-mac"
        sockets = [FakeSocket(http(status="302 Found", location=unknown)) for _ in range(2)]
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.23.2.4", 80))]
        status = []
        with patch("campus_login.transport.socket.getaddrinfo", return_value=addresses), \
             patch("campus_login.transport.socket.socket", side_effect=sockets):
            engine = LoginEngine(lambda: NetworkSnapshot((WIRED,)), NetworkContext, status.append)
            engine.update_settings(Settings("example-student", "test-only"))
            engine.step()
        self.assertEqual(status[-1].code, "unsupported")
        for sock in sockets:
            self.assertNotIn(b"POST", sock.sent)
            self.assertNotIn(b"example-student", sock.sent)
        self.assertNotIn("secret-ip", status[-1].text)

    def test_unready_connection_cannot_create_unbound_session(self):
        with self.assertRaises(ValueError):
            interface_session(replace(WIRED, ipv4=""))


class AdapterTests(unittest.TestCase):
    def fake_snapshot(self, specs, wireless=(), wifi_error=False, wifi_partial=False):
        """Exercise native-buffer parsing with synthetic Windows API outputs."""
        objects, nodes = [], []

        def address(value):
            buffer = c.create_string_buffer(struct.pack("H", socket.AF_INET) + b"\0\0" +
                                            socket.inet_aton(value) + b"\0" * 8)
            node = adapters.AddressNode()
            node.socket.address, node.socket.length = c.addressof(buffer), 16
            nodes.extend([buffer, node])
            return c.pointer(node)

        for index, kind, ip, gateway, up, hardware, identity in specs:
            item = adapters.Adapter()
            item.length, item.index = c.sizeof(adapters.Adapter), index
            item.adapter_name = identity.encode()
            item.friendly_name = "USB Ethernet" if kind == 6 else "WLAN"
            item.if_type, item.oper_status = kind, up
            if ip:
                item.unicast = address(ip)
            if gateway:
                item.gateway = address(gateway)
            objects.append(item)
        for previous, following in zip(objects, objects[1:]):
            previous.next = c.pointer(following)

        def get_adapters(family, flags, reserved, output, size):
            c.memmove(output, c.byref(objects[0]), c.sizeof(objects[0]))
            return 0

        def get_entry(output):
            row = c.cast(output, c.POINTER(adapters.InterfaceRowPrefix)).contents
            spec = next(item for item in specs if item[0] == row.index)
            row.if_type, row.status_flags = spec[1], int(spec[5])
            return 0

        api = Mock()
        api.GetAdaptersAddresses.side_effect = get_adapters
        api.GetIfEntry2.side_effect = get_entry
        with patch.object(adapters.c, "WinDLL", return_value=api), \
             patch.object(adapters, "read_wifi_snapshot", side_effect=OSError("permission") if wifi_error else None,
                          return_value=WifiReadResult(tuple(wireless), wifi_partial)):
            return adapters.network_snapshot()

    def test_native_and_usb_ethernet_recognized_virtual_vpn_excluded(self):
        result = self.fake_snapshot([
            (5, 6, "10.1.0.2", "10.1.0.1", 1, True, "native"),
            (8, 6, "10.2.0.2", "10.2.0.1", 1, True, "usb"),
            (9, 6, "10.3.0.2", "10.3.0.1", 1, False, "vpn"),
            (10, 6, "", "", 2, True, "unplugged")])
        self.assertEqual([item.interface_id for item in result.candidates], ["native", "usb"])

    def test_guid_matching_and_wifi_permission_failure_preserves_wired(self):
        identity = uuid.UUID("12345678-1234-5678-1234-567812345678")
        specs = [(17, 71, "10.0.0.2", "10.0.0.1", 1, True, "{" + str(identity) + "}"),
                 (8, 6, "10.1.0.2", "10.1.0.1", 1, True, "wired")]
        result = self.fake_snapshot(specs, [WifiConnection(identity.bytes_le.hex(), "SUSE_Hostel", "ap")])
        self.assertEqual([item.kind for item in result.candidates], ["ethernet", "wifi"])
        result = self.fake_snapshot(specs, wifi_error=True)
        self.assertTrue(result.wifi_unavailable)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].kind, "ethernet")

    def test_no_dhcp_address_or_gateway_retained_but_not_ready(self):
        for ip, gateway in [("", ""), ("169.254.1.2", ""), ("10.1.0.2", "")]:
            result = self.fake_snapshot([(8, 6, ip, gateway, 1, True, "wired")])
            self.assertEqual(len(result.connections), 1)
            self.assertFalse(result.connections[0].ready)
            self.assertFalse(result.candidates)

    def test_multiple_wifi_filtered_and_partial_failure_keeps_readable_interface(self):
        identities = [uuid.UUID(int=i) for i in (1, 2, 3)]
        specs = [(i + 10, 71, f"10.0.{i}.2", f"10.0.{i}.1", 1, True,
                  "{" + str(identity) + "}") for i, identity in enumerate(identities)]
        wireless = [WifiConnection(identities[0].bytes_le.hex(), "SUSE_Hostel", "ap1"),
                    WifiConnection(identities[1].bytes_le.hex(), "Home", "ap2")]
        for order in (wireless, wireless[::-1]):
            result = self.fake_snapshot(specs, order, wifi_partial=True)
            self.assertTrue(result.wifi_unavailable)
            self.assertEqual(len(result.connections), 2)
            self.assertEqual([item.ssid for item in result.candidates], ["SUSE_Hostel"])

    def test_partial_failure_without_readable_wifi_keeps_ethernet(self):
        identity = uuid.UUID(int=1)
        result = self.fake_snapshot([
            (17, 71, "10.0.0.2", "10.0.0.1", 1, True, "{" + str(identity) + "}"),
            (8, 6, "10.1.0.2", "10.1.0.1", 1, True, "wired")], wifi_partial=True)
        self.assertTrue(result.wifi_unavailable)
        self.assertEqual(result.candidates[0].kind, "ethernet")


class DiagnosticTests(unittest.TestCase):
    def test_partial_and_total_wifi_failure_messages(self):
        for connections, expected in [((WIFI,), "部分无线接口暂时无法读取，其他正常连接仍可使用"),
                                      ((), "无线连接信息均无法读取"),
                                      ((WIRED,), "无线连接信息均无法读取")]:
            context = Mock()
            context.__enter__ = Mock(return_value=context)
            context.__exit__ = Mock(return_value=False)
            context.probe.check.return_value = ProbeResult(ProbeState.ONLINE)
            snapshot = NetworkSnapshot(connections, wifi_unavailable=True)
            report = connection_report(lambda: snapshot, Mock(return_value=context))
            self.assertIn(expected, report)
            if connections == (WIFI,):
                self.assertNotIn("检查网卡或 Windows", report)
            context.portal.authenticate.assert_not_called()

    def test_reports_parameter_names_only_and_never_reads_password(self):
        context = Mock()
        context.__enter__ = Mock(return_value=context)
        context.__exit__ = Mock(return_value=False)
        context.probe.check.return_value = ProbeResult(ProbeState.UNSUPPORTED,
            "http://10.23.2.4/eportal/index.jsp?userip=secret-ip&mac=secret-mac")
        report = connection_report(lambda: NetworkSnapshot((WIRED,)), Mock(return_value=context))
        self.assertIn("userip", report)
        self.assertIn("10.23.2.4", report)
        self.assertNotIn("secret", report)
        self.assertNotIn(WIRED.ipv4, report)
        self.assertNotIn(WIRED.gateway, report)
        context.portal.authenticate.assert_not_called()

    def test_changed_network_stops_diagnosis(self):
        context = Mock()
        read = Mock(side_effect=[NetworkSnapshot((WIRED,)), NetworkSnapshot()])
        factory = Mock(return_value=context)
        report = connection_report(read, factory)
        factory.assert_not_called()
        self.assertIn("连接已变化", report)


if __name__ == "__main__":
    unittest.main()
