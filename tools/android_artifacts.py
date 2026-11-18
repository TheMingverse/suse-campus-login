"""Local Android artifact checks. Never reads account data or signing private keys."""
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ID = "io.github.themingverse.susecampus"
REPOSITORY = "TheMingverse/suse-campus-login"
VERSION_PATTERN = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?"
SIGNATURE_CHECKS = (
    ("default", ()),
    ("v2", ("--min-sdk-version", "24", "--max-sdk-version", "27")),
    ("v3", ("--min-sdk-version", "28", "--max-sdk-version", "32")),
)


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def read_version(path=None, tag=None):
    path = path or ROOT / "android/version.properties"
    try:
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            require(key.strip() not in values, "Duplicate Android version setting")
            values[key.strip()] = value.strip()
        name, code = values["versionName"], values["versionCode"]
        require(set(values) == {"versionName", "versionCode"}, "Only public Android version settings are allowed")
        require(re.fullmatch(VERSION_PATTERN, name), "Invalid Android versionName")
        require(re.fullmatch(r"[1-9][0-9]*", code) and 4 <= int(code) <= 2100000000,
                "Android versionCode must be an integer from 4 to 2100000000")
        expected = f"android-v{name}"
        require(tag is None or tag == expected, "Release tag does not match Android version")
        return {"versionName": name, "versionCode": int(code), "tag": expected}
    except (OSError, KeyError, ValueError) as error:
        raise VerificationError("Missing or malformed Android version.properties") from error


def normalize_digest(value):
    require(isinstance(value, str), "SHA-256 must be a string")
    value = value.replace(":", "").lower()
    require(re.fullmatch(r"[0-9a-f]{64}", value), "Invalid SHA-256 digest")
    return value


def read_identity(path=None, require_certificate=False):
    try:
        identity = json.loads((path or ROOT / "android/release-identity.json").read_text(encoding="utf-8"))
        require(isinstance(identity, dict) and set(identity) ==
                {"applicationId", "githubRepository", "signingCertificateSha256"}, "Only public release identity fields are allowed")
        require(identity["applicationId"] == APPLICATION_ID, "Unexpected Android applicationId")
        require(identity["githubRepository"] == REPOSITORY, "Unexpected official GitHub repository")
        fingerprint = identity["signingCertificateSha256"]
        if fingerprint is not None:
            identity["signingCertificateSha256"] = normalize_digest(fingerprint)
        require(not require_certificate or fingerprint is not None,
                "Official signing certificate is not configured; follow docs/android-signing.md")
        return identity
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise VerificationError("Missing or malformed public release identity") from error


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_update_sources(path=None):
    try:
        value = json.loads((path or ROOT / "android/update-sources.json").read_text(encoding="utf-8"))
        require(isinstance(value, dict) and set(value) == {"giteeRepository"}, "Invalid public update source configuration")
        repository = value["giteeRepository"]
        require(repository is None or isinstance(repository, str) and
                (repository == "" or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) and
                 not any(part in {".", ".."} for part in repository.split("/"))), "Invalid Gitee repository configuration")
        return repository or ""
    except (OSError, ValueError) as error:
        raise VerificationError("Missing or malformed public update source configuration") from error


def tool_environment():
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("SUSE_ANDROID_")}
    if "JAVA_HOME" not in environment:
        candidate = Path("D:/pycharm下载版/PyCharm 2023.3.5/jbr")
        if (candidate / "bin/java.exe").exists():
            environment["JAVA_HOME"] = str(candidate)
    return environment


