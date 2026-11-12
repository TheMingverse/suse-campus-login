# Third-party notices

This application bundles the following open-source components. Available distribution license texts are supplied in the `licenses` directory. The exact pystray Python source is supplied in `third_party_source/pystray` so it can be modified or replaced before rebuilding.

| Component | License / project |
| --- | --- |
| Python | PSF License — https://docs.python.org/3/license.html |
| Tcl/Tk | Tcl/Tk license — https://www.tcl-lang.org/software/tcltk/license.html |
| Requests | Apache-2.0 — https://github.com/psf/requests |
| urllib3 | MIT — https://github.com/urllib3/urllib3 |
| certifi | MPL-2.0 — https://github.com/certifi/python-certifi |
| charset-normalizer | MIT — https://github.com/jawah/charset_normalizer |
| idna | BSD-3-Clause — https://github.com/kjd/idna |
| Pillow | MIT-CMU — https://github.com/python-pillow/Pillow |
| pystray | LGPL-3.0 — https://github.com/moses-palmer/pystray |
| six | MIT — https://github.com/benjaminp/six |
| PyInstaller bootloader | GPL-2.0-or-later with bootloader exception — https://pyinstaller.org/en/stable/license.html |

Source code for this helper is supplied in the project alongside the build script. To modify or replace pystray/Python dependencies, install the desired source/package version into the development environment and rebuild with `python tools/package_release.py`. Exact build dependency versions are recorded in `requirements-lock.txt` in the source project. The tool and icon are unofficial and are not endorsed by the university.

