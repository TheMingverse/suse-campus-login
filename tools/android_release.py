"""Build, optionally sign, and verify Android release artifacts. No publishing."""
import argparse
from dataclasses import dataclass, field
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from android_artifacts import (ROOT, VerificationError, normalize_digest, provenance, quality_reports,
                               read_identity, read_version, require, run_tool, sha256,
                               SIGNATURE_CHECKS, check_signature, signature_tool_details,
                               tool_environment, validate_release_bundle, verify_apk, write_json)
from android_build import build_environment

PREFIX = "SUSE_ANDROID_"


@dataclass(repr=False)
class SigningInputs:
    keystore: Path
    alias: str
    store_password: str = field(repr=False)
    key_password: str = field(repr=False)

    def __repr__(self):
        return "SigningInputs(<redacted>)"


def signing_inputs(environment=None):
    environment = os.environ if environment is None else environment
    location = environment.get(PREFIX + "KEYSTORE_PATH")
    alias = environment.get(PREFIX + "KEY_ALIAS")
    require(location and alias, "Set SUSE_ANDROID_KEYSTORE_PATH and SUSE_ANDROID_KEY_ALIAS; see docs/android-signing.md")
    keystore = Path(location).expanduser().resolve()
    forbidden = [ROOT.resolve(), (Path.home() / ".cache/suse-campus-build").resolve(),
                 (Path.home() / ".cache/suse-campus-gradle").resolve()]
    require(not any(keystore.is_relative_to(directory) for directory in forbidden),
            "Signing private key must be outside the repository and build caches")
    require(keystore.is_file() and keystore.suffix.lower() == ".p12", "A user-created PKCS12 .p12 key is required")
    require(alias == "suse-campus-android", "Expected key alias: suse-campus-android")
    store_password = environment.get(PREFIX + "STORE_PASSWORD")
    key_password = environment.get(PREFIX + "KEY_PASSWORD")
    if not store_password and sys.stdin.isatty():
        store_password = getpass.getpass("发行密钥密码（输入不显示）: ")
    key_password = key_password or store_password
    require(store_password and key_password, "Signing passwords missing; use hidden prompts locally or environment secrets in CI")
    return SigningInputs(keystore, alias, store_password, key_password)


def sign_apk(unsigned, signed, inputs):
    environment = tool_environment()
    environment[PREFIX + "STORE_PASSWORD"] = inputs.store_password
    environment[PREFIX + "KEY_PASSWORD"] = inputs.key_password
    try:
        result = run_tool("apksigner", ["sign", "--ks", inputs.keystore, "--ks-type", "PKCS12",
                 "--ks-key-alias", inputs.alias, "--ks-pass", "env:" + PREFIX + "STORE_PASSWORD",
                 "--key-pass", "env:" + PREFIX + "KEY_PASSWORD", "--v1-signing-enabled", "false",
                 "--v2-signing-enabled", "true", "--v3-signing-enabled", "true", "--v4-signing-enabled", "false",
                 "--out", signed, unsigned], environment=environment, check=False)
        if result.returncode != 0:
            # Interpret the error in memory. Never export raw signer output: it may contain secrets.
            output = (result.stdout + "\n" + result.stderr).lower()
            category = "SIGNER_REJECTED_INPUT"
            advice = "签名工具拒绝输入；请在本机核对现有密钥文件、别名及密码。"
            if any(value in output for value in ("keystore password was incorrect", "password verification failed",
                                                 "keystore was tampered")):
                category = "STORE_PASSWORD_REJECTED"
                advice = "密钥库密码未被接受；请在本机核对密码和键盘输入状态，不要重新创建密钥。"
            elif any(value in output for value in ("cannot recover key", "unrecoverablekeyexception")):
                category = "KEY_PASSWORD_REJECTED"
                advice = "无法解锁签名条目；请在本机核对条目密码与密钥库密码是否一致。"
            elif any(value in output for value in ("not found in keystore", "does not contain key", "no key with alias")):
                category = "KEY_ALIAS_NOT_FOUND"
                advice = "密钥库中找不到预期签名别名，请核对是否选中了原正式密钥文件。"
            elif any(value in output for value in ("invalid keystore format", "derinputstream", "toderinputstream")):
                category = "INVALID_KEYSTORE_FORMAT"
                advice = "所选文件不能按 PKCS12 读取，请核对是否为原正式 .p12 文件。"
            elif any(value in output for value in ("filenotfoundexception", "nosuchfileexception", "accessdeniedexception")):
                category = "KEYSTORE_UNAVAILABLE"
                advice = "签名工具无法访问所选密钥文件，请在本机核对文件位置及读取权限。"
            parent = ROOT / "build/android-diagnostics"
            parent.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix="signer-", dir=parent))
            write_json(directory / "signing-failure.json", {"schemaVersion": 1, "stage": "signing",
                "releaseReady": False, "exitCode": result.returncode, "category": category, "advice": advice,
                "rawSignerOutputSaved": False, "signingInputsSaved": False, "localOnly": True})
            raise VerificationError(f"apksigner: {category}。{advice} 本地无秘密诊断：{directory}")
    finally:
        environment.pop(PREFIX + "STORE_PASSWORD", None)
        environment.pop(PREFIX + "KEY_PASSWORD", None)


