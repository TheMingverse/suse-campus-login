"""Three-pass verification and failure retention; no private signing material."""
import json
import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import android_artifacts as a
import android_release as release

PIN = "ab" * 32
IDENTITY = {"signingCertificateSha256": PIN, "githubRepository": a.REPOSITORY}
VERSION = {"versionName": "0.3.0", "versionCode": 4, "tag": "android-v0.3.0"}


def result(v2=True, v3=True, fingerprint=PIN, code=0):
    return subprocess.CompletedProcess([], code,
        "Verified using v1 scheme (JAR signing): false\n"
        f"Verified using v2 scheme (APK Signature Scheme v2): {str(v2).lower()}\n"
        f"Verified using v3 scheme (APK Signature Scheme v3): {str(v3).lower()}\n"
        "Number of signers: 1\nSigner #1 certificate DN: CN=Public Test\n"
        f"Signer #1 certificate SHA-256 digest: {fingerprint}\n", "")


def successful_results():
    return [result(v2=False), result(v3=False), result(v2=False)]


class SignaturePolicyTests(unittest.TestCase):
    def verify(self, results, checks):
        with patch.object(a, "run_tool", side_effect=results) as tool:
            try:
                return a.verify_release_signatures("signed.apk", PIN, checks=checks)
            finally:
                self.assertEqual(tool.call_count, 3)
                self.assertEqual(tool.call_args_list[0].args[1], ["verify", "--verbose", "--print-certs", "signed.apk"])
                self.assertEqual(tool.call_args_list[1].args[1][3:-1], ["--min-sdk-version", "24", "--max-sdk-version", "27"])
                self.assertEqual(tool.call_args_list[2].args[1][3:-1], ["--min-sdk-version", "28", "--max-sdk-version", "32"])

    def test_valid_three_passes_allow_default_to_skip_v2(self):
        checks = []
        self.assertEqual(self.verify(successful_results(), checks), PIN)
        self.assertTrue(all(check["passed"] for check in checks))
        self.assertFalse(checks[0]["schemes"]["v2"])
        self.assertTrue(checks[1]["schemes"]["v2"])
        self.assertTrue(checks[2]["schemes"]["v3"])

    def test_v2_only_is_rejected_even_with_success_exit_codes(self):
        checks = []
        with self.assertRaisesRegex(a.VerificationError, "v3"):
            self.verify([result(v3=False)] * 3, checks)
        self.assertFalse(checks[2]["passed"])

    def test_v3_only_is_rejected_even_with_success_exit_codes(self):
        with self.assertRaisesRegex(a.VerificationError, "v2"):
            self.verify([result(v2=False)] * 3, [])

    def test_default_failure_cannot_be_overridden_by_specialized_success(self):
        checks = []
        with self.assertRaisesRegex(a.VerificationError, "default"):
            self.verify([result(code=1), result(v3=False), result(v2=False)], checks)
        self.assertEqual(len(checks), 3)
        self.assertFalse(checks[0]["passed"])

    def test_corrupt_signature_failure_is_recorded_for_all_passes(self):
        checks = []
        with self.assertRaises(a.VerificationError):
            self.verify([subprocess.CompletedProcess([], 1, "", "DOES NOT VERIFY")] * 3, checks)
        self.assertTrue(all(check["exitCode"] == 1 and check["stderr"] == "DOES NOT VERIFY" for check in checks))

    def test_pin_is_required_in_each_pass(self):
        for index in range(3):
            values = successful_results()
            values[index] = result(fingerprint="cd" * 32)
            checks = []
            with self.subTest(index=index), self.assertRaisesRegex(a.VerificationError, "identity mismatch"):
                self.verify(values, checks)
            self.assertFalse(checks[index]["passed"])

    def test_absent_scheme_status_is_not_treated_as_true(self):
        values = successful_results()
        values[1] = subprocess.CompletedProcess([], 0, f"Signer #1 certificate SHA-256 digest: {PIN}\n", "")
        with self.assertRaisesRegex(a.VerificationError, "v2"):
            self.verify(values, [])

    def test_duplicate_scheme_status_is_rejected(self):
        malformed = result()
        malformed.stdout += "Verified using v2 scheme (APK Signature Scheme v2): false\n"
        with self.assertRaisesRegex(a.VerificationError, "Duplicate"):
            self.verify([malformed, result(), result()], [])

    def test_timeout_keeps_partial_output_and_runs_remaining_checks(self):
        timeout = subprocess.TimeoutExpired("public verify", 120, output=b"partial stdout", stderr=b"partial stderr")
        checks = []
        with self.assertRaisesRegex(a.VerificationError, "timed out"):
            self.verify([timeout, result(), result()], checks)
        self.assertEqual(checks[0]["stdout"], "partial stdout")
        self.assertEqual(checks[0]["stderr"], "partial stderr")
        self.assertIsNone(checks[0]["exitCode"])


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.unsigned = self.root / "unsigned-test-data.apk"
        self.unsigned.write_bytes(b"synthetic public APK test bytes")
        self.inputs = release.SigningInputs(self.root / "never-opened.p12", "suse-campus-android",
                                           "SYNTHETIC_SECRET_1", "SYNTHETIC_SECRET_2")
        self.created = []
        self.output = io.StringIO()
        output_capture = contextlib.redirect_stdout(self.output)
        output_capture.__enter__()
        self.addCleanup(output_capture.__exit__, None, None, None)
        self.patchers = [patch.object(release, "ROOT", self.root),
                        patch.object(release, "read_identity", return_value=IDENTITY),
                        patch.object(release, "signature_tool_details", return_value={"buildToolsRevision":"35.0.0", "apksignerVersion":"0.9"}),
                        patch.object(release, "sign_apk", side_effect=self.fake_sign)]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_sign(self, unsigned, signed, inputs):
        self.created.append(signed)
        shutil.copyfile(unsigned, signed)

    def fake_verify(self, apk, variant, **kwargs):
        self.assertEqual(kwargs["expected_sha256"], a.sha256(apk))
        checks = kwargs["signature_checks"]
        a.verify_release_signatures(apk, PIN, checks=checks)
        return {**VERSION, "apk": str(apk), "variant": variant, "releaseReady": True,
                "signatureVerified": True, "signatureChecks": checks, "signingCertificateSha256": PIN,
                "sha256": a.sha256(apk), "bytes": apk.stat().st_size, "minSdk":29, "applicationId":a.APPLICATION_ID}

    def test_failed_verification_keeps_apk_raw_outputs_and_hash_without_secrets(self):
        failure = result(code=1)
        failure.stderr = "DOES NOT VERIFY SYNTHETIC_SECRET_1 SYNTHETIC_SECRET_2"
        with patch.object(release, "verify_apk", side_effect=self.fake_verify), \
                patch.object(a, "run_tool", side_effect=[failure, result(), result()]):
            with self.assertRaises(a.VerificationError) as caught:
                release.sign_and_deliver(self.unsigned, self.inputs, VERSION, {}, {})
        directory = caught.exception.diagnostic_directory
        data = json.loads((directory / "diagnostics.json").read_text())
        self.assertEqual(data["sha256ImmediatelyAfterSigning"], a.sha256(self.unsigned))
        self.assertEqual(data["retainedApkSha256"], a.sha256(directory / "signed-failed.apk"))
        self.assertTrue(data["unchangedSinceSigning"])
        self.assertEqual(data["expectedCertificateSha256"], PIN)
        self.assertEqual(data["observedCertificateSha256"], [PIN])
        self.assertEqual(len(data["signatureChecks"]), 3)
        self.assertEqual(data["tools"]["apksignerVersion"], "0.9")
        self.assertTrue(data["localOnly"])
        self.assertFalse(data["automaticUpload"])
        for path in directory.glob("*.txt"):
            self.assertNotIn("SYNTHETIC_SECRET_", path.read_text())
        self.assertNotIn("SYNTHETIC_SECRET_", (directory / "diagnostics.json").read_text())
        self.assertFalse(self.created[0].parent.exists())
        self.assertFalse((self.root / "release/android/android-v0.3.0").exists())

    def test_successful_delivery_cleans_workspace_without_diagnostic_residue(self):
        with patch.object(release, "verify_apk", side_effect=self.fake_verify), \
                patch.object(release, "validate_release_bundle"), \
                patch.object(a, "run_tool", side_effect=successful_results()):
            target, report = release.sign_and_deliver(self.unsigned, self.inputs, VERSION, {}, {})
        self.assertTrue(target.exists())
        self.assertEqual(report["sha256ImmediatelyAfterSigning"], a.sha256(target))
        self.assertFalse(self.created[0].parent.exists())
        self.assertFalse((self.root / "build/android-diagnostics").exists())
        self.assertFalse(list((self.root / "release/android").glob(".pending-*")))

    def test_failed_diagnostic_export_keeps_original_temporary_apk(self):
        with patch.object(release, "verify_apk", side_effect=a.VerificationError("verification failed")), \
                patch.object(release, "preserve_failure", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(a.VerificationError):
                release.sign_and_deliver(self.unsigned, self.inputs, VERSION, {}, {})
        workspace = self.created[0].parent
        self.assertTrue(self.created[0].exists())
        # Only the uniquely allocated test workspace is removed after verifying containment.
        expected_parent = (Path.home() / ".cache/suse-campus-build").resolve()
        self.assertEqual(workspace.resolve().parent, expected_parent)
        self.assertTrue(workspace.name.startswith("release-"))
        shutil.rmtree(workspace)

    def test_hash_change_after_signing_is_preserved_and_rejected(self):
        def mutate_then_fail(apk, *args, **kwargs):
            apk.write_bytes(b"changed after signing")
            raise a.VerificationError("APK SHA-256 mismatch")
        with patch.object(release, "verify_apk", side_effect=mutate_then_fail):
            with self.assertRaises(a.VerificationError) as caught:
                release.sign_and_deliver(self.unsigned, self.inputs, VERSION, {}, {})
        data = json.loads((caught.exception.diagnostic_directory / "diagnostics.json").read_text())
        self.assertFalse(data["unchangedSinceSigning"])

    def test_missing_three_pass_evidence_cannot_enter_formal_directory(self):
        fake = {"releaseReady": True, "signatureVerified": True, "variant":"release",
                "signingCertificateSha256":PIN}
        with self.assertRaisesRegex(a.VerificationError, "three signature checks"):
            release.release_metadata(fake, {})
