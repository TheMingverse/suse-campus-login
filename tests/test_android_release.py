"""Release safety tests use synthetic data and mock tools, never real signing keys."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import android_artifacts as artifacts
import android_build as build
import android_release as release


class AndroidReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.version = {"versionName": "0.3.0", "versionCode": 4, "tag": "android-v0.3.0"}
        self.fingerprint = "ab" * 32

    def version_file(self, content):
        path = self.root / "version.properties"
        path.write_text(content, encoding="utf-8")
        return path

    def signature(self, fingerprint=None, valid=True, dn="CN=Release", v3=True):
        return subprocess.CompletedProcess([], 0 if valid else 1,
            f"Signer #1 certificate SHA-256 digest: {fingerprint or self.fingerprint}\n"
            f"Signer #1 certificate DN: {dn}\n"
            "Verified using v2 scheme (APK Signature Scheme v2): true\n"
            f"Verified using v3 scheme (APK Signature Scheme v3): {str(v3).lower()}\n", "")

    def archive(self, extra=None):
        path = self.root / "synthetic.apk"
        with zipfile.ZipFile(path, "w") as archive:
            for name in ("AndroidManifest.xml", "classes.dex", "assets/third_party_notices.txt",
                         "assets/licenses/Apache-2.0.txt", "assets/licenses/jsoup-MIT.txt"):
                archive.writestr(name, b"synthetic data, not an Android package")
            if extra:
                archive.writestr(extra, b"synthetic test data")
        return path

    def manifest(self):
        manifest = ET.Element("manifest", {"package": artifacts.APPLICATION_ID})
        for p in ("INTERNET", "ACCESS_NETWORK_STATE", "ACCESS_WIFI_STATE", "ACCESS_COARSE_LOCATION", "ACCESS_FINE_LOCATION", "REQUEST_INSTALL_PACKAGES"):
            ET.SubElement(manifest, "uses-permission", {"android:name": "android.permission." + p})
        ET.SubElement(manifest, "uses-permission", {"android:name": artifacts.APPLICATION_ID + ".DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"})
        app = ET.SubElement(manifest, "application", {"android:allowBackup": "false"})
        for tag, name, exported in (("activity", "MainActivity", True), ("activity", "QuickLoginActivity", False),
                ("receiver", "SmallLoginWidget", False), ("receiver", "WideLoginWidget", False),
                ("receiver", "WidgetPinResultReceiver", False), ("service", "LoginTileService", True),
                ("provider", "androidx.startup.InitializationProvider", False),
                ("provider", "androidx.core.content.FileProvider", False),
                ("activity", "update.UpdateActivity", False),
                ("receiver", "androidx.profileinstaller.ProfileInstallReceiver", True)):
            full = name if name.startswith("androidx.") else artifacts.APPLICATION_ID + "." + name
            node = ET.SubElement(app, tag, {"android:name": full, "android:exported": str(exported).lower()})
            if name == "QuickLoginActivity":
                node.set("android:launchMode", "2")
                node.set("android:excludeFromRecents", "true")
            if name in {"LoginTileService", "androidx.profileinstaller.ProfileInstallReceiver"}:
                node.set("android:permission", "android.permission." + ("DUMP" if name.startswith("androidx") else "BIND_QUICK_SETTINGS_TILE"))
            if name == "androidx.core.content.FileProvider":
                node.set("android:authorities", artifacts.APPLICATION_ID + ".updates")
                node.set("android:grantUriPermissions", "true")
        return manifest

    def report(self):
        checks = [{"name": name, "passed": True, "exitCode": 0, "stdout": self.signature().stdout,
                   "stderr": ""} for name, _ in artifacts.SIGNATURE_CHECKS]
        return {**self.version, "variant": "release", "releaseReady": True, "signatureVerified": True,
                "applicationId": artifacts.APPLICATION_ID, "minSdk": 29, "bytes": 3,
                "sha256": artifacts.sha256(self.small_apk()), "signingCertificateSha256": self.fingerprint,
                "apk": "SUSE-CampusLogin-Android-v0.3.0-release.apk", "signatureChecks": checks}

    def small_apk(self):
        path = self.root / "verified-test-data.apk"
        path.write_bytes(b"apk")
        return path

    def test_version_and_tag_share_one_source(self):
        path = self.version_file("versionName=0.3.0\nversionCode=4\n")
        self.assertEqual(artifacts.read_version(path, "android-v0.3.0"), self.version)

    def test_invalid_or_missing_versions_are_rejected(self):
        values = ("", "versionName=0.3.0", "versionName=03.0.0\nversionCode=4",
                  "versionName=0.3.0\nversionCode=3", "versionName=0.3.0\nversionCode=4.0",
                  "versionName=0.3.0\nversionCode=2100000001", "versionName=0.3.0\nversionCode=4\nversionCode=5")
        for content in values:
            with self.subTest(content=content), self.assertRaises(artifacts.VerificationError):
                artifacts.read_version(self.version_file(content))
        with self.assertRaises(artifacts.VerificationError):
            artifacts.read_version(self.root / "absent")

    def test_prerelease_tags_are_android_specific(self):
        path = self.version_file("versionName=0.4.0-beta.1\nversionCode=5")
        self.assertEqual(artifacts.read_version(path)["tag"], "android-v0.4.0-beta.1")
        for tag in ("v0.4.0-beta.1", "android-v0.4.0", "v1.1.3"):
            with self.subTest(tag=tag), self.assertRaises(artifacts.VerificationError):
                artifacts.read_version(path, tag)

    def test_missing_public_certificate_blocks_signed_mode(self):
        identity = self.root / "identity.json"
        identity.write_text(json.dumps({"applicationId": artifacts.APPLICATION_ID,
            "githubRepository": artifacts.REPOSITORY, "signingCertificateSha256": None}))
        self.assertIsNone(artifacts.read_identity(identity)["signingCertificateSha256"])
        with self.assertRaises(artifacts.VerificationError):
            artifacts.read_identity(identity, require_certificate=True)

    def test_public_fingerprint_normalization(self):
        self.assertEqual(artifacts.normalize_digest(":".join(["AB"] * 32)), self.fingerprint)
        for value in (None, "a" * 63, "z" * 64):
            with self.subTest(value=value), self.assertRaises(artifacts.VerificationError):
                artifacts.normalize_digest(value)

    def test_public_identity_rejects_private_fields_and_wrong_repository(self):
        identity = self.root / "identity.json"
        valid = {"applicationId": artifacts.APPLICATION_ID, "githubRepository": artifacts.REPOSITORY,
                 "signingCertificateSha256": self.fingerprint}
        for changes in ({"storePassword": "synthetic-secret"}, {"githubRepository": "wrong/repo"},
                        {"signingCertificateSha256": "bad-fingerprint"}):
            identity.write_text(json.dumps({**valid, **changes}))
            with self.subTest(changes=changes), self.assertRaises(artifacts.VerificationError):
                artifacts.read_identity(identity)

    def test_version_configuration_cannot_carry_private_settings(self):
        path = self.version_file("versionName=0.3.0\nversionCode=4\nstorePassword=synthetic-secret")
        with self.assertRaises(artifacts.VerificationError):
            artifacts.read_version(path)

    def test_compiled_update_trust_must_match_local_public_identity(self):
        identity = {"applicationId": artifacts.APPLICATION_ID, "githubRepository": artifacts.REPOSITORY,
                    "signingCertificateSha256": self.fingerprint}
        output = '\n'.join(f'resource 0x7f08000{i} pkg:string/{name}: t=0x03\n  (string8) "{value}"' for i, (name, value) in enumerate((
            ("update_application_id", artifacts.APPLICATION_ID), ("update_github_repository", artifacts.REPOSITORY),
            ("update_certificate_sha256", self.fingerprint), ("update_gitee_repository", ""))))
        with patch.object(artifacts, "read_update_sources", return_value=""):
            artifacts.check_compiled_update_trust(output, identity)
            with self.assertRaises(artifacts.VerificationError):
                artifacts.check_compiled_update_trust(output.replace(self.fingerprint, "00" * 32), identity)

    def test_public_mirror_configuration_starts_empty_and_rejects_secrets(self):
        path = self.root / "update-sources.json"
        path.write_text('{"giteeRepository":null}')
        self.assertEqual(artifacts.read_update_sources(path), "")
        path.write_text('{"giteeRepository":"test-owner/test-repo"}')
        self.assertEqual(artifacts.read_update_sources(path), "test-owner/test-repo")
        for value in ({"giteeRepository":"../repo"}, {"giteeRepository":None, "password":"synthetic"}):
            path.write_text(json.dumps(value))
            with self.assertRaises(artifacts.VerificationError):
                artifacts.read_update_sources(path)

    def test_badging_rejects_wrong_package_version_code_and_sdk(self):
        good = "package: name='io.github.themingverse.susecampus' versionCode='4' versionName='0.3.0'\nsdkVersion:'29'\ntargetSdkVersion:'36'"
        artifacts.check_badging(good, self.version)
        for wrong in (good.replace("susecampus'", "other'"), good.replace("versionCode='4'", "versionCode='3'"),
                      good.replace("0.3.0", "0.2.1"), good.replace("sdkVersion:'29'", "sdkVersion:'28'")):
            with self.subTest(wrong=wrong), self.assertRaises(artifacts.VerificationError):
                artifacts.check_badging(wrong, self.version)

    def test_compiled_release_manifest_checks_actual_security(self):
        artifacts.check_manifest(self.manifest(), "release")
        for attribute, value in (("android:debuggable", "true"), ("android:allowBackup", "true"), ("android:testOnly", "true")):
            manifest = self.manifest()
            manifest.find("application").set(attribute, value)
            with self.subTest(attribute=attribute), self.assertRaises(artifacts.VerificationError):
                artifacts.check_manifest(manifest, "release")

    def test_extra_permission_or_exported_receiver_is_rejected(self):
        manifest = self.manifest()
        ET.SubElement(manifest, "uses-permission", {"android:name": "android.permission.MANAGE_EXTERNAL_STORAGE"})
        with self.assertRaises(artifacts.VerificationError):
            artifacts.check_manifest(manifest, "release")
        manifest = self.manifest()
        manifest.find("application/receiver").set("android:exported", "true")
        with self.assertRaises(artifacts.VerificationError):
            artifacts.check_manifest(manifest, "release")

    def test_xmltree_parser_preserves_scope_types_and_resource_references(self):
        output = ('N: android=uri\nE: manifest (line=2)\n  A: package="example" (Raw: "example")\n'
                  '  E: application (line=3)\n    A: android:debuggable(0x0101000f)=(type 0x12)0x0\n'
                  '    A: android:networkSecurityConfig(0x01010527)=@0x7f0b0002\n'
                  '    E: receiver (line=4)\n      A: android:exported(0x01010010)=(type 0x12)0xffffffff\n')
        root = artifacts.parse_xmltree(output)
        self.assertEqual(root.find("application").get("android:debuggable"), "false")
        self.assertEqual(root.find("application").get("android:networkSecurityConfig"), "@0x7f0b0002")
        self.assertEqual(root.find("application/receiver").get("android:exported"), "true")

    def test_optimized_resource_paths_follow_ids_and_all_configurations(self):
        output = ('resource 0x7f0b0002 pkg:xml/network_security_config: t=0x03\n  (string8) "res/8G.xml"\n'
                  'resource 0x7f0b0003 pkg:xml/widget: t=0x03\n  (string8) "res/other.xml"\n'
                  'config (night):\nresource 0x7f0b0002 pkg:xml/network_security_config: t=0x03\n  (string8) "res/N.xml"\n')
        self.assertEqual(artifacts.resource_paths(output, "@0x7f0b0002"), ["res/8G.xml", "res/N.xml"])
        with self.assertRaises(artifacts.VerificationError):
            artifacts.resource_paths(output, "@0x00000000")

    def test_network_resources_reject_widened_http_access(self):
        config = ET.fromstring('<network-security-config><base-config cleartextTrafficPermitted="false"/>'
            '<domain-config cleartextTrafficPermitted="true"><domain includeSubdomains="false">10.23.2.4</domain>'
            '<domain includeSubdomains="false">www.msftconnecttest.com</domain>'
            '<domain includeSubdomains="false">detectportal.firefox.com</domain></domain-config></network-security-config>')
        artifacts.check_network_config(config)
        config.find("domain-config/domain").set("includeSubdomains", "true")
        with self.assertRaises(artifacts.VerificationError):
            artifacts.check_network_config(config)

    def test_backup_resource_checks_require_exclusions(self):
        exclusions = ''.join(f'<exclude domain="{d}" path="."/>' for d in ("root", "file", "database", "sharedpref", "external"))
        config = ET.fromstring(f"<full-backup-content>{exclusions}</full-backup-content>")
        artifacts.check_backups(config)
        config.remove(config[0])
        with self.assertRaises(artifacts.VerificationError):
            artifacts.check_backups(config)
        with self.assertRaises(artifacts.VerificationError):
            artifacts.check_backups(ET.fromstring(f"<data-extraction-rules><cloud-backup>{exclusions}</cloud-backup></data-extraction-rules>"), True)

    def test_archive_rejects_corruption(self):
        path = self.root / "broken.apk"
        path.write_bytes(b"not a zip")
        with self.assertRaises(artifacts.VerificationError):
            artifacts.check_archive(path)

    def test_archive_rejects_secrets_and_test_credentials(self):
        self.assertFalse(artifacts.check_archive(self.archive()))
        for name in ("assets/key.p12", "assets/.env.production", "assets/account.enc", "assets/rsa_vectors.json"):
            with self.subTest(name=name), self.assertRaises(artifacts.VerificationError):
                artifacts.check_archive(self.archive(name))

    def test_unsigned_apk_is_rejected_in_formal_mode(self):
        with self.assertRaises(artifacts.VerificationError):
            artifacts.check_signature(self.signature(valid=False), "release", False, self.fingerprint)
        self.assertIsNone(artifacts.check_signature(self.signature(valid=False), "release", True, None))

    def test_signed_or_corrupted_signature_material_is_not_an_unsigned_build(self):
        for result, material in ((self.signature(), False), (self.signature(valid=False), True)):
            with self.subTest(material=material), self.assertRaises(artifacts.VerificationError):
                artifacts.check_signature(result, "release", True, None, material)

    def test_mock_default_signature_requires_pinned_identity(self):
        self.assertEqual(artifacts.check_signature(self.signature(), "release", False, self.fingerprint), self.fingerprint)
        for result, expected in ((self.signature(), "cd" * 32), (self.signature(), None),
                                 (self.signature(dn="CN=Android Debug,O=Android,C=US"), self.fingerprint)):
            with self.subTest(expected=expected, stdout=result.stdout), self.assertRaises(artifacts.VerificationError):
                artifacts.check_signature(result, "release", False, expected)

    def test_apk_hash_mismatch_stops_before_tools(self):
        path = self.archive()
        with patch.object(artifacts, "run_tool") as run, self.assertRaises(artifacts.VerificationError):
            artifacts.verify_apk(path, "release", True, "00" * 32)
        run.assert_not_called()

    def test_gradle_environment_strips_signing_credentials(self):
        env = build.build_environment({"SUSE_ANDROID_STORE_PASSWORD": "synthetic-secret", "suse_android_key_password": "x", "JAVA_HOME": "jdk"})
        self.assertEqual(env, {"JAVA_HOME": "jdk"})

    def test_source_allowlist_rejects_local_credentials(self):
        for name in ("android/private.p12", "android/signing.properties", "android/app/src/main/assets/private.p12",
                     "android/app/src/main/assets/settings.json", "android/core/src/test/fixtures/secret.json"):
            with self.subTest(name=name):
                self.assertFalse(build.allowed_source(Path(name)))
        for name in ("android/version.properties", "android/app/src/main/kotlin/example/Code.kt",
                     "android/app/src/main/assets/licenses/Apache-2.0.txt"):
            self.assertTrue(build.allowed_source(Path(name)))

    def test_sync_removes_previously_copied_disallowed_files(self):
        with patch.object(build, "ROOT", self.root):
            (self.root / "android").mkdir()
            (self.root / "android/private.p12").write_bytes(b"NOT A KEY: synthetic test")
            (self.root / "tests").mkdir()
            (self.root / "tests/rsa_vectors.json").write_text("[]")
            stage = self.root / "stage"
            (stage / "android").mkdir(parents=True)
            stale = stage / "android/private.p12"
            stale.write_bytes(b"NOT A KEY: synthetic old copy")
            (stage / ".suse-campus-sources.json").write_text('["android/private.p12"]')
            build.sync_sources(stage)
            self.assertFalse(stale.exists())
            self.assertTrue((self.root / "android/private.p12").exists())

    def test_sync_rejects_escaping_manifest_paths(self):
        stage = self.root / "stage"
        stage.mkdir()
        outside = self.root / "keep.txt"
        outside.write_text("keep")
        (stage / ".suse-campus-sources.json").write_text('["../keep.txt"]')
        with self.assertRaises(RuntimeError):
            build.sync_sources(stage)
        self.assertEqual(outside.read_text(), "keep")

    def test_key_paths_inside_repo_and_cache_are_rejected(self):
        for location in (release.ROOT / "forbidden.p12", Path.home() / ".cache/suse-campus-build/forbidden.p12"):
            with self.subTest(location=location), self.assertRaises(artifacts.VerificationError):
                release.signing_inputs({"SUSE_ANDROID_KEYSTORE_PATH": str(location), "SUSE_ANDROID_KEY_ALIAS": "suse-campus-android"})

    def test_signing_values_are_redacted_and_passwords_not_in_arguments(self):
        inputs = release.SigningInputs(self.root / "not-a-real-key.p12", "suse-campus-android", "SYNTHETIC_PASSWORD", "SYNTHETIC_PASSWORD")
        self.assertNotIn("SYNTHETIC_PASSWORD", repr(inputs))
        observed = {}
        def fake_tool(name, args, **kwargs):
            observed.update(name=name, args=args, env=dict(kwargs["environment"]))
            return subprocess.CompletedProcess([], 0, "", "")
        with patch.object(release, "run_tool", side_effect=fake_tool):
            release.sign_apk(self.root / "unsigned.apk", self.root / "signed.apk", inputs)
        self.assertNotIn("SYNTHETIC_PASSWORD", str(observed["args"]))
        self.assertEqual(observed["env"]["SUSE_ANDROID_STORE_PASSWORD"], "SYNTHETIC_PASSWORD")
        self.assertIn("env:SUSE_ANDROID_STORE_PASSWORD", observed["args"])

    def test_signer_failure_reports_category_without_exporting_password_path_or_raw_output(self):
        inputs = release.SigningInputs(self.root / "PRIVATE_PATH.p12", "suse-campus-android", "SECRET_STORE", "SECRET_KEY")
        failure = subprocess.CompletedProcess([], 1, "SECRET_STORE", "keystore password was incorrect SECRET_KEY PRIVATE_PATH.p12")
        with patch.object(release, "ROOT", self.root), patch.object(release, "run_tool", return_value=failure), \
                self.assertRaisesRegex(artifacts.VerificationError, "STORE_PASSWORD_REJECTED") as caught:
            release.sign_apk(self.root / "unsigned.apk", self.root / "signed.apk", inputs)
        reports = list((self.root / "build/android-diagnostics").glob("signer-*/signing-failure.json"))
        self.assertEqual(len(reports), 1)
        contents = reports[0].read_text(encoding="utf-8")
        for value in ("SECRET_STORE", "SECRET_KEY", "PRIVATE_PATH"):
            self.assertNotIn(value, contents + str(caught.exception))
        data = json.loads(contents)
        self.assertFalse(data["releaseReady"])
        self.assertFalse(data["rawSignerOutputSaved"])
        self.assertFalse(data["signingInputsSaved"])

    def test_signer_failure_classifies_other_input_errors_without_raw_output(self):
        inputs = release.SigningInputs(self.root / "never-read.p12", "suse-campus-android", "SYNTHETIC_STORE", "SYNTHETIC_KEY")
        for message, category in (("Cannot recover key", "KEY_PASSWORD_REJECTED"),
                                  ('Key "suse-campus-android" not found in keystore', "KEY_ALIAS_NOT_FOUND"),
                                  ("Invalid keystore format", "INVALID_KEYSTORE_FORMAT"),
                                  ("java.nio.file.NoSuchFileException", "KEYSTORE_UNAVAILABLE"),
                                  ("Unclassified failure", "SIGNER_REJECTED_INPUT")):
            with self.subTest(category=category), patch.object(release, "ROOT", self.root), \
                    patch.object(release, "run_tool", return_value=subprocess.CompletedProcess([], 1, "", message)), \
                    self.assertRaisesRegex(artifacts.VerificationError, category):
                release.sign_apk(self.root / "unsigned.apk", self.root / "signed.apk", inputs)

    def test_tool_failure_does_not_echo_raw_stderr_or_environment(self):
        failure = subprocess.CompletedProcess([], 1, "SYNTHETIC_PASSWORD", "SYNTHETIC_PASSWORD")
        with patch.object(artifacts, "sdk_tool", return_value=self.root / "zipalign.exe"), \
                patch.object(artifacts.subprocess, "run", return_value=failure):
            with self.assertRaises(artifacts.VerificationError) as caught:
                artifacts.run_tool("zipalign", [])
        self.assertNotIn("SYNTHETIC_PASSWORD", str(caught.exception))

    def test_formal_command_stops_before_build_when_pin_missing(self):
        with patch.object(sys, "argv", ["android_release.py"]), patch.object(release.subprocess, "run") as run, \
                patch.object(release, "read_identity", side_effect=artifacts.VerificationError("Certificate not configured")):
            with self.assertRaises(artifacts.VerificationError):
                release.main()
        run.assert_not_called()

    def test_unsigned_report_cannot_produce_update_metadata_or_release_directory(self):
        report = self.report()
        report.update(releaseReady=False, signatureVerified=False)
        with self.assertRaises(artifacts.VerificationError):
            release.release_metadata(report, {})
        with patch.object(release, "ROOT", self.root), self.assertRaises(artifacts.VerificationError):
            release.deliver(self.small_apk(), report, {})
        self.assertFalse((self.root / "release").exists())

    def test_unsigned_delivery_checks_hash_and_emits_no_update_metadata(self):
        report = self.report()
        report.update(releaseReady=False, signatureVerified=False)
        with patch.object(release, "ROOT", self.root):
            target = release.deliver(self.small_apk(), report, {}, unsigned=True)
        self.assertIn("unsigned", target.name)
        self.assertEqual(artifacts.sha256(target), report["sha256"])
        self.assertFalse(list(self.root.rglob("android-release.json")))

    def test_changed_apk_cannot_be_exported(self):
        path = self.small_apk()
        digest = artifacts.sha256(path)
        path.write_bytes(b"modified")
        target = self.root / "delivery.apk"
        with self.assertRaises(artifacts.VerificationError):
            release.copy_checked(path, target, digest)
        self.assertFalse(target.exists())

    def test_mock_verified_delivery_is_atomic_and_preserves_source_status(self):
        report = self.report()
        source = {"gitCommit": "synthetic-commit", "workingTreeDirty": True, "sourceIncludesUncommittedChanges": True}
        with patch.object(release, "ROOT", self.root), patch.object(release, "read_identity", return_value={
                "signingCertificateSha256": self.fingerprint, "githubRepository": artifacts.REPOSITORY}), \
                patch.object(release, "validate_release_bundle") as preflight:
            target = release.deliver(self.small_apk(), report, source)
            preflight.assert_called_once()
            with self.assertRaises(artifacts.VerificationError):
                release.deliver(self.small_apk(), report, source)
        metadata = json.loads((target.parent / "android-release.json").read_text())
        self.assertEqual(metadata["source"], source)
        self.assertEqual(metadata["fileName"], target.name)
        self.assertEqual(metadata["schemaVersion"], 1)
        self.assertEqual(metadata["platform"], "android")
        self.assertIn(report["sha256"], (target.parent / "SHA256SUMS.txt").read_text())


if __name__ == "__main__":
    unittest.main()
