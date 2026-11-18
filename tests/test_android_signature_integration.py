"""Real SDK verifier tests against pinned public pre-signed AOSP APKs; no keys.

Opt in with SUSE_ANDROID_SIGNATURE_INTEGRATION=1 after running
tools/android_signature_fixtures.py. Tests never fetch media or keys themselves.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import android_artifacts as a
import android_release as release

REAL_RUN_TOOL = a.run_tool
GOLDEN = "golden-aligned-v1v2v3-out.apk"
V2_ONLY = "v2-only-with-rsa-pkcs1-sha256-2048.apk"
V3_ONLY = "v3-only-with-rsa-pkcs1-sha256-2048.apk"
CORRUPT = "v3-only-with-rsa-pkcs1-sha256-3072-sig-does-not-verify.apk"


@unittest.skipUnless(os.environ.get("SUSE_ANDROID_SIGNATURE_INTEGRATION") == "1",
                     "Opt in to real SDK tests with SUSE_ANDROID_SIGNATURE_INTEGRATION=1")
class RealApksignerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "tests/android_signature_fixtures.json").read_text(encoding="utf-8"))
        cls.pin = cls.manifest["certificateSha256"]
        cls.cache = ROOT / ".cache/android-signature-fixtures"
        for name, digest in cls.manifest["files"].items():
            path = cls.cache / name
            if not path.is_file() or a.sha256(path) != digest:
                raise RuntimeError("Run tools/android_signature_fixtures.py to prepare pinned public APK fixtures")
        cls.tools = a.signature_tool_details()
        cls.evidence = []
        cls.identity_before = (ROOT / "android/release-identity.json").read_bytes()
        cls.version_before = (ROOT / "android/version.properties").read_bytes()

    @classmethod
    def tearDownClass(cls):
        a.require((ROOT / "android/release-identity.json").read_bytes() == cls.identity_before,
                  "Integration tests changed official signing identity")
        a.require((ROOT / "android/version.properties").read_bytes() == cls.version_before,
                  "Integration tests changed app version")
        a.write_json(ROOT / "build/android-signature-tests/integration-results.json", {
            "tools": cls.tools, "fixtureSourceCommit": cls.manifest["commit"], "cases": cls.evidence,
            "officialPrivateKeyAccessed": False, "newKeysGenerated": False,
            "officialIdentityUnchanged": True, "appVersionUnchanged": True})

    @staticmethod
    def api29_default(name, args, **kwargs):
        # Old AOSP fixtures declare older minSdk versions. Only adapt the test command
        # to simulate the campus app's actual API 29 minimum; SDK outputs stay real.
        if name == "apksigner" and args[0] == "verify" and "--min-sdk-version" not in args:
            args = [*args[:-1], "--min-sdk-version", "29", args[-1]]
        return REAL_RUN_TOOL(name, args, **kwargs)

    def verify(self, fixture, expected=None, api29=False):
        checks = []
        entry = {"test": self._testMethodName, "fixture": fixture,
                 "defaultRangeSimulatesCampusApi29": api29, "checks": checks}
        self.evidence.append(entry)
        try:
            if api29:
                with patch.object(a, "run_tool", side_effect=self.api29_default):
                    return a.verify_release_signatures(self.cache / fixture, expected or self.pin, checks=checks)
            return a.verify_release_signatures(self.cache / fixture, expected or self.pin, checks=checks)
        finally:
            self.assertEqual(len(checks), 3)

    def test_real_valid_v2_v3_pass_all_three_checks(self):
        self.assertEqual(self.verify(GOLDEN), self.pin)
        self.assertTrue(all(c["passed"] for c in self.evidence[-1]["checks"]))

    def test_real_api29_regression_skips_v2_by_default_but_verifies_it_separately(self):
        self.assertEqual(self.verify(GOLDEN, api29=True), self.pin)
        checks = self.evidence[-1]["checks"]
        self.assertFalse(checks[0]["schemes"]["v2"])
        self.assertTrue(checks[0]["schemes"]["v3"])
        self.assertTrue(checks[1]["schemes"]["v2"])
        self.assertTrue(checks[2]["schemes"]["v3"])

    def test_real_v2_only_is_rejected_despite_all_exit_codes_being_zero(self):
        with self.assertRaisesRegex(a.VerificationError, "v3"):
            self.verify(V2_ONLY, api29=True)
        checks = self.evidence[-1]["checks"]
        self.assertTrue(all(c["exitCode"] == 0 for c in checks))
        self.assertFalse(checks[2]["schemes"]["v3"])

    def test_real_v3_only_is_rejected_by_v2_check(self):
        with self.assertRaisesRegex(a.VerificationError, "v2"):
            self.verify(V3_ONLY, api29=True)
        self.assertNotEqual(self.evidence[-1]["checks"][1]["exitCode"], 0)

    def test_real_corrupt_signature_is_rejected(self):
        with self.assertRaises(a.VerificationError):
            self.verify(CORRUPT, api29=True)
        self.assertFalse(any(c["passed"] for c in self.evidence[-1]["checks"]))

    def test_real_certificate_mismatch_rejected_in_every_pass(self):
        with self.assertRaisesRegex(a.VerificationError, "identity mismatch"):
            self.verify(GOLDEN, expected="00" * 32)
        self.assertTrue(all(c["exitCode"] == 0 and not c["passed"] for c in self.evidence[-1]["checks"]))

    def test_real_default_failure_rejected_even_when_v2_and_v3_checks_pass(self):
        # This public fixture omits V1, while its manifest still targets old Android.
        with self.assertRaisesRegex(a.VerificationError, "default"):
            self.verify("golden-aligned-v2v3-out.apk")
        checks = self.evidence[-1]["checks"]
        self.assertNotEqual(checks[0]["exitCode"], 0)
        self.assertTrue(checks[1]["passed"] and checks[2]["passed"])

    def test_real_failed_signature_evidence_and_apk_are_retained_without_signing(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            inputs = release.SigningInputs(temporary_root / "never-opened.p12", "suse-campus-android",
                                           "SYNTHETIC_INTEGRATION_SECRET", "SYNTHETIC_INTEGRATION_SECRET")
            identity = {"signingCertificateSha256": self.pin, "githubRepository": a.REPOSITORY}
            def public_fixture_copy(unsigned, signed, ignored_inputs):
                shutil.copyfile(unsigned, signed)  # No signing or private key operation.
            def real_signature_verification(apk, variant, **kwargs):
                self.assertEqual(a.sha256(apk), kwargs["expected_sha256"])
                with patch.object(a, "run_tool", side_effect=self.api29_default):
                    a.verify_release_signatures(apk, self.pin, checks=kwargs["signature_checks"])
                self.fail("V2-only fixture must not be accepted")
            with patch.object(release, "ROOT", temporary_root), \
                    patch.object(release, "read_identity", return_value=identity), \
                    patch.object(release, "sign_apk", side_effect=public_fixture_copy), \
                    patch.object(release, "verify_apk", side_effect=real_signature_verification), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(a.VerificationError) as caught:
                    release.sign_and_deliver(self.cache / V2_ONLY, inputs,
                        {"versionName":"0.3.0", "versionCode":4, "tag":"android-v0.3.0"}, {}, {})
            retained = caught.exception.diagnostic_directory
            evidence = json.loads((retained / "diagnostics.json").read_text())
            self.assertEqual(a.sha256(retained / "signed-failed.apk"), a.sha256(self.cache / V2_ONLY))
            self.assertEqual(evidence["sha256ImmediatelyAfterSigning"], a.sha256(self.cache / V2_ONLY))
            self.assertEqual(len(evidence["signatureChecks"]), 3)
            self.assertFalse((temporary_root / "release/android/android-v0.3.0").exists())
            for check in evidence["signatureChecks"]:
                for stream in ("stdout", "stderr"):
                    self.assertEqual((retained / f"{check['name']}.{stream}.txt").read_text(), check[stream])
            self.evidence.append({"test": self._testMethodName, "fixture":V2_ONLY,
                                  "checks":evidence["signatureChecks"], "retentionVerified":True})
