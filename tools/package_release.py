"""Build only code/docs; user settings live outside this tree and are never copied."""

import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from campus_login.gui import icon_image
from campus_login import __version__


def main():
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(ROOT / ".cache" / "pyinstaller")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    icon = build / "campus.ico"
    icon_image().save(icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "CampusLogin", "--icon", str(icon), "--hidden-import", "pystray._win32",
        "--exclude-module", "unittest", "--exclude-module", "pytest", str(ROOT / "main.py"),
    ], cwd=ROOT, check=True)
    destination = ROOT / "release" / f"SUSE-CampusLogin-Windows-v{__version__}"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "dist" / "CampusLogin.exe", destination / "CampusLogin.exe")
    shutil.copy2(ROOT / "docs" / "使用说明.html", destination / "使用说明.html")
    shutil.copy2(ROOT / "docs" / "settings-window.png", destination / "settings-window.png")
    shutil.copy2(ROOT / "docs" / "先读我.txt", destination / "先读我.txt")
    shutil.copy2(ROOT / "docs" / "升级说明.txt", destination / "升级说明.txt")
    shutil.copy2(ROOT / "docs" / "验证记录.md", destination / "验证记录.md")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", destination / "THIRD_PARTY_NOTICES.md")
    license_files = []
    for package_name in ("requests", "urllib3", "certifi", "charset-normalizer", "idna", "Pillow", "pystray", "six", "pyinstaller"):
        distribution = importlib.metadata.distribution(package_name)
        for entry in distribution.files or []:
            if entry.name.lower().startswith(("license", "copying")) and ".." not in entry.parts:
                target = destination / "licenses" / package_name / str(entry)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(entry), target)
                license_files.append(target)
    for name, source in (("Python-LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"),
                         ("Tk-license.terms", Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms")):
        if source.exists():
            target = destination / "licenses" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            license_files.append(target)
    # Include the exact LGPL dependency source so recipients can replace/rebuild it.
    pystray = importlib.metadata.distribution("pystray")
    for entry in pystray.files or []:
        if entry.parts[0] == "pystray" and entry.suffix == ".py":
            target = destination / "third_party_source" / str(entry)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pystray.locate_file(entry), target)
            license_files.append(target)
    dependencies = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True,
                                  text=True, check=True).stdout
    (ROOT / "requirements-lock.txt").write_text(dependencies, encoding="utf-8")
    archive = destination.parent / (destination.name + ".zip")
    # Explicit allowlist avoids accidentally shipping a local file from a prior run.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for name in ("CampusLogin.exe", "使用说明.html", "settings-window.png", "先读我.txt", "升级说明.txt", "验证记录.md", "THIRD_PARTY_NOTICES.md"):
            package.write(destination / name, destination.name + "/" + name)
        for path in license_files:
            package.write(path, destination.name + "/" + path.relative_to(destination).as_posix())
    digest = hashlib.sha256((destination / "CampusLogin.exe").read_bytes()).hexdigest()
    lines = []
    for executable in sorted(destination.parent.glob("SUSE-CampusLogin-Windows-v*/CampusLogin.exe")):
        checksum = hashlib.sha256(executable.read_bytes()).hexdigest()
        lines.append(f"{checksum}  {executable.parent.name}/CampusLogin.exe")
    for bundle in sorted(destination.parent.glob("SUSE-CampusLogin-Windows-v*.zip")):
        checksum = hashlib.sha256(bundle.read_bytes()).hexdigest()
        lines.append(f"{checksum}  {bundle.name}")
    (destination.parent / "SHA256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Release: {archive}")
    print(f"SHA256: {digest}")


if __name__ == "__main__":
    main()

