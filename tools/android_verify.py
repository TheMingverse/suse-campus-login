"""Inspect a local Android APK and build reports; release mode fails closed."""
import argparse
import json
from pathlib import Path
import subprocess

from android_artifacts import (ROOT, VerificationError, provenance, quality_reports, require,
                               read_version, run_tool, sha256, validate_release_bundle, verify_apk, write_json)


def quick_entry_source_checks():
    source_root = ROOT / "android/app/src/main/kotlin/io/github/themingverse/susecampus"
    entry = (source_root / "QuickWidgets.kt").read_text(encoding="utf-8")
    require("PendingIntent.getActivity" in entry and "FLAG_IMMUTABLE" in entry and
            "PendingIntent.getBroadcast" not in entry, "Unexpected widget entry implementation")
    pin = (source_root / "AndroidWidgetPinGateway.kt").read_text(encoding="utf-8")
    require("PendingIntent.getBroadcast" in pin and "FLAG_IMMUTABLE" in pin and
            "allowLogin = false" in pin and "LoginEngine" not in pin and "store.load" not in pin,
            "Widget pin request must not access credentials or authenticate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("debug", "release"), default="debug")
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--allow-unsigned", action="store_true", help="Only inspect an unsigned Release intermediate")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--tag")
    parser.add_argument("--release-dir", type=Path, help="Read-only preflight of an existing four-file release directory; emits JSON to stdout")
    args = parser.parse_args()
    if args.release_dir is not None:
        require(args.apk is None and not args.allow_unsigned and args.expected_sha256 is None and args.variant == "debug",
                "--release-dir cannot be combined with APK inspection options")
        result = validate_release_bundle(args.release_dir, expected_version=read_version(tag=args.tag))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    suffix = "debug/app-debug.apk" if args.variant == "debug" else "release/app-release-unsigned.apk"
    apk = args.apk or ROOT / "android/app/build/outputs/apk" / suffix
    report = verify_apk(apk, args.variant, args.allow_unsigned, args.expected_sha256, args.tag)
    report.update(quality_reports(args.variant))
    quick_entry_source_checks()
    if args.variant == "debug":
        test_apk = ROOT / "android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
        run_tool("apksigner", ["verify", test_apk])
        report.update(testApk=str(test_apk), testApkSha256=sha256(test_apk))
        report["componentSimulationTestCount"] = sum(t["tests"] for t in report["jvmTests"] if
            t["suite"].endswith(("QuickComponentsTest", "LoginTileServiceTest", "WidgetPinGatewayTest", "AndroidUpdateTest")))
    report.update(phase="6B", version=report["versionName"], source=provenance())
    name = "verification.json" if args.variant == "debug" else "release-verification.json"
    output = ROOT / "build/android" / name
    write_json(output, report)
    print(json.dumps({k: report[k] for k in ("apk", "sha256", "versionName", "versionCode", "signatureVerified",
                                           "releaseReady", "jvmTestCount", "lintErrors", "lintWarnings")}, ensure_ascii=False, indent=2))
    print(f"Report: {output}")


if __name__ == "__main__":
    try:
        main()
    except (VerificationError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Android verification stopped: {error}" if isinstance(error, VerificationError)
              else "Android verification stopped: tool, file, or report unavailable")
        raise SystemExit(1)
