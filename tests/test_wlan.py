"""Exercise the WLAN reader using real ctypes buffers and synthetic APIs."""

import ctypes as c
import unittest
import uuid
from unittest.mock import Mock, patch

from campus_login import windows
from campus_login.models import WifiReadResult


class WlanTests(unittest.TestCase):
    def read(self, specs, *, open_error=0, enum_error=0, null_list=False, legacy=False):
        api = Mock()
        buffers = []
        self.allocated = []
        self.freed = []
        self.queried = []
        self.api = api
        table = c.create_string_buffer(8 + len(specs) * c.sizeof(windows.Interface))
        c.cast(table, c.POINTER(windows.w.DWORD))[0] = len(specs)
        buffers.append(table)
        identities = {}
        for index, spec in enumerate(specs):
            item = windows.Interface.from_address(c.addressof(table) + 8 + index * c.sizeof(windows.Interface))
            identity = uuid.UUID(int=spec.get("id", index + 1)).bytes_le
            c.memmove(c.byref(item.guid), identity, 16)
            item.state = spec.get("state", 1)
            identities[identity] = spec

        def open_handle(version, reserved, negotiated, handle):
            if not open_error:
                c.cast(handle, c.POINTER(windows.w.HANDLE))[0] = 123
            return open_error

        def enum_interfaces(handle, reserved, output):
            if not null_list:
                c.cast(output, c.POINTER(c.c_void_p))[0] = c.addressof(table)
                self.allocated.append(c.addressof(table))
            return enum_error

        def query(handle, guid, opcode, reserved, size, output, value_type):
            identity = bytes(c.cast(guid, c.POINTER(windows.GUID)).contents)
            spec = identities[identity]
            self.queried.append(spec)
            if spec.get("raise"):
                raise OSError("synthetic interface disappeared")
            if not spec.get("null"):
                info = windows.Connection()
                info.state = spec.get("connection_state", 1)
                raw = spec.get("ssid", b"SUSE_Hostel")
                info.association.ssid.length = spec.get("length", len(raw))
                for index, value in enumerate(raw[:32]):
                    info.association.ssid.value[index] = value
                buffers.append(info)
                c.cast(size, c.POINTER(windows.w.DWORD))[0] = spec.get("size", c.sizeof(info))
                c.cast(output, c.POINTER(c.c_void_p))[0] = c.addressof(info)
                self.allocated.append(c.addressof(info))
            return spec.get("error", 0)

        api.WlanOpenHandle.side_effect = open_handle
        api.WlanEnumInterfaces.side_effect = enum_interfaces
        api.WlanQueryInterface.side_effect = query
        api.WlanFreeMemory.side_effect = lambda value: self.freed.append(value.value)
        with patch.object(windows.c, "WinDLL", return_value=api):
            try:
                return windows.connected_wifi() if legacy else windows.read_wifi_snapshot()
            finally:
                self.assertCountEqual(self.freed, self.allocated)
                self.assertEqual(len(self.freed), len(set(self.freed)))
                if open_error:
                    api.WlanCloseHandle.assert_not_called()
                else:
                    api.WlanCloseHandle.assert_called_once()

    def test_interface_failure_preserves_success_in_both_orders(self):
        good = {"id": 10}
        bad = {"id": 20, "error": 5023}
        for specs in ([good, bad], [bad, good]):
            with self.subTest(specs=specs):
                result = self.read(specs)
                self.assertTrue(result.incomplete)
                self.assertEqual(len(result.connections), 1)
                self.assertEqual(result.connections[0].interface_id, uuid.UUID(int=10).bytes_le.hex())

    def test_null_short_invalid_and_disconnected_results_are_skipped(self):
        cases = [{"null": True}, {"size": 1}, {"length": 0}, {"length": 33},
                 {"length": 0xffffffff}, {"connection_state": 0}, {"ssid": b"\xff"},
                 {"raise": True}]
        for case in cases:
            with self.subTest(case=case):
                result = self.read([case, {"id": 100}])
                self.assertTrue(result.incomplete)
                self.assertEqual(len(result.connections), 1)

    def test_all_queries_fail_report_incomplete_not_disconnected(self):
        self.assertEqual(self.read([{"error": 5}, {"null": True}]), WifiReadResult((), True))

    def test_no_connections_and_disconnected_interfaces_are_not_errors(self):
        self.assertEqual(self.read([]), WifiReadResult())
        self.assertEqual(self.read([{"state": 0}]), WifiReadResult())
        self.assertFalse(self.queried)

    def test_global_failures_raise_and_release_resources(self):
        for kwargs in ({"open_error": 5}, {"enum_error": 5}, {"null_list": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(OSError):
                self.read([{}], **kwargs)

    def test_multiple_successes_and_compatibility_tuple(self):
        specs = [{"ssid": b"Home"}, {"ssid": b"SUSE"}]
        result = self.read(specs)
        self.assertFalse(result.incomplete)
        self.assertEqual([item.ssid for item in result.connections], ["Home", "SUSE"])
        self.assertEqual(self.read(specs, legacy=True), result.connections)


if __name__ == "__main__":
    unittest.main()
