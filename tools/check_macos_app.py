"""Verify and exercise the packaged app rather than only Python source."""
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import tempfile
import time


def main():
    app = Path('build/macos/dist/SUSECampusLogin.app').resolve()
    report = Path('build/macos-app-report.json').resolve()
    executable = app/'Contents/MacOS/SUSECampusLogin'
    info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
    assert info['LSMinimumSystemVersion']=='15.0'
    assert info['LSUIElement']
    architecture = subprocess.check_output(['lipo','-archs',str(executable)], text=True).strip()
    assert architecture == platform.machine(), architecture
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    with tempfile.TemporaryDirectory() as temp:
        env = dict(os.environ, HOME=temp, PYTHONPATH='', PYTHONHOME='')
        process = subprocess.Popen([str(executable),'--smoke-report',str(report)],env=env)
        try:
            time.sleep(2)
            # Consent only to this ephemeral CI machine's local-network test dialog.
            # Never change Gatekeeper, location, notification or user-machine settings.
            consent = '''tell application "System Events"
                set resultText to ""
                repeat with appName in {"UserNotificationCenter", "CoreServicesUIAgent"}
                    if exists process appName then
                        tell process appName
                            repeat with w in windows
                                try
                                    set contentsText to (value of every static text of w) as text
                                    if contentsText contains "local networks" then
                                        click button "Allow" of w
                                        set resultText to resultText & "local-network-test-consent "
                                    end if
                                end try
                            end repeat
                        end tell
                    end if
                end repeat
                return resultText
            end tell'''
            consent_result=subprocess.run(['osascript','-e',consent],capture_output=True,text=True,timeout=10)
            Path('build/macos-consent.txt').write_text(consent_result.stdout+consent_result.stderr,encoding='utf-8')
            screenshot = subprocess.run(['screencapture','-x','build/macos-window.png'],capture_output=True)
            process.wait(timeout=45)
            assert process.returncode==0,process.returncode
            assert report.exists(), 'Packaged app did not complete UI checks'
            data=json.loads(report.read_text())
            assert data['menu_items']==4 and data['engine_stopped'] and data['close_keeps_app']
            assert not list(Path(temp).rglob('settings.json'))
            data.update(architecture=architecture, signature_verified=True, screenshot_available=screenshot.returncode==0)
            report.write_text(json.dumps(data,indent=2),encoding='utf-8')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__=='__main__':
    main()
