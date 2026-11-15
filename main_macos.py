"""Independent macOS entrypoint; no Tk or Windows framework imports."""
import argparse
import sys


def main():
    if sys.platform != 'darwin':
        raise SystemExit('此入口仅用于 macOS。')
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-report', help='Synthetic UI only, no settings or credential access')
    args = parser.parse_args()
    import AppKit as A
    from PyObjCTools import AppHelper
    from campus_login.macos.system import acquire_instance
    from campus_login.macos.gui import Delegate
    instance = None if args.smoke_report else acquire_instance()
    if not args.smoke_report and instance is None:
        from campus_login.macos import BUNDLE_ID
        for running in A.NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID):
            if running.processIdentifier() != __import__('os').getpid():
                running.activateWithOptions_(A.NSApplicationActivateIgnoringOtherApps)
        return
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    delegate = Delegate.alloc().init()
    delegate.configure(args.smoke_report)
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == '__main__':
    main()
