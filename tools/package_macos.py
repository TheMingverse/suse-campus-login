"""Build native-architecture app, ZIP and DMG on macOS only."""
import hashlib
import importlib.metadata
import json
import platform
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from campus_login.macos import VERSION, BUNDLE_ID


def run(*args):
    return subprocess.run(args, check=True)


def main():
    assert sys.platform == 'darwin'
    name = 'SUSECampusLogin'
    arch = platform.machine()
    output = ROOT / 'build/macos'
    output.mkdir(parents=True, exist_ok=True)
    spec = output / 'macos.spec'
    spec.write_text(f'''
a = Analysis([{str(ROOT / 'main_macos.py')!r}], pathex=[{str(ROOT)!r}], binaries=[], datas=[],
    hiddenimports=['AppKit', 'Foundation', 'CoreLocation', 'CoreWLAN', 'SystemConfiguration',
                   'Security', 'ServiceManagement', 'UserNotifications', 'PyObjCTools.AppHelper'],
    excludes=['tkinter', 'pystray', 'PIL', 'unittest'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name={name!r}, console=False,
          target_arch={arch!r}, codesign_identity='-')
coll = COLLECT(exe, a.binaries, a.datas, name={name!r})
app = BUNDLE(coll, name={name + '.app'!r}, bundle_identifier={BUNDLE_ID!r},
    info_plist={{'CFBundleDisplayName': 'SUSE 校园网助手', 'CFBundleShortVersionString': '1.2.0',
        'CFBundleVersion': '12001', 'LSMinimumSystemVersion': '15.0', 'LSUIElement': True,
        'NSLocationUsageDescription': '用于识别当前校园 Wi-Fi，以便自动登录。',
        'NSLocationWhenInUseUsageDescription': '用于识别当前校园 Wi-Fi，以便自动登录。',
        'NSHighResolutionCapable': True}})
''', encoding='utf-8')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', str(output/'dist'), '--workpath', str(output/'work'), str(spec))
    app = output / 'dist' / (name + '.app')
    resources = app / 'Contents/Resources'
    shutil.copy2(ROOT/'THIRD_PARTY_NOTICES.md', resources)
    licenses = resources/'licenses'
    licenses.mkdir(exist_ok=True)
    for dist in importlib.metadata.distributions():
        for f in dist.files or []:
            if f.name.lower().startswith(('license', 'copying')) and '..' not in f.parts:
                target = licenses/dist.metadata['Name']/str(f)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(f), target)
    # Add resource files before the final signature.
    run('codesign', '--force', '--deep', '--sign', '-', str(app))
    run('codesign', '--verify', '--deep', '--strict', str(app))
    release = ROOT/'build/macos-release'
    release.mkdir(exist_ok=True)
    base = f'SUSE-CampusLogin-macOS-{VERSION}-{arch}'
    stage = output/'stage'
    stage.mkdir(exist_ok=True)
    shutil.copytree(app, stage/app.name, dirs_exist_ok=True, symlinks=True)
    (stage/'Applications').symlink_to('/Applications', target_is_directory=True)
    (stage/'使用说明.txt').write_text('SUSE 校园网助手 · Mac 测试版\n\n'
        '适用：宜宾校区，macOS 15 及以上。\n'
        '将 SUSECampusLogin.app 拖入“应用程序”，然后打开。\n'
        '填写自己的账号密码，选择服务，点击“保存并测试”。\n'
        '关闭窗口后，程序继续在菜单栏运行。\n'
        '若系统阻止首次打开，请到“系统设置 → 隐私与安全性”查看并确认。\n'
        '读取校园 Wi-Fi 名称时，请允许定位服务。\n'
        '反馈：https://github.com/TheMingverse/suse-campus-login/issues\n', encoding='utf-8')
    run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(stage), str(release/(base+'.zip')))
    run('hdiutil', 'create', '-volname', 'SUSECampusLogin', '-srcfolder', str(stage),
        '-ov', '-format', 'UDZO', str(release/(base+'.dmg')))
    freeze = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True)
    (release/f'dependencies-{arch}.txt').write_text(freeze, encoding='utf-8')
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in release.iterdir() if p.suffix in ('.zip', '.dmg')}
    (release/f'SHA256-{arch}.txt').write_text(''.join(f'{h}  {p}\n' for p,h in manifest.items()), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
