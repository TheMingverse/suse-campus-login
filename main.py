import argparse
import sys
import tkinter as tk
from tkinter import messagebox


def main():
    parser = argparse.ArgumentParser(description="SUSE 校园网自动登录")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--ui-check", action="store_true", help="显示空白示例界面，8 秒后退出，不登录、不保存设置")
    parser.add_argument("--diagnose", action="store_true", help="只读网络诊断，不提交账号密码")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("此版本只支持 Windows 10 / 11。")
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    from campus_login.windows import acquire_instance
    if args.diagnose:
        from campus_login.diagnostics import connection_report
        report = connection_report()
        if sys.stdout is not None:
            print(report)
        else:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("连接诊断（只读）", report)
            root.destroy()
        return
    mutex = None if args.ui_check else acquire_instance()
    root = tk.Tk()
    root.withdraw()
    if not args.ui_check and mutex is None:
        messagebox.showinfo("程序已在运行", "请点击任务栏右下角的校园网小图标打开设置。小图标可能收在向上箭头里。")
        root.destroy()
        return
    from campus_login.gui import Application
    try:
        app = Application(root, args.background, args.ui_check)
        if not args.background or args.ui_check or not app.engine.settings.username:
            root.deiconify()
        root.mainloop()
    except Exception:
        messagebox.showerror("程序未能启动", "程序启动遇到问题。请将压缩包完整解压后重试，或保留现场联系维护者。")
        raise


if __name__ == "__main__":
    main()
