import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

import requests

from campus_login.models import ProbeState, Settings
from campus_login.network import NetworkProbe, portal_from_response
from campus_login.storage import SettingsStore
from campus_login.windows import protect, current_wifi

PORTAL = "http://10.23.2.4/eportal/index.jsp?wlanuserip=new&wlanacname=new&mac=new"


def response(body=b"", status=200, headers=None):
    r = requests.Response()
    r.status_code = status
    r.url = "http://www.msftconnecttest.com/connecttest.txt"
    r.headers.update(headers or {})
    r._content = body
    r._content_consumed = True
    r.raw = Mock()
    return r


class NetworkTests(unittest.TestCase):
    def test_legitimate_redirects_and_html_entity_decode(self):
        for r in [response(status=302, headers={"Location": PORTAL}),
                  response(("<script>location.href='" + PORTAL.replace("&", "&amp;") + "'</script>").encode()),
                  response(("<meta http-equiv='refresh' content='0;url=" + PORTAL + "'>").encode())]:
            self.assertEqual(portal_from_response(r), PORTAL)

    def test_random_links_and_rogue_portals_not_authentication_evidence(self):
        self.assertIsNone(portal_from_response(response(("<a href='" + PORTAL + "'>link</a>").encode())))
        self.assertIsNone(portal_from_response(response(status=302, headers={"Location": PORTAL.replace("10.23.2.4", "evil.example")})))
        self.assertIsNone(portal_from_response(response(status=302, headers={"Location": "http://10.23.2.4/eportal/index.jsp"})))

    def test_second_detector_success_overrides_first_detector_failure_or_redirect(self):
        for first in [requests.Timeout(), response(status=302, headers={"Location": PORTAL})]:
            session = Mock()
            session.get.side_effect = [first, response(b"success\n")]
            self.assertEqual(NetworkProbe(session).check().state, ProbeState.ONLINE)

    def test_timeout_and_other_content_are_unknown_not_login(self):
        session = Mock()
        session.get.side_effect = [requests.Timeout(), response(b"unavailable")]
        self.assertEqual(NetworkProbe(session).check().state, ProbeState.UNKNOWN)


@unittest.skipUnless(sys.platform == "win32", "Windows APIs")
class StorageTests(unittest.TestCase):
    def test_notification_default_old_files_and_disabled_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            self.assertTrue(store.load().notifications_enabled)
            settings = Settings("example", "test-only", "宜宾移动", False, False)
            store.save(settings)
            self.assertEqual(SettingsStore(Path(temp)).load(), settings)
            data = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertIs(data.pop("notifications_enabled"), False)
            store.path.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(store.load().notifications_enabled)
            self.assertEqual(store.load().password, settings.password)

    def test_invalid_notification_setting_rejected_instead_of_enabling(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            store.save(Settings("example", "test-only"))
            data = json.loads(store.path.read_text(encoding="utf-8"))
            data["notifications_enabled"] = "false"
            store.path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()

    def test_dpapi_roundtrip_and_settings_not_plaintext(self):
        password = "test-only+&汉字🙂"
        encrypted = protect(password.encode())
        self.assertNotIn(password.encode(), encrypted)
        self.assertEqual(protect(encrypted, decrypt=True).decode(), password)
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            settings = Settings("example", password, "宜宾联通", False)
            store.save(settings)
            self.assertEqual(store.load(), settings)
            text = store.path.read_text(encoding="utf-8")
            self.assertNotIn(password, text)
            self.assertIn("protected_password", json.loads(text))

    def test_corrupted_ciphertext_does_not_silently_load(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            store.path.write_text('{"protected_password":"AA==","username":"example"}')
            with self.assertRaises(OSError):
                store.load()


if __name__ == "__main__":
    unittest.main()
