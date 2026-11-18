"""Build the local Android sources in an ASCII staging path on Windows.

JDK 17/Gradle test workers misread non-ASCII Windows argument-file paths.
Only generated outputs are copied back. This script never changes OS settings.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from android_artifacts import read_version, read_identity, read_update_sources

ROOT = Path(__file__).resolve().parents[1]

TUTORIAL_IMAGES = frozenset({
    "tutorial_account.jpg", "tutorial_service.jpg", "tutorial_tile_confirm.jpg",
    "tutorial_tile_edit.jpg", "tutorial_quick_entries.jpg", "tutorial_widget_desktop.jpg",
    "tutorial_widget_catalog.jpg", "tutorial_widget_android.jpg", "tutorial_widget_picker.jpg",
    "tutorial_widget_placed.jpg",
})


def build_environment(source=None):
    # Signing credentials must not reach Gradle, its daemon, or workers.
    return {key: value for key, value in (os.environ if source is None else source).items()
            if not key.upper().startswith("SUSE_ANDROID_")}


def allowed_source(relative):
    """An allowlist, independent of gitignore (which does not govern file copies)."""
    parts = relative.parts
    if not parts or parts[0] != "android":
        return False
    if len(parts) == 2:
        return parts[1] in {"build.gradle.kts", "settings.gradle.kts", "gradle.properties",
                            "version.properties", "release-identity.json", "update-sources.json", "gradlew", "gradlew.bat"}
    if parts[1:] in (("gradle", "wrapper", "gradle-wrapper.jar"),
                     ("gradle", "wrapper", "gradle-wrapper.properties")):
        return True
    if parts[1] not in {"app", "core"}:
        return False
    if len(parts) == 3:
        return parts[2] == "build.gradle.kts"
    if len(parts) < 6 or parts[2] != "src" or parts[3] not in {"main", "test", "androidTest"}:
        return False
    name = relative.name.lower()
    if any(part.startswith(".") for part in parts) or name in {
            "settings.json", "account.enc", "local.properties", "keystore.properties", "signing.properties"}:
        return False
    if parts[4] == "kotlin":
        return relative.suffix == ".kt"
    if parts[3] == "main" and parts[4] == "res":
        return relative.suffix == ".xml" or (
            parts[:5] == ("android", "app", "src", "main", "res") and len(parts) == 7 and
            parts[5] == "drawable-nodpi" and parts[6] in TUTORIAL_IMAGES)
    if parts[3] == "main" and parts[4] == "assets":
        return parts[5:] in (("third_party_notices.txt",), ("licenses", "Apache-2.0.txt"),
                            ("licenses", "jsoup-MIT.txt"))
    return parts[3:] == ("test", "fixtures", "python_protocol.json")


def sync_sources(destination):
    destination.mkdir(parents=True, exist_ok=True)
    manifest = destination / ".suse-campus-sources.json"
    previous = json.loads(manifest.read_text()) if manifest.exists() else []
    current = []
    for source in (ROOT / "android").rglob("*"):
        relative = source.relative_to(ROOT)
        if not source.is_file() or source.is_symlink():
            continue
        # AndroidManifest.xml is the one source file directly under a source set.
        is_manifest = relative.parts == ("android", "app", "src", "main", "AndroidManifest.xml")
        if not (allowed_source(relative) or is_manifest):
            continue
        if not source.resolve().is_relative_to((ROOT / "android").resolve()):
            continue
        current.append(relative.as_posix())
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or source.read_bytes() != target.read_bytes():
            shutil.copy2(source, target)
    # Delete only stale files previously written by this script, within this staging directory.
    for old in set(previous) - set(current):
        target = (destination / old).resolve()
        if not target.is_relative_to(destination.resolve()):
            raise RuntimeError("Invalid staging manifest path")
        if target.is_file():
            target.unlink()
    (destination / "tests").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "tests/rsa_vectors.json", destination / "tests/rsa_vectors.json")
    manifest.write_text(json.dumps(current), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", nargs="*", default=[":core:test", ":app:testDebugUnitTest", ":app:lintDebug", ":app:assembleDebug", ":app:assembleDebugAndroidTest"])
    args = parser.parse_args()
    read_version()
    read_identity(require_certificate=True)
    read_update_sources()
    local_cache = Path.home() / ".cache" / "suse-campus-build"
    destination = local_cache / "workspace"
    sync_sources(destination)
    sdk_source = ROOT / ".cache/android-tools/sdk"
    sdk_target = local_cache / "sdk"
    for directory in ("platforms", "build-tools", "platform-tools", "licenses"):
        source = sdk_source / directory
        if source.exists():
            shutil.copytree(source, sdk_target / directory, dirs_exist_ok=True,
                            copy_function=lambda src, dst: dst if Path(dst).exists() and Path(src).stat().st_size == Path(dst).stat().st_size else shutil.copy2(src, dst))
    java = os.environ.get("JAVA_HOME")
    if not java:
        candidate = Path("D:/pycharm下载版/PyCharm 2023.3.5/jbr")
        if (candidate / "bin/java.exe").exists():
            java = str(candidate)
        else:
            raise SystemExit("Set JAVA_HOME to a JDK 17 installation before building.")
    environment = build_environment()
    environment.update(JAVA_HOME=java, ANDROID_HOME=str(sdk_target), ANDROID_SDK_ROOT=str(sdk_target),
                       GRADLE_USER_HOME=str(Path.home() / ".cache/suse-campus-gradle"))
    test_java_file = local_cache / "test-jdk-home.txt"
    if test_java_file.exists():
        environment["SUSE_TEST_JAVA_HOME"] = test_java_file.read_text(encoding="utf-8").strip()
    # Copy the already verified distribution to avoid another large download; Wrapper is still shipped.
    gradle_source = ROOT / ".cache/android-tools/gradle-8.13"
    gradle_target = local_cache / "gradle-8.13"
    if gradle_source.exists():
        shutil.copytree(gradle_source, gradle_target, dirs_exist_ok=True,
                        copy_function=lambda src, dst: dst if Path(dst).exists() else shutil.copy2(src, dst))
        executable = gradle_target / "bin/gradle.bat"
    else:
        executable = destination / "android/gradlew.bat"
    print(f"Build staging: {destination}", flush=True)
    result = subprocess.run([str(executable), *args.tasks, "--console=plain", "--no-configuration-cache"],
                            cwd=destination / "android", env=environment)
    for module in ("core", "app"):
        for directory in ("reports", "test-results", "outputs"):
            source = destination / "android" / module / "build" / directory
            if source.exists():
                shutil.copytree(source, ROOT / "android" / module / "build" / directory, dirs_exist_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