def sdk_tool(name):
    suffix = ".bat" if name == "apksigner" else ".exe"
    filename = name + suffix if os.name == "nt" else name
    candidates = [ROOT / ".cache/android-tools/sdk"]
    candidates += [Path(os.environ[key]) for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT") if os.environ.get(key)]
    for sdk in candidates:
        path = sdk / "build-tools/35.0.0" / filename
        if path.is_file():
            return path
    raise VerificationError(f"Missing Android Build Tools 35.0.0: {name}")


def run_tool(name, args, cwd=None, check=True, environment=None):
    environment = tool_environment() if environment is None else environment
    executable = sdk_tool(name)
    command = [str(executable)]
    if name == "apksigner":
        # Invoke the SDK's official jar directly: no .bat/cmd interpolation of key paths.
        jar = executable.parent / "lib/apksigner.jar"
        java = (Path(environment["JAVA_HOME"]) / "bin" / ("java.exe" if os.name == "nt" else "java")) \
            if environment.get("JAVA_HOME") else shutil.which("java")
        require(java and jar.is_file(), "Missing Java runtime or SDK apksigner.jar")
        command = [str(java), "-jar", str(jar)]
    result = subprocess.run([*command, *map(str, args)], cwd=cwd,
                            env=environment,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    # Do not echo raw signing tool failures or environment values.
    require(not check or result.returncode == 0, f"Android tool failed: {name}")
    return result


def parse_xmltree(output):
    """Read aapt's compiled XML tree, preserving element nesting and typed values."""
    root = None
    stack = []
    for line in output.splitlines():
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped.startswith("E: "):
            node = ET.Element(stripped[3:].split(" ", 1)[0])
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                stack[-1][1].append(node)
            else:
                require(root is None, "Multiple compiled XML roots")
                root = node
            stack.append((indent, node))
        elif stripped.startswith("A: ") and stack:
            match = re.fullmatch(r"A: ([^=(]+)(?:\(0x[0-9a-f]+\))?=(.*)", stripped)
            require(match is not None, "Unrecognized compiled XML attribute")
            key, value = match.groups()
            if value.startswith('"'):
                value = value.split('"', 2)[1]
            elif value.startswith("(type "):
                typed = re.fullmatch(r"\(type 0x([0-9a-f]+)\)0x([0-9a-f]+)", value)
                require(typed is not None, "Invalid compiled XML value")
                kind, number = (int(part, 16) for part in typed.groups())
                value = ("true" if number else "false") if kind == 0x12 else str(number)
            stack[-1][1].set(key, value)
        elif stripped.startswith("C: ") and stack:
            stack[-1][1].text = stripped[3:].strip('"')
    require(root is not None, "Missing compiled XML root")
    return root


def check_badging(output, version):
    package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", output, re.M)
    require(package is not None, "Cannot read APK package identity")
    require(package.groups() == (APPLICATION_ID, str(version["versionCode"]), version["versionName"]),
            "APK package or version differs from Android version configuration")
    require("sdkVersion:'29'" in output and "targetSdkVersion:'36'" in output, "Unexpected SDK versions")


def check_manifest(manifest, variant):
    require(manifest.tag == "manifest" and manifest.get("package") == APPLICATION_ID, "Invalid compiled manifest")
    app = manifest.find("application")
    require(app is not None, "Missing application")
    require(app.get("android:allowBackup") == "false", "APK allows account backups")
    if variant == "release":
        require(app.get("android:debuggable", "false") == "false", "Release APK is debuggable")
        require(app.get("android:testOnly", "false") == "false", "Release APK is testOnly")
    else:
        require(app.get("android:debuggable") == "true", "Expected a Debug APK")
    allowed_permissions = {"android.permission." + p for p in (
        "INTERNET", "ACCESS_NETWORK_STATE", "ACCESS_WIFI_STATE", "ACCESS_COARSE_LOCATION", "ACCESS_FINE_LOCATION",
        "REQUEST_INSTALL_PACKAGES")}
    allowed_permissions.add(APPLICATION_ID + ".DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION")
    require({p.get("android:name") for p in manifest.findall("uses-permission")} == allowed_permissions,
            "Unexpected APK permissions")
    expected = {"MainActivity", "QuickLoginActivity", "SmallLoginWidget", "WideLoginWidget",
                "WidgetPinResultReceiver", "LoginTileService", "androidx.startup.InitializationProvider",
                "androidx.profileinstaller.ProfileInstallReceiver", "update.UpdateActivity", "androidx.core.content.FileProvider"}
    debug_components = {"androidx.compose.ui.tooling.PreviewActivity", "androidx.activity.ComponentActivity"}
    if variant == "debug":
        expected |= debug_components
    components = [c for c in app if c.tag in {"activity", "activity-alias", "receiver", "service", "provider"}]
    def short_name(node):
        return node.get("android:name", "").removeprefix(APPLICATION_ID + ".")
    require({short_name(c) for c in components} == expected and len(components) == len(expected),
            "Unexpected APK component set")
    for component in components:
        name = short_name(component)
        exported = name in {"MainActivity", "LoginTileService", "androidx.profileinstaller.ProfileInstallReceiver"} | debug_components
        require(component.get("android:exported") == str(exported).lower(), "Unexpected exported component")
        require(component.get("android:process") is None, "Unexpected component process")
        if name == "LoginTileService":
            require(component.tag == "service" and
                    component.get("android:permission") == "android.permission.BIND_QUICK_SETTINGS_TILE",
                    "Tile service protection missing")
        if name == "androidx.profileinstaller.ProfileInstallReceiver":
            require(component.get("android:permission") == "android.permission.DUMP", "Profile receiver protection missing")
        if name == "QuickLoginActivity":
            require(component.get("android:launchMode") == "2" and
                    component.get("android:excludeFromRecents") == "true" and
                    component.get("android:noHistory", "false") == "false", "Quick entry lifecycle differs")
        if name == "androidx.core.content.FileProvider":
            require(component.tag == "provider" and component.get("android:authorities") == APPLICATION_ID + ".updates"
                    and component.get("android:grantUriPermissions") == "true", "Unsafe update FileProvider")
    return app


def resource_paths(output, resource_id):
    paths = []
    active = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("resource "):
            active = stripped.split()[1] == resource_id.removeprefix("@")
        elif stripped.startswith(("spec resource ", "config ", "type ", "Package ")):
            active = False
        elif active:
            match = re.fullmatch(r'\(string(?:8|16)\) "([^"\r\n]+)"', stripped)
            if match:
                paths.append(match.group(1))
    require(paths, "Referenced APK XML resource not found")
    require(all(p.startswith("res/") and p.endswith(".xml") and ".." not in Path(p).parts for p in paths),
            "Invalid APK resource path")
    return paths


def check_network_config(config):
    require(config.tag == "network-security-config", "Wrong network security resource")
    require([n.tag for n in config] == ["base-config", "domain-config"], "Unexpected network security overrides")
    require(config.find("base-config").attrib == {"cleartextTrafficPermitted": "false"}, "HTTP default must be denied")
    domains = config.find("domain-config")
    require(domains.attrib == {"cleartextTrafficPermitted": "true"}, "Unexpected HTTP exception configuration")
    require(len(domains) == 3 and {d.text for d in domains} ==
            {"10.23.2.4", "www.msftconnecttest.com", "detectportal.firefox.com"}, "Unexpected HTTP exceptions")
    require(all(d.tag == "domain" and d.attrib == {"includeSubdomains": "false"} for d in domains),
            "Unexpected HTTP subdomain exception")


def check_backups(config, extraction=False):
    expected = {(d, ".") for d in ("root", "file", "database", "sharedpref", "external")}
    if extraction:
        require(config.tag == "data-extraction-rules" and
                [n.tag for n in config] == ["cloud-backup", "device-transfer"], "Missing backup exclusion sections")
        groups = list(config)
    else:
        require(config.tag == "full-backup-content", "Wrong backup resource")
        groups = [config]
    for group in groups:
        require(len(group) == 5 and all(n.tag == "exclude" for n in group) and
                {(n.get("domain"), n.get("path")) for n in group} == expected, "APK backups are not fully excluded")


def check_compiled_update_trust(resources, identity):
    for name, expected in (("update_application_id", identity["applicationId"]),
                           ("update_github_repository", identity["githubRepository"]),
                           ("update_certificate_sha256", identity["signingCertificateSha256"]),
                           ("update_gitee_repository", read_update_sources())):
        values = []
        active = False
        for line in resources.splitlines():
            stripped = line.strip()
            if stripped.startswith("resource "):
                active = f":string/{name}:" in stripped
            elif stripped.startswith(("spec resource ", "config ", "type ", "Package ")):
                active = False
            elif active:
                match = re.fullmatch(r'\(string(?:8|16)\) "([^"\r\n]*)"', stripped)
                if match:
                    values.append(match.group(1))
        require(values and all(value == expected for value in values), "Compiled update trust differs from public release identity")


def check_archive(apk):
    try:
        with zipfile.ZipFile(apk) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)), "Duplicate APK ZIP entries")
            require(archive.testzip() is None, "APK ZIP integrity check failed")
            require({"AndroidManifest.xml", "classes.dex", "assets/third_party_notices.txt",
                     "assets/licenses/Apache-2.0.txt", "assets/licenses/jsoup-MIT.txt"}.issubset(names),
                    "APK missing code or third-party notices")
            forbidden = {"settings.json", "account.enc", "rsa_vectors.json", "python_protocol.json",
                         "keystore.properties", "signing.properties", "local.properties"}
            for name in names:
                path = Path(name)
                require(path.name.lower() not in forbidden and path.suffix.lower() not in
                        {".jks", ".keystore", ".p12", ".pfx", ".pem", ".key", ".pk8", ".p8"} and
                        not path.name.lower().startswith(".env"), "Sensitive or test file in APK")
            return any(n.upper().startswith("META-INF/") and Path(n).suffix.upper() in
                       {".RSA", ".DSA", ".EC", ".SF"} for n in names)
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        if isinstance(error, VerificationError):
            raise
        raise VerificationError("Cannot read APK ZIP archive") from error


