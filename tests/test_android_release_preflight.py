"""Synthetic archives + mocked SDK results; real SDK signatures have a separate suite."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import android_artifacts as a
import android_release as release
import android_release_parity as parity
import android_verify as verify

PIN = "ab" * 32
VERSION = {"versionName": "0.3.0", "versionCode": 4, "tag": "android-v0.3.0"}
IDENTITY = {"applicationId": a.APPLICATION_ID, "githubRepository": a.REPOSITORY, "signingCertificateSha256": PIN}


class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "github"
        self.directory.mkdir()
        self.filename = "SUSE-CampusLogin-Android-v0.3.0-release.apk"
        self.apk = self.directory / self.filename
        with zipfile.ZipFile(self.apk, "w") as archive:
            for name in ("AndroidManifest.xml", "classes.dex", "assets/third_party_notices.txt",
                         "assets/licenses/Apache-2.0.txt", "assets/licenses/jsoup-MIT.txt"):
                archive.writestr(name, b"Synthetic archive; not an installable APK")
        self.badging = "package: name='%s' versionCode='4' versionName='0.3.0'\nsdkVersion:'29'\ntargetSdkVersion:'36'" % a.APPLICATION_ID
        self.manifest = 'E: manifest\n  A: package="%s"\n  E: application\n' % a.APPLICATION_ID
        self.signature_failure = None
        self.debug_signer = False
        self.signer = PIN
        self.badging_by_digest = {}
        patcher = patch.object(a, "read_identity", return_value=IDENTITY)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(a, "run_tool", side_effect=self.tool)
        self.tool_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.fresh = a.verify_distribution_apk(self.apk, VERSION, a.sha256(self.apk))
        self.saved = {**self.fresh, "source": {"gitCommit": "synthetic", "workingTreeDirty": True},
                      "sha256ImmediatelyAfterSigning": self.fresh["sha256"]}
        self.metadata = {"schemaVersion": 1, "platform": "android", **VERSION, "applicationId": a.APPLICATION_ID,
                         "githubRepository": a.REPOSITORY, "minSdk": 29, "size": self.fresh["bytes"],
                         "fileName": self.filename, "sha256": self.fresh["sha256"], "signingCertificateSha256": PIN,
                         "source": self.saved["source"]}
        self.write_sidecars()
        self.tool_mock.reset_mock()

    def tool(self, name, args, **kwargs):
        if name == "apksigner":
            scheme = "v2" if "24" in args else "v3" if "28" in args else "default"
            v2, v3 = scheme == "v2", scheme != "v2"
            if self.signature_failure == scheme:
                v2 = v3 = False
            stdout = (f"Verified using v2 scheme (APK Signature Scheme v2): {str(v2).lower()}\n"
                      f"Verified using v3 scheme (APK Signature Scheme v3): {str(v3).lower()}\n"
                      f"Signer #1 certificate DN: CN={'Android Debug' if self.debug_signer else 'Synthetic Release'}\n"
                      f"Signer #1 certificate SHA-256 digest: {self.signer}\n")
            return subprocess.CompletedProcess([], 1 if self.signature_failure == "unsigned" else 0, stdout, "")
        if name == "aapt":
            badging = self.badging_by_digest.get(a.sha256(Path(kwargs["cwd"]) / "artifact.apk"), self.badging)
            return subprocess.CompletedProcess([], 0, badging if args[1] == "badging" else self.manifest, "")
        if name == "zipalign":
            return subprocess.CompletedProcess([], 0, "", "")
        self.fail(f"Unexpected tool {name}")

    def write_sidecars(self):
        a.write_json(self.directory / "android-release.json", self.metadata)
        a.write_json(self.directory / "verification.json", self.saved)
        (self.directory / "SHA256SUMS.txt").write_text(f"{self.metadata['sha256']}  {self.filename}\n", encoding="utf-8")

    def check(self):
        return a.validate_release_bundle(self.directory, VERSION)

    def fails(self, message):
        with self.assertRaisesRegex(a.VerificationError, message):
            self.check()

    def mirror(self):
        target = self.root / "gitee"
        shutil.copytree(self.directory, target)
        return target

    def test_normal_bundle_runs_three_signature_checks_and_preserves_all_bytes(self):
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        report = self.check()
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["publicReleaseAuthorized"])
        calls = [call for call in self.tool_mock.call_args_list if call.args[0] == "apksigner"]
        self.assertEqual(len(calls), 3)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_missing_apk(self):
        self.apk.unlink()
        self.fails("four delivery files")

    def test_corrupted_apk(self):
        data = bytearray(self.apk.read_bytes()); data[30] ^= 1; self.apk.write_bytes(data)
        self.fails("SHA-256")
        self.tool_mock.assert_not_called()

    def test_corrupted_archive_even_if_hash_sidecars_are_updated(self):
        self.apk.write_bytes(b"not an APK ZIP")
        self.metadata.update(size=self.apk.stat().st_size, sha256=a.sha256(self.apk))
        self.write_sidecars()
        self.fails("ZIP archive")

    def test_wrong_sha256sums(self):
        (self.directory / "SHA256SUMS.txt").write_text(f"{'00' * 32}  {self.filename}\n")
        self.fails("SHA256SUMS")

    def test_duplicate_checksum_entries(self):
        path = self.directory / "SHA256SUMS.txt"
        path.write_text(path.read_text() * 2)
        self.fails("SHA256SUMS")

    def test_manifest_sha256_mismatch(self):
        self.metadata["sha256"] = "00" * 32; self.write_sidecars()
        self.fails("SHA-256")

    def test_wrong_version_code_in_metadata(self):
        self.metadata["versionCode"] = 5; self.write_sidecars()
        self.fails("expected configuration")

    def test_wrong_actual_apk_version(self):
        self.badging = self.badging.replace("versionCode='4'", "versionCode='5'")
        self.fails("package or version")

    def test_wrong_actual_apk_version_name(self):
        self.badging = self.badging.replace("versionName='0.3.0'", "versionName='0.4.0'")
        self.fails("package or version")

    def test_wrong_tag(self):
        self.metadata["tag"] = "v0.3.0"; self.write_sidecars()
        self.fails("Tag")

    def test_wrong_metadata_application_id(self):
        self.metadata["applicationId"] = "other.app"; self.write_sidecars()
        self.fails("applicationId")

    def test_wrong_actual_package(self):
        self.badging = self.badging.replace(a.APPLICATION_ID, "other.app")
        self.fails("package or version")

    def test_wrong_metadata_certificate(self):
        self.metadata["signingCertificateSha256"] = "cd" * 32; self.write_sidecars()
        self.fails("certificate")

    def test_wrong_actual_certificate(self):
        self.signer = "cd" * 32
        self.fails("identity mismatch")

    def test_unsigned_apk(self):
        self.signature_failure = "unsigned"
        self.fails("signature verification failed")

    def test_debug_signer_even_with_pinned_fingerprint(self):
        self.debug_signer = True
        self.fails("Debug signing identity")

    def test_debuggable_manifest(self):
        self.manifest += "    A: android:debuggable(0x0101000f)=(type 0x12)0xffffffff\n"
        self.fails("debuggable")

    def test_v2_signature_failure(self):
        self.signature_failure = "v2"
        self.fails("v2")

    def test_v3_signature_failure(self):
        self.signature_failure = "v3"
        self.fails("v3")

    def test_default_signature_failure(self):
        self.signature_failure = "default"
        self.fails("default")

    def test_stale_verification_fields(self):
        for key, value in (("sha256", "00" * 32), ("bytes", 1), ("versionCode", 5), ("releaseReady", False),
                           ("signingCertificateSha256", "cd" * 32), ("apk", "another.apk")):
            previous = self.saved[key]
            self.saved[key] = value; self.write_sidecars()
            with self.subTest(key=key): self.fails("verification.json")
            self.saved[key] = previous

    def test_forged_pass_flag_cannot_hide_failed_saved_v3_output(self):
        check = self.saved["signatureChecks"][2]
        check["stdout"] = check["stdout"].replace("v3): true", "v3): false")
        check["schemes"]["v3"] = False
        self.write_sidecars()
        self.fails("v3")

    def test_missing_saved_signature_checks(self):
        self.saved["signatureChecks"] = []; self.write_sidecars()
        self.fails("three signature checks")

    def test_wrong_saved_sdk_range(self):
        self.saved["signatureChecks"][1]["sdkOptions"] = []; self.write_sidecars()
        self.fails("invalid v2")

    def test_wrong_saved_provenance(self):
        self.saved["source"] = {"gitCommit": "other"}; self.write_sidecars()
        self.fails("source provenance")

    def test_duplicate_json_field(self):
        path = self.directory / "android-release.json"
        path.write_text(path.read_text().replace('"schemaVersion": 1,', '"schemaVersion": 1, "schemaVersion": 1,'))
        self.fails("duplicate JSON")

    def test_boolean_version_is_not_an_integer(self):
        self.metadata["versionCode"] = True; self.write_sidecars()
        self.fails("integer")

    def test_extra_unsigned_apk_is_rejected(self):
        (self.directory / "unsigned.apk").write_bytes(b"synthetic")
        self.fails("four delivery files")

    def test_wrong_filename_and_path_traversal(self):
        self.metadata["fileName"] = "../outside.apk"; self.write_sidecars()
        self.fails("fileName")

    def test_apk_mutation_during_verification_is_rejected(self):
        original = self.tool
        def mutate(name, args, **kwargs):
            if name == "zipalign": self.apk.write_bytes(b"changed during verification")
            return original(name, args, **kwargs)
        self.tool_mock.side_effect = mutate
        self.fails("APK changed")

    def test_sidecar_mutation_during_verification_is_rejected(self):
        original = self.tool
        def mutate(name, args, **kwargs):
            if name == "zipalign": (self.directory / "SHA256SUMS.txt").write_text("changed")
            return original(name, args, **kwargs)
        self.tool_mock.side_effect = mutate
        self.fails("files changed")

    def test_parity_gitee_not_configured(self):
        self.assertEqual(parity.compare_releases(self.directory)["status"], "NOT_CONFIGURED")

    def test_parity_identical_local_downloads(self):
        result = parity.compare_releases(self.directory, self.mirror())
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["dualPlatformVerified"])
        self.assertTrue(result["localBundlesIdentical"])

    def test_parity_different_metadata_bytes(self):
        mirror = self.mirror()
        path = mirror / "android-release.json"
        path.write_text(json.dumps(self.metadata, separators=(",", ":")))
        self.assertEqual(parity.compare_releases(self.directory, mirror)["status"], "FAIL")

    def test_parity_different_metadata_provenance(self):
        mirror = self.mirror()
        for filename in ("android-release.json", "verification.json"):
            path = mirror / filename; data = json.loads(path.read_text()); data["source"]["gitCommit"] = "other"
            a.write_json(path, data)
        result = parity.compare_releases(self.directory, mirror)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("android-release.json: source", result["differences"])

    def test_parity_rejects_corrupt_mirror_before_claiming_pass(self):
        mirror = self.mirror(); (mirror / self.filename).write_bytes(b"broken")
        with self.assertRaises(a.VerificationError): parity.compare_releases(self.directory, mirror)

    def test_preflight_accepts_portable_paths_but_parity_requires_original_evidence_bytes(self):
        mirror = self.mirror()
        path = mirror / "verification.json"; data = json.loads(path.read_text())
        data.update(apk="/another/machine/" + self.filename, verifiedAtUtc="2030-01-01T00:00:00Z")
        a.write_json(path, data)
        self.assertEqual(a.validate_release_bundle(mirror)["status"], "PASS")
        self.assertEqual(parity.compare_releases(self.directory, mirror)["status"], "FAIL")

    def test_parity_different_valid_apk_hash_and_size(self):
        mirror = self.mirror()
        apk = mirror / self.filename
        with zipfile.ZipFile(apk, "a") as archive:
            archive.writestr("assets/synthetic-extra.txt", "different synthetic artifact")
        report = a.verify_distribution_apk(apk, VERSION, a.sha256(apk))
        saved = {**self.saved, **report, "sha256ImmediatelyAfterSigning": report["sha256"]}
        metadata = {**self.metadata, "sha256": report["sha256"], "size": report["bytes"]}
        a.write_json(mirror / "verification.json", saved)
        a.write_json(mirror / "android-release.json", metadata)
        (mirror / "SHA256SUMS.txt").write_text(f"{report['sha256']}  {self.filename}\n")
        result = parity.compare_releases(self.directory, mirror)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("android-release.json: sha256", result["differences"])
        self.assertIn("android-release.json: size", result["differences"])

    def test_parity_different_valid_version_tag_and_filename(self):
        mirror = self.mirror()
        filename = "SUSE-CampusLogin-Android-v0.4.0-release.apk"
        apk = mirror / filename
        (mirror / self.filename).rename(apk)
        with zipfile.ZipFile(apk, "a") as archive:
            archive.writestr("assets/synthetic-version.txt", "0.4.0")
        version = {"versionName": "0.4.0", "versionCode": 5, "tag": "android-v0.4.0"}
        digest = a.sha256(apk)
        self.badging_by_digest[digest] = self.badging.replace("versionCode='4'", "versionCode='5'").replace("versionName='0.3.0'", "versionName='0.4.0'")
        report = a.verify_distribution_apk(apk, version, digest)
        a.write_json(mirror / "verification.json", {**self.saved, **report, "sha256ImmediatelyAfterSigning": digest})
        a.write_json(mirror / "android-release.json", {**self.metadata, **version, "fileName": filename, "sha256": digest, "size": report["bytes"]})
        (mirror / "SHA256SUMS.txt").write_text(f"{digest}  {filename}\n")
        result = parity.compare_releases(self.directory, mirror)
        self.assertEqual(result["status"], "FAIL")
        for key in ("versionName", "versionCode", "tag", "fileName"):
            self.assertIn(f"android-release.json: {key}", result["differences"])

    def test_parity_rejects_mirror_signing_identity_mismatch(self):
        mirror = self.mirror()
        path = mirror / "android-release.json"; data = json.loads(path.read_text())
        data["signingCertificateSha256"] = "cd" * 32; a.write_json(path, data)
        with self.assertRaisesRegex(a.VerificationError, "certificate"):
            parity.compare_releases(self.directory, mirror)

    def test_parity_rejects_mirror_checksum_mismatch(self):
        mirror = self.mirror(); (mirror / "SHA256SUMS.txt").write_text("invalid")
        with self.assertRaisesRegex(a.VerificationError, "SHA256SUMS"):
            parity.compare_releases(self.directory, mirror)

    def test_preflight_rejects_missing_or_malformed_sidecars(self):
        for filename in ("android-release.json", "verification.json", "SHA256SUMS.txt"):
            path = self.directory / filename
            original = path.read_bytes()
            with self.subTest(filename=filename):
                path.unlink()
                with self.assertRaises(a.VerificationError): self.check()
                path.write_bytes(b"not valid metadata")
                with self.assertRaises(a.VerificationError): self.check()
            path.write_bytes(original)

    def test_original_formal_directory_is_never_replaced(self):
        target = self.root / "release/android/android-v0.3.0"
        target.mkdir(parents=True)
        sentinel = target / "preserve.txt"; sentinel.write_text("existing release")
        with patch.object(release, "ROOT", self.root), self.assertRaisesRegex(a.VerificationError, "already exists"):
            release.deliver(self.apk, self.saved, self.saved["source"])
        self.assertEqual(sentinel.read_text(), "existing release")
        self.assertEqual(list(target.iterdir()), [sentinel])

    def test_parity_cli_exit_codes_and_no_report_file_writes(self):
        for extra, status, code in (([], "NOT_CONFIGURED", 2), (["--gitee", str(self.mirror())], "PASS", 0),
                                     (["--gitee", str(self.root / "missing")], "FAIL", 1)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(parity.main(["--github", str(self.directory), *extra]), code)
            self.assertEqual(json.loads(output.getvalue())["status"], status)

    def test_verify_cli_reuses_preflight_without_build_reports(self):
        with patch.object(sys, "argv", ["android_verify.py", "--release-dir", str(self.directory)]), \
                patch.object(verify, "read_version", return_value=VERSION), \
                patch.object(verify, "quality_reports") as quality, contextlib.redirect_stdout(io.StringIO()) as output:
            verify.main()
        quality.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "PASS")

    def test_failed_preflight_prevents_formal_directory_export(self):
        with patch.object(release, "ROOT", self.root), patch.object(release, "read_identity", return_value=IDENTITY), \
                patch.object(release, "validate_release_bundle", side_effect=a.VerificationError("synthetic preflight failed")):
            with self.assertRaisesRegex(a.VerificationError, "preflight failed"):
                release.deliver(self.apk, self.saved, self.saved["source"])
        self.assertFalse((self.root / "release/android/android-v0.3.0").exists())
        self.assertFalse(list((self.root / "release/android").glob(".pending-*")))
        self.assertTrue(self.apk.exists())


if __name__ == "__main__":
    unittest.main()