def release_metadata(report, source):
    require(report["releaseReady"] and report["signatureVerified"] and report["variant"] == "release",
            "Only a verified signed release can produce update metadata")
    identity = read_identity(require_certificate=True)
    require(normalize_digest(report["signingCertificateSha256"]) == identity["signingCertificateSha256"],
            "Release identity changed before delivery")
    checks = report.get("signatureChecks", [])
    require([check["name"] for check in checks] == [name for name, _ in SIGNATURE_CHECKS],
            "All three signature checks are required before delivery")
    for check in checks:
        require(check.get("passed") is True, "Signature evidence did not pass")
        result = subprocess.CompletedProcess([], check["exitCode"], check["stdout"], check["stderr"])
        check_signature(result, "release", False, identity["signingCertificateSha256"],
                        required_scheme=None if check["name"] == "default" else check["name"])
    return {"schemaVersion": 1, "platform": "android", "applicationId": report["applicationId"],
            "versionName": report["versionName"], "versionCode": report["versionCode"],
            "minSdk": report["minSdk"], "tag": report["tag"], "fileName": Path(report["apk"]).name,
            "size": report["bytes"], "sha256": report["sha256"],
            "signingCertificateSha256": normalize_digest(report["signingCertificateSha256"]),
            "githubRepository": identity["githubRepository"], "source": source}


def copy_checked(source, destination, expected_digest):
    require(sha256(source) == expected_digest, "Verified APK changed before delivery")
    shutil.copyfile(source, destination)
    require(sha256(destination) == expected_digest, "Delivered APK differs from verified APK")


def deliver(apk, report, source, unsigned=False):
    version = report["versionName"]
    if unsigned:
        require(not report["signatureVerified"] and not report["releaseReady"], "Unexpected signed intermediate")
        directory = ROOT / "build/android-delivery"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"SUSE-CampusLogin-Android-v{version}-unsigned.apk"
        with tempfile.TemporaryDirectory(prefix="unsigned-", dir=directory) as temporary:
            staged = Path(temporary) / target.name
            copy_checked(apk, staged, report["sha256"])
            staged.replace(target)
        return target
    require(report["releaseReady"], "Unsigned APK cannot enter the release directory")
    parent = ROOT / "release/android"
    parent.mkdir(parents=True, exist_ok=True)
    directory = parent / report["tag"]
    require(not directory.exists(), "Release directory already exists; refusing to replace an existing release")
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=parent) as temporary:
        stage = Path(temporary) / "delivery"
        stage.mkdir()
        target = stage / f"SUSE-CampusLogin-Android-v{version}-release.apk"
        copy_checked(apk, target, report["sha256"])
        final_report = {**report, "apk": str(directory / target.name)}
        metadata = release_metadata(final_report, source)
        write_json(stage / "android-release.json", metadata)
        write_json(stage / "verification.json", final_report)
        (stage / "SHA256SUMS.txt").write_text(f"{report['sha256']}  {target.name}\n", encoding="utf-8")
        validate_release_bundle(stage, expected_version={k: report[k] for k in ("versionName", "versionCode", "tag")})
        stage.rename(directory)
    return directory / target.name


def redact_diagnostics(value, secrets):
    """Verification output is public, but still remove any known password if echoed accidentally."""
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "<redacted>")
        return value
    if isinstance(value, list):
        return [redact_diagnostics(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_diagnostics(item, secrets) for key, item in value.items()}
    return value


def preserve_failure(apk, signed_sha256, checks, tools, reason, stage, version, secrets=()):
    """Retain only the failed APK and public verifier evidence, never the signing inputs."""
    parent = ROOT / "build/android-diagnostics"
    parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=version["tag"] + "-", dir=parent))
    actual_digest = sha256(apk)
    retained = directory / "signed-failed.apk"
    copy_checked(apk, retained, actual_digest)
    evidence = redact_diagnostics({
        "schemaVersion": 1, "releaseReady": False, "stage": stage, "reason": reason,
        "version": version, "apkFile": retained.name, "apkBytes": retained.stat().st_size,
        "sha256ImmediatelyAfterSigning": signed_sha256, "retainedApkSha256": actual_digest,
        "unchangedSinceSigning": signed_sha256 == actual_digest,
        "expectedCertificateSha256": read_identity()["signingCertificateSha256"],
        "observedCertificateSha256": sorted({fingerprint for check in checks
                                             for fingerprint in check.get("certificateSha256", [])}),
        "tools": tools, "signatureChecks": checks,
        "localOnly": True, "automaticUpload": False,
    }, secrets)
    write_json(directory / "diagnostics.json", evidence)
    for check in evidence["signatureChecks"]:
        require(check["name"] in {name for name, _ in SIGNATURE_CHECKS}, "Invalid diagnostic check name")
        for stream in ("stdout", "stderr"):
            (directory / f"{check['name']}.{stream}.txt").write_text(check[stream], encoding="utf-8")
    return directory