def signature_output(result):
    """False means not verified in this range; it does not prove a block is absent."""
    schemes = {}
    for scheme, value in re.findall(
            r"^Verified using (v[0-9.]+) scheme \([^\r\n]+\): (true|false)\s*$", result.stdout, re.M):
        require(scheme not in schemes, "Duplicate signature scheme status")
        schemes[scheme] = value == "true"
    certificates = [normalize_digest(value) for value in re.findall(
        r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)\s*$", result.stdout, re.M)]
    return schemes, certificates


def check_signature(result, variant, allow_unsigned, expected, signature_material=False, required_scheme=None):
    if allow_unsigned:
        require(result.returncode != 0 and not signature_material, "Unsigned inspection requires an unsigned APK")
        return None
    require(result.returncode == 0, "APK signature verification failed")
    schemes, fingerprints = signature_output(result)
    require(len(fingerprints) == 1, "Expected one APK signer")
    fingerprint = normalize_digest(fingerprints[0])
    if variant == "release":
        require(expected is not None and fingerprint == normalize_digest(expected), "APK signing identity mismatch")
        require(not re.search(r"certificate DN: .*CN=Android Debug(?:[,\r\n]|$)", result.stdout),
                "Debug signing identity cannot be used for a release")
        if required_scheme is None:
            require(any(schemes.get(scheme) is True for scheme in ("v2", "v3", "v3.1")),
                    "Default verification did not verify a modern APK signature scheme")
        else:
            require(required_scheme in {"v2", "v3"} and schemes.get(required_scheme) is True,
                    f"Release must have a verified {required_scheme} signature in its dedicated SDK range")
    return fingerprint


def verify_release_signatures(apk, expected, cwd=None, checks=None):
    """Always collect all three checks, even when one fails; never use signing inputs."""
    checks = [] if checks is None else checks
    require(not checks, "Signature evidence must start empty")
    failures = []
    for name, options in SIGNATURE_CHECKS:
        record = {"name": name, "sdkOptions": list(options), "exitCode": None,
                  "stdout": "", "stderr": "", "schemes": {}, "certificateSha256": [], "passed": False}
        checks.append(record)
        try:
            result = run_tool("apksigner", ["verify", "--verbose", "--print-certs", *options, apk],
                              cwd=cwd, check=False)
            record.update(exitCode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            schemes, fingerprints = signature_output(result)
            record.update(schemes=schemes, certificateSha256=fingerprints)
            check_signature(result, "release", False, expected,
                            required_scheme=None if name == "default" else name)
            record["passed"] = True
        except VerificationError as error:
            record["failure"] = str(error)
            failures.append(f"{name}: {error}")
        except subprocess.TimeoutExpired as error:
            for stream, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                record[stream] = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
            record["failure"] = "Verification tool timed out"
            failures.append(f"{name}: {record['failure']}")
        except (OSError, subprocess.SubprocessError):
            # No environment or signing command can enter these diagnostics.
            record["failure"] = "Verification tool unavailable or timed out"
            failures.append(f"{name}: {record['failure']}")
    require(not failures, "Release signature verification failed: " + "; ".join(failures))
    return normalize_digest(expected)


def signature_tool_details():
    executable = sdk_tool("apksigner")
    version = run_tool("apksigner", ["version"])
    return {"buildToolsRevision": "35.0.0", "apksignerVersion": version.stdout.strip(),
            "apksignerJar": str(executable.parent / "lib/apksigner.jar"),
            "apksignerJarSha256": sha256(executable.parent / "lib/apksigner.jar")}


def verify_distribution_apk(apk, version, expected_sha256):
    """Recheck a frozen distribution, independent of newer source component lists.

    This is artifact verification, not a replacement for verify_apk's build audit.
    Historical releases need not contain components added after they were built.
    """
    identity = read_identity(require_certificate=True)
    apk = Path(apk).resolve()
    require(apk.is_file(), "APK not found")
    cache = Path.home() / ".cache/suse-campus-build/verification"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="distribution-", dir=cache) as directory:
        snapshot = Path(directory) / "artifact.apk"
        shutil.copyfile(apk, snapshot)
        digest = sha256(snapshot)
        require(digest == normalize_digest(expected_sha256), "APK SHA-256 mismatch")
        checks = []
        fingerprint = verify_release_signatures("artifact.apk", identity["signingCertificateSha256"],
                                                cwd=directory, checks=checks)
        check_archive(snapshot)
        check_badging(run_tool("aapt", ["dump", "badging", "artifact.apk"], cwd=directory).stdout, version)
        manifest = parse_xmltree(run_tool("aapt", ["dump", "xmltree", "artifact.apk", "AndroidManifest.xml"],
                                          cwd=directory).stdout)
        app = manifest.find("application")
        require(manifest.tag == "manifest" and manifest.get("package") == APPLICATION_ID and app is not None,
                "Invalid compiled manifest")
        require(app.get("android:debuggable", "false") == "false" and
                app.get("android:testOnly", "false") == "false", "Distribution APK is debuggable or testOnly")
        run_tool("zipalign", ["-c", "-P", "16", "4", "artifact.apk"], cwd=directory)
        require(sha256(apk) == digest, "APK changed during inspection")
        return {"apk": str(apk), **version, "variant": "release", "applicationId": APPLICATION_ID,
                "minSdk": 29, "targetSdk": 36, "bytes": snapshot.stat().st_size, "sha256": digest,
                "signingCertificateSha256": fingerprint, "signatureChecks": checks,
                "signatureVerified": True, "releaseReady": True, "archiveVerified": True,
                "alignmentVerified": True, "verificationScope": "distribution-artifact"}


def read_release_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"{path.name}: duplicate JSON field {key}")
            result[key] = value
        return result
    try:
        require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 1024 * 1024,
                f"{path.name}: missing, symbolic link, or too large")
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        require(isinstance(value, dict), f"{path.name}: expected JSON object")
        return value
    except (OSError, ValueError) as error:
        raise VerificationError(f"{path.name}: unreadable or malformed JSON") from error


