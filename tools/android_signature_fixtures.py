"""Fetch pinned, already signed public AOSP test APKs. Never fetch or generate keys."""
import argparse
import base64
import json
from pathlib import Path
import re
import urllib.request

from android_artifacts import ROOT, require, sha256

CACHE = ROOT / ".cache/android-signature-fixtures"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Only check local fixtures, without network requests")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "tests/android_signature_fixtures.json").read_text(encoding="utf-8"))
    require(manifest["source"] == "https://android.googlesource.com/platform/tools/apksig", "Unexpected fixture source")
    require(re.fullmatch(r"[0-9a-f]{40}", manifest["commit"]), "Fixture source must be an immutable commit")
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, expected in manifest["files"].items():
        require(re.fullmatch(r"[a-zA-Z0-9_.-]+\.apk", name), "Only public APK fixtures may be fetched")
        target = CACHE / name
        if not target.is_file() or sha256(target) != expected:
            require(not args.check, f"Missing or changed fixture: {name}; run tools/android_signature_fixtures.py")
            url = f"{manifest['source']}/+/{manifest['commit']}/src/test/resources/com/android/apksig/{name}?format=TEXT"
            with urllib.request.urlopen(url, timeout=30) as response:
                encoded = response.read(5 * 1024 * 1024 + 1)
            require(len(encoded) <= 5 * 1024 * 1024, "Oversized public fixture")
            temporary = target.with_suffix(".download")
            try:
                temporary.write_bytes(base64.b64decode(encoded))
                require(sha256(temporary) == expected, "Public fixture SHA-256 mismatch")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        print(f"Verified public pre-signed fixture: {name} ({expected})")


if __name__ == "__main__":
    main()
