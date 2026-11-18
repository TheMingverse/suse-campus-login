"""Download verified official build tools; never accept SDK licenses automatically."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".cache" / "android-tools"


def download(url, target, algorithm, expected):
    if target.exists() and hashlib.new(algorithm, target.read_bytes()).hexdigest() == expected:
        return
    temporary = target.with_suffix(".download")
    print(f"Downloading {target.name}", flush=True)
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual = hashlib.new(algorithm, temporary.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError("Official download checksum mismatch")
    temporary.replace(target)


def main():
    TOOLS.mkdir(parents=True, exist_ok=True)
    gradle_url = "https://downloads.gradle.org/distributions/gradle-8.13-bin.zip"
    with urllib.request.urlopen(gradle_url + ".sha256", timeout=30) as response:
        gradle_hash = response.read().decode().strip()
    gradle_zip = TOOLS / "gradle-8.13-bin.zip"
    download(gradle_url, gradle_zip, "sha256", gradle_hash)
    if not (TOOLS / "gradle-8.13/bin/gradle.bat").exists():
        with zipfile.ZipFile(gradle_zip) as archive:
            archive.extractall(TOOLS)
    with urllib.request.urlopen("https://dl.google.com/android/repository/repository2-1.xml", timeout=45) as response:
        repository = ET.fromstring(response.read())
    package = next(p for p in repository.iter("remotePackage") if p.get("path") == "cmdline-tools;latest")
    archive = next(a for a in package.findall("archives/archive") if a.findtext("host-os") == "windows")
    complete = archive.find("complete")
    sdk_zip = TOOLS / "commandlinetools-win.zip"
    checksum = complete.find("checksum")
    download("https://dl.google.com/android/repository/" + complete.findtext("url"), sdk_zip,
             checksum.get("type", "sha1"), checksum.text)
    sdk_root = TOOLS / "sdk"
    if not (sdk_root / "cmdline-tools/latest/bin/sdkmanager.bat").exists():
        staging = TOOLS / "sdk-extracted"
        with zipfile.ZipFile(sdk_zip) as sdk_archive:
            sdk_archive.extractall(staging)
        (sdk_root / "cmdline-tools").mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging / "cmdline-tools"), str(sdk_root / "cmdline-tools/latest"))
    (TOOLS / "checksums.json").write_text(json.dumps({"gradleSha256": gradle_hash,
        "sdkArchiveChecksum": checksum.text, "sdkArchiveAlgorithm": checksum.get("type", "sha1")}, indent=2))
    print("Build tools ready. SDK licenses have NOT been accepted.", flush=True)


if __name__ == "__main__":
    main()