def sign_and_deliver(unsigned, inputs, version, quality, source):
    """The failure handler runs before temporary APK cleanup, including on cancellation."""
    tools = signature_tool_details()
    cache = Path.home() / ".cache/suse-campus-build"
    cache.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="release-", dir=cache))
    candidate = workspace / "signed.apk"
    checks = []
    signed_digest = None
    keep_workspace = False
    stage = "signing"
    try:
        staged_unsigned = workspace / "unsigned.apk"
        copy_checked(unsigned, staged_unsigned, sha256(unsigned))
        sign_apk(staged_unsigned, candidate, inputs)
        signed_digest = sha256(candidate)  # First action after the signer returns successfully.
        stage = "verification"
        report = verify_apk(candidate, "release", expected_sha256=signed_digest,
                            tag=version["tag"], signature_checks=checks)
        report.update(quality)
        report.update(phase="6A", source=source, tools=tools, sha256ImmediatelyAfterSigning=signed_digest)
        stage = "delivery"
        target = deliver(candidate, report, source)
        report["apk"] = str(target)
        return target, report
    except (VerificationError, OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        if candidate.is_file():
            reason = str(error) if isinstance(error, VerificationError) else type(error).__name__
            try:
                directory = preserve_failure(candidate, signed_digest, checks, tools, reason, stage, version,
                                             secrets=(inputs.store_password, inputs.key_password))
                print(f"Failed APK and verification evidence retained locally: {directory}", flush=True)
                error.diagnostic_directory = directory
            except (VerificationError, OSError, ValueError):
                # A disk/diagnostic error must not destroy the only remaining signed APK.
                keep_workspace = True
                print(f"Diagnostic export failed; temporary APK retained locally: {candidate}", flush=True)
        raise
    finally:
        if not keep_workspace:
            resolved = workspace.resolve()
            require(resolved.parent == cache.resolve() and resolved.name.startswith("release-")
                    and not workspace.is_symlink(), "Unsafe temporary release cleanup path")
            shutil.rmtree(resolved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unsigned", action="store_true", help="Build an unsigned intermediate; never a distributable release")
    parser.add_argument("--tag", help="Must exactly match android-v<versionName>")
    args = parser.parse_args()
    version = read_version(tag=args.tag)
    read_identity(require_certificate=not args.unsigned)
    inputs = None if args.unsigned else signing_inputs()
    source = provenance()
    tasks = [":core:test", ":app:testReleaseUnitTest", ":app:lintRelease", ":app:assembleRelease"]
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/android_build.py"), *tasks],
                   cwd=ROOT, env=build_environment(), check=True)
    original = ROOT / "android/app/build/outputs/apk/release/app-release-unsigned.apk"
    unsigned_report = verify_apk(original, "release", allow_unsigned=True, tag=version["tag"])
    quality = quality_reports("release")
    if args.unsigned:
        report = unsigned_report
        report.update(quality)
        report.update(phase="6A", source=source)
        target = deliver(original, report, source, unsigned=True)
    else:
        target, report = sign_and_deliver(original, inputs, version, quality, source)
    report["apk"] = str(target)
    write_json(ROOT / "build/android/release-verification.json", report)
    print(json.dumps({k: report[k] for k in ("apk", "sha256", "versionName", "versionCode", "signatureVerified",
                                           "releaseReady", "jvmTestCount", "lintErrors", "lintWarnings")}, ensure_ascii=False, indent=2))
    if args.unsigned:
        print("Unsigned intermediate only: not installable, not an official release; no update metadata emitted.")


if __name__ == "__main__":
    try:
        main()
    except (VerificationError, OSError, ValueError, subprocess.SubprocessError, EOFError, KeyboardInterrupt) as error:
        print(f"Android release stopped: {error}" if isinstance(error, VerificationError)
              else "Android release stopped: build, tool, or input unavailable; no publishing performed")
        raise SystemExit(1)