def validate_release_bundle(directory, expected_version=None):
    """Read-only preflight of the four-file delivery contract, using fresh SDK evidence.

    expected_version=None accepts a historical version, useful for downloaded mirrors.
    The CLI supplies the current version configuration when checking a new release.
    """
    directory = Path(directory).resolve()
    require(directory.is_dir(), "Release directory not found")
    require(not (directory / "android-release.json").is_symlink() and
            (directory / "android-release.json").is_file(), "android-release.json: missing or symbolic link")
    metadata_digest = sha256(directory / "android-release.json")
    metadata = read_release_json(directory / "android-release.json")
    identity = read_identity(require_certificate=True)
    for key in ("schemaVersion", "versionCode", "minSdk", "size"):
        require(type(metadata.get(key)) is int, f"android-release.json: {key} must be an integer")
    require(metadata["schemaVersion"] == 1 and metadata.get("platform") == "android", "Unsupported Android release schema")
    name = metadata.get("versionName")
    require(isinstance(name, str) and re.fullmatch(VERSION_PATTERN, name), "Invalid release versionName")
    require(4 <= metadata["versionCode"] <= 2100000000 and metadata["minSdk"] == 29 and
            0 < metadata["size"] <= 250 * 1024 * 1024, "Invalid release versionCode, minSdk, or size")
    version = {"versionName": name, "versionCode": metadata["versionCode"], "tag": f"android-v{name}"}
    require(metadata.get("tag") == version["tag"], "Release Tag differs from versionName")
    require(expected_version is None or version == expected_version, "Release version or Tag differs from expected configuration")
    for key in ("applicationId", "githubRepository"):
        require(metadata.get(key) == identity[key], f"Release {key} differs from registered identity")
    require(normalize_digest(metadata.get("signingCertificateSha256")) == identity["signingCertificateSha256"],
            "Release certificate differs from registered identity")
    digest = metadata.get("sha256")
    require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "Invalid release APK SHA-256")
    filename = f"SUSE-CampusLogin-Android-v{name}-release.apk"
    require(metadata.get("fileName") == filename, "Release APK fileName differs from versionName")
    expected_files = {filename, "android-release.json", "SHA256SUMS.txt", "verification.json"}
    require({p.name for p in directory.iterdir()} == expected_files, "Release must contain exactly the four delivery files (missing or unexpected file)")
    require(all(not (directory / f).is_symlink() and (directory / f).is_file() for f in expected_files),
            "Release files must be regular local files, not symbolic links")
    # Freeze the sidecars as well: fail if any evidence changes while SDK checks run.
    before = {f: sha256(directory / f) for f in expected_files}
    require(before["android-release.json"] == metadata_digest, "Metadata changed during preflight")
    require((directory / filename).stat().st_size == metadata["size"], "APK size differs from android-release.json")
    require(before[filename] == digest, "APK SHA-256 differs from android-release.json")
    try:
        sums = (directory / "SHA256SUMS.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise VerificationError("SHA256SUMS.txt: unreadable UTF-8") from error
    require(sums == f"{digest}  {filename}\n", "SHA256SUMS.txt differs from APK or canonical delivery format")
    saved = read_release_json(directory / "verification.json")
    fresh = verify_distribution_apk(directory / filename, version, digest)
    for key in ("variant", "applicationId", "versionName", "versionCode", "tag", "minSdk", "targetSdk",
                "bytes", "sha256", "signingCertificateSha256", "signatureVerified", "releaseReady",
                "archiveVerified", "alignmentVerified"):
        require(type(saved.get(key)) is type(fresh[key]) and saved.get(key) == fresh[key],
                f"verification.json: {key} differs from fresh APK verification")
    # Absolute build-machine paths and verification timestamps are not portable identity.
    require(isinstance(saved.get("apk"), str) and saved["apk"].replace("\\", "/").rsplit("/", 1)[-1] == filename,
            "verification.json: APK fileName mismatch")
    require(saved.get("source") == metadata.get("source") and isinstance(saved.get("source"), dict),
            "verification.json: source provenance differs from android-release.json")
    if "sha256ImmediatelyAfterSigning" in saved:
        require(saved["sha256ImmediatelyAfterSigning"] == digest, "APK differs from hash recorded immediately after signing")
    checks = saved.get("signatureChecks")
    require(isinstance(checks, list) and len(checks) == len(SIGNATURE_CHECKS), "verification.json: missing three signature checks")
    for index, (check, (check_name, options)) in enumerate(zip(checks, SIGNATURE_CHECKS)):
        require(isinstance(check, dict) and check.get("name") == check_name and check.get("sdkOptions") == list(options)
                and check.get("passed") is True and type(check.get("exitCode")) is int,
                f"verification.json: invalid {check_name} signature evidence")
        require(isinstance(check.get("stdout"), str) and isinstance(check.get("stderr"), str), "Invalid signature tool output")
        result = subprocess.CompletedProcess([], check["exitCode"], check["stdout"], check["stderr"])
        schemes, certificates = signature_output(result)
        require(check.get("schemes") == schemes and check.get("certificateSha256") == certificates,
                f"verification.json: inconsistent parsed {check_name} signature evidence")
        check_signature(result, "release", False, identity["signingCertificateSha256"],
                        required_scheme=None if check_name == "default" else check_name)
        require(certificates == fresh["signatureChecks"][index]["certificateSha256"],
                f"verification.json: {check_name} signer differs from fresh verification")
    require(all(sha256(directory / f) == value for f, value in before.items()), "Release files changed during preflight")
    return {"status": "PASS", "scope": "local-release-bundle", "directory": str(directory),
            "metadata": metadata, "fileSha256": before, "apkVerification": fresh,
            "publicReleaseAuthorized": False}


def verify_apk(apk, variant="debug", allow_unsigned=False, expected_sha256=None, tag=None,
               signature_checks=None):
    require(variant in {"debug", "release"}, "Invalid APK variant")
    require(not allow_unsigned or variant == "release", "Unsigned inspection is only for Release intermediates")
    version = read_version(tag=tag)
    identity = read_identity(require_certificate=variant == "release" and not allow_unsigned)
    apk = Path(apk).resolve()
    require(apk.is_file(), "APK not found")
    cache = Path.home() / ".cache/suse-campus-build/verification"
    cache.mkdir(parents=True, exist_ok=True)
    # aapt on Windows cannot reliably read Unicode APK paths; inspect an immutable local snapshot.
    with tempfile.TemporaryDirectory(prefix="apk-", dir=cache) as directory:
        snapshot = Path(directory) / "artifact.apk"
        shutil.copyfile(apk, snapshot)
        digest = sha256(snapshot)
        require(expected_sha256 is None or digest == normalize_digest(expected_sha256), "APK SHA-256 mismatch")
        checks = [] if signature_checks is None else signature_checks
        fingerprint = None
        if variant == "release" and not allow_unsigned:
            # Collect evidence before structural checks, including for corrupted signed APKs.
            fingerprint = verify_release_signatures("artifact.apk", identity["signingCertificateSha256"],
                                                    cwd=directory, checks=checks)
        jar_signature = check_archive(snapshot)
        badging = run_tool("aapt", ["dump", "badging", "artifact.apk"], cwd=directory).stdout
        check_badging(badging, version)
        def xml(path):
            return parse_xmltree(run_tool("aapt", ["dump", "xmltree", "artifact.apk", path], cwd=directory).stdout)
        manifest = xml("AndroidManifest.xml")
        app = check_manifest(manifest, variant)
        resources = run_tool("aapt", ["dump", "--values", "resources", "artifact.apk"], cwd=directory).stdout
        check_compiled_update_trust(resources, identity)
        for attribute, checker in (("networkSecurityConfig", check_network_config),
                                   ("fullBackupContent", check_backups),
                                   ("dataExtractionRules", lambda tree: check_backups(tree, extraction=True))):
            resource = app.get("android:" + attribute, "")
            require(resource.startswith("@0x"), f"Missing compiled {attribute}")
            for path in resource_paths(resources, resource):
                checker(xml(path))
        for receiver in app.findall("receiver"):
            if receiver.get("android:name") not in {APPLICATION_ID + ".SmallLoginWidget", APPLICATION_ID + ".WideLoginWidget"}:
                continue
            metadata = receiver.find("meta-data")
            require(metadata is not None and metadata.get("android:name") == "android.appwidget.provider",
                    "Missing widget configuration")
            for path in resource_paths(resources, metadata.get("android:resource", "")):
                widget = xml(path)
                require(widget.tag == "appwidget-provider" and widget.get("android:updatePeriodMillis") == "0",
                        "Widgets must not perform periodic updates")
        provider = next(node for node in app.findall("provider") if node.get("android:name") == "androidx.core.content.FileProvider")
        metadata = provider.find("meta-data")
        require(metadata is not None and metadata.get("android:name") == "android.support.FILE_PROVIDER_PATHS",
                "Missing update FileProvider paths")
        for path in resource_paths(resources, metadata.get("android:resource", "")):
            paths = xml(path)
            require(paths.tag == "paths" and len(paths) == 1 and paths[0].tag == "cache-path" and
                    paths[0].attrib == {"name": "verified_update", "path": "updates/ready/"},
                    "Update FileProvider must expose only verified APKs")
        run_tool("zipalign", ["-c", "-P", "16", "4", "artifact.apk"], cwd=directory)
        if variant != "release" or allow_unsigned:
            signature = run_tool("apksigner", ["verify", "--verbose", "--print-certs", "artifact.apk"], cwd=directory, check=False)
            material = jar_signature or b"APK Sig Block 42" in snapshot.read_bytes()
            fingerprint = check_signature(signature, variant, allow_unsigned,
                                          identity["signingCertificateSha256"], material)
        require(sha256(apk) == digest, "APK changed during inspection")
        size = snapshot.stat().st_size
    return {"apk": str(apk), "variant": variant, **version, "applicationId": APPLICATION_ID,
            "minSdk": 29, "targetSdk": 36, "bytes": size, "sha256": digest,
            "signatureVerified": not allow_unsigned, "signingCertificateSha256": fingerprint,
            "signatureChecks": checks,
            "releaseReady": variant == "release" and not allow_unsigned,
            "officialSigningIdentityConfigured": identity["signingCertificateSha256"] is not None,
            "verifiedAtUtc": datetime.now(timezone.utc).isoformat(),
            "archiveVerified": True, "alignmentVerified": True, "compiledSecurityVerified": True}


def quality_reports(variant="debug"):
    tests = []
    for path in sorted((ROOT / "android").glob("*/build/test-results/**/TEST-*.xml")):
        if path.parent.name not in {"test", f"test{variant.title()}UnitTest"}:
            continue
        suite = ET.parse(path).getroot()
        tests.append({"suite": suite.get("name"), "task": path.parent.name,
                      **{key: int(suite.get(key, 0)) for key in ("tests", "failures", "errors", "skipped")}})
    require(tests and all(t["failures"] == t["errors"] == t["skipped"] == 0 for t in tests),
            "Missing or unsuccessful JVM test reports")
    require(any(t["task"] == "test" for t in tests) and any(t["task"].startswith("test") and
            t["task"].endswith("UnitTest") for t in tests), "Missing core or app JVM test reports")
    lint_path = ROOT / f"android/app/build/reports/lint-results-{variant}.xml"
    require(lint_path.is_file(), "Missing lint report")
    lint = [{"severity": n.get("severity"), "id": n.get("id"), "message": n.get("message")}
            for n in ET.parse(lint_path).getroot().findall("issue")]
    require(not any(n["severity"] in {"Error", "Fatal"} for n in lint), "Lint errors prevent delivery")
    return {"jvmTests": tests, "jvmTestCount": sum(t["tests"] for t in tests), "lint": lint,
            "lintErrors": 0, "lintWarnings": len(lint),
            "deviceTestsExecuted": False, "realCampusLoginTested": False}


def provenance():
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    return {"gitCommit": commit, "workingTreeDirty": bool(status.strip()),
            "sourceIncludesUncommittedChanges": bool(status.strip())}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
