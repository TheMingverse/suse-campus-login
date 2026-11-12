"""Verify ZIP contents and launch its exe with isolated data and no Python PATH."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from campus_login import __version__


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    name = f"SUSE-CampusLogin-Windows-v{__version__}"
    destination = ROOT / "release" / name
    archive = destination.parent / (name + ".zip")
    output = ROOT / "build" / f"release-smoke-{time.time_ns()}"
    output.mkdir(parents=True)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        names = package.namelist()
        assert all(item.startswith(name + "/") and ".." not in Path(item).parts for item in names)
        assert not any(Path(item).name.lower() in ("settings.json", "settings.tmp", "status.log") for item in names)
        for required in ("CampusLogin.exe", "使用说明.html", "升级说明.txt", "验证记录.md", "settings-window.png"):
            assert name + "/" + required in names
        package.extractall(output)
    executable = output / name / "CampusLogin.exe"
    assert sha(executable) == sha(destination / "CampusLogin.exe")
    binary = executable.read_bytes()
    offset = struct.unpack_from("<I", binary, 0x3C)[0]
    assert binary[offset:offset + 4] == b"PE\0\0"
    assert struct.unpack_from("<H", binary, offset + 4)[0] == 0x8664, "AMD64 expected"
    baseline = json.loads((ROOT / ".cache" / "v1.0-baseline.json").read_text(encoding="utf-8"))
    assert all(sha(ROOT / path) == checksum for path, checksum in baseline.items()), "Old release changed"
    previous = json.loads((ROOT / ".cache" / "v1.1.0-baseline.json").read_text(encoding="utf-8"))
    assert all(sha(ROOT / path) == checksum for path, checksum in previous.items()), "1.1.0 release changed"
    previous_patch = json.loads((ROOT / ".cache" / "v1.1.1-baseline.json").read_text(encoding="utf-8"))
    assert all(sha(ROOT / path) == checksum for path, checksum in previous_patch.items()), "1.1.1 release changed"
    previous_services = json.loads((ROOT / ".cache" / "v1.1.2-baseline.json").read_text(encoding="utf-8"))
    assert all(sha(ROOT / path) == checksum for path, checksum in previous_services.items()), "1.1.2 release changed"
    for line in (destination.parent / "SHA256.txt").read_text(encoding="utf-8").splitlines():
        checksum, relative = line.split("  ", 1)
        assert sha(destination.parent / relative) == checksum, "Checksum manifest mismatch"
    environment = dict(os.environ)
    environment["LOCALAPPDATA"] = str(output / "isolated-user")
    environment["TEMP"] = environment["TMP"] = str(output / "temp")
    Path(environment["TEMP"]).mkdir()
    windows_directory = os.environ.get("SystemRoot", r"C:\Windows")
    environment["PATH"] = str(Path(windows_directory) / "System32") + ";" + windows_directory
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    started = time.monotonic()
    result = subprocess.run([str(executable), "--ui-check"], cwd=executable.parent,
                            env=environment, timeout=35, check=True)
    assert result.returncode == 0
    assert not list((output / "isolated-user").rglob("settings.json"))
    report = {"version": __version__, "zip_crc_valid": True, "archive_file_count": len(names),
              "no_personal_settings_in_zip": True, "architecture": "AMD64", "old_1_0_unchanged": True,
              "old_1_1_0_unchanged": True, "checksum_manifest_valid": True,
              "old_1_1_1_unchanged": True,
              "old_1_1_2_unchanged": True,
              "isolated_extracted_exe_exit_code": result.returncode,
              "python_removed_from_path": True, "personal_settings_created": False,
              "duration_seconds": round(time.monotonic() - started, 2),
              "exe_sha256": sha(executable), "zip_sha256": sha(archive),
              "limits": "Same Windows 11 computer; sample UI only, no account or wired authentication."}
    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    (ROOT / "build" / "release-verification.json").write_text(report_text, encoding="utf-8")
    (ROOT / "build" / f"release-verification-{__version__}.json").write_text(report_text, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
