import json
from pathlib import Path
import unittest
from urllib.parse import unquote

import requests

from campus_login.models import PortalError, Settings
from campus_login.portal import (PortalClient, classify_login, component, connection_query,
                                 form, login_fields, rsa_password, trusted_portal)

QUERY = "wlanuserip=fresh-user&wlanacname=fresh-ac&mac=ab%3Acd&ssid=fresh-ssid"
URL = "http://10.23.2.4/eportal/index.jsp?" + QUERY
MODULUS = "b" + "d" * 255


class Response:
    is_redirect = False

    def __init__(self, data):
        self.content = json.dumps(data).encode()

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(next(self.replies))


class PortalTests(unittest.TestCase):
    def test_school_javascript_compatibility_regression_vectors(self):
        fixture = json.loads(Path(__file__).with_name("rsa_vectors.json").read_text(encoding="utf-8"))
        for vector in fixture["vectors"]:
            with self.subTest(length=len(vector["password"])):
                self.assertEqual(rsa_password(vector["password"], fixture["mac"], fixture["exponent"], fixture["modulus"]), vector["expected"])

    def test_double_encoding_preserves_query_and_chinese(self):
        values = {"userId": "student+&%", "password": "a+b&c=汉字!", "queryString": QUERY, "service": "宜宾移动"}
        wire = form(values, double=True).decode()
        for part in wire.split("&"):
            key, value = part.split("=", 1)
            self.assertEqual(unquote(unquote(value)), values[key])
        self.assertEqual(component("!~*'() "), "!~*'()%20")

    def test_host_and_query_validation_prevents_credentials_to_other_host(self):
        for url in ["http://10.23.2.4.evil/eportal/index.jsp?" + QUERY,
                    "http://10.23.2.4@evil/eportal/index.jsp?" + QUERY,
                    "https://10.23.2.4/eportal/index.jsp?" + QUERY,
                    "http://10.23.2.4:9999/eportal/index.jsp?" + QUERY,
                    "http://10.23.2.4/eportal/other.jsp?" + QUERY]:
            self.assertFalse(trusted_portal(url))
            with self.assertRaises(PortalError):
                connection_query(url)
        with self.assertRaises(PortalError):
            connection_query("http://10.23.2.4/eportal/index.jsp")
        self.assertEqual(connection_query(URL), QUERY)

    def test_encrypt_even_long_passwords_not_saved_ciphertext_heuristic(self):
        settings = Settings("student", "a" * 180 + "&汉字🙂", "宜宾移动")
        fields = login_fields(settings, QUERY, {"passwordEncrypt": "true", "publicKeyExponent": "10001", "publicKeyModulus": MODULUS})
        self.assertNotIn("a" * 100, fields["password"])
        self.assertIn(" ", fields["password"])
        self.assertEqual(fields["passwordEncrypt"], "true")
        self.assertEqual(fields["password"], rsa_password(settings.password, "ab%3Acd", "10001", MODULUS))

    def test_captcha_and_invalid_encryption_stop_before_login(self):
        for info in [{"validCodeUrl": "/captcha"}, {"isCheckSmsAuth": "true"},
                     {"passwordEncrypt": "true", "publicKeyModulus": "bad"}]:
            with self.assertRaises(PortalError) as error:
                login_fields(Settings("s", "secret"), QUERY, info)
            self.assertEqual(error.exception.kind, "manual")

    def test_authentication_reads_settings_before_login_and_does_not_follow_redirects(self):
        session = Session([
            {"passwordEncrypt": "true", "publicKeyExponent": "10001", "publicKeyModulus": MODULUS},
            {"serviceJson": json.dumps([{"serviceName": "宜宾移动", "domainName": "false"}])},
            {"result": "success"},
        ])
        PortalClient(session).authenticate(URL, Settings("s", "private"))
        self.assertEqual(len(session.calls), 3)
        self.assertTrue(session.calls[-1][0].endswith("method=login"))
        self.assertTrue(all(not kwargs["allow_redirects"] for _, kwargs in session.calls))
        wire = session.calls[-1][1]["data"].decode()
        self.assertNotIn("private", wire)
        self.assertIn(component(component("宜宾移动")), wire)

    def test_unknown_service_never_submits_credentials(self):
        session = Session([{}, {"serviceJson": "[]"}])
        with self.assertRaises(PortalError):
            PortalClient(session).authenticate(URL, Settings("s", "secret"))
        self.assertEqual(len(session.calls), 2)

    def test_login_error_classification_and_redaction(self):
        for message, kind in [("用户student密码错误", "credentials"), ("验证码错误", "manual"),
                              ("服务器繁忙", "temporary"), ("终端数量上限", "manual"),
                              ("unknown student secret", "manual")]:
            with self.assertRaises(PortalError) as error:
                classify_login({"result": "fail", "message": message})
            self.assertEqual(error.exception.kind, kind)
            self.assertNotIn("student", str(error.exception))
            self.assertNotIn("secret", str(error.exception))

    def test_success_password_strength_warning_is_not_ignored(self):
        with self.assertRaises(PortalError):
            classify_login({"result": "success", "message": "false::PWD_COMPLEX_OFFLINE_WEB::5"})


if __name__ == "__main__":
    unittest.main()

