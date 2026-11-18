"""Prepare a checksum-verified isolated Java 21 for Robolectric API 36; no system installation."""
from pathlib import Path
import hashlib
import shutil
import urllib.request
import zipfile


def main():
    directory = Path.home() / ".cache/suse-campus-build"
    directory.mkdir(parents=True, exist_ok=True)
    url = "https://aka.ms/download-jdk/microsoft-jdk-21.0.13.0.2-windows-x64.zip"

    def fetch(address):
        return urllib.request.urlopen(urllib.request.Request(address, headers={"User-Agent": "SUSECampusLogin-local-build"}), timeout=60)

    with fetch(url + ".sha256sum.txt") as response:
        expected = response.read().decode().split()[0]
    if len(expected) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in expected):
        raise RuntimeError("Official download did not return a SHA-256 checksum")
    archive = directory / "test-jdk21.zip"
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        temporary = directory / "test-jdk21.download"
        print("Downloading isolated Microsoft JDK 21 for Android component tests", flush=True)
        with fetch(url) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Official test JDK checksum mismatch")
        temporary.replace(archive)
    with zipfile.ZipFile(archive) as compressed:
        top = compressed.namelist()[0].split("/")[0]
        if not (directory / top / "bin/java.exe").exists():
            compressed.extractall(directory)
    (directory / "test-jdk-home.txt").write_text(str(directory / top), encoding="utf-8")
    print("Isolated test Java ready; system Java unchanged", flush=True)


if __name__ == "__main__":
    main()
