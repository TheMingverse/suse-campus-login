"""Synthetic notification demo: no settings, network, engine, or login calls."""

import argparse
import ctypes
import json
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pystray
from campus_login.gui import icon_image
from campus_login.models import Status
from campus_login.notifications import NotificationController


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto", action="store_true", help="Run synthetic cases and exit after 20 seconds")
    parser.add_argument("--capture", action="store_true", help="Capture bottom-right screen region into build only")
    args = parser.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    output = ROOT / "build" / "notification-demo"
    output.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.title("系统通知演示 · 不登录、不读取个人设置")
    root.geometry("600x380+30+30")
    actions = queue.Queue()
    report = {"synthetic_only": True, "network_calls": 0, "personal_settings_loaded": False,
              "api_calls_without_exception": [], "captures": [], "removed_without_exception": False}
    state = ctypes.c_int()
    error = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    report["windows_notification_state"] = state.value if error == 0 else None
    label = tk.StringVar(value="等待托盘准备完成；以下提示均为模拟，不代表你的真实账号状态。")
    ttk.Label(root, textvariable=label, wraplength=550).pack(padx=20, pady=20)
    icon = pystray.Icon("SUSECampusLoginNotificationDemo", icon_image(), "校园网通知演示")
    sequence = 0

    def send(message, title):
        icon.notify(message, title + "（通知演示）")
        report["api_calls_without_exception"].append(message)
        return True

    def remove():
        icon.remove_notification()
        report["removed_without_exception"] = True

    controller = NotificationController(send, remove)

    def emit(kind):
        nonlocal sequence
        sequence += 1
        controller.observe(Status("online" if kind in ("connected", "available") else kind,
                                  "模拟事件", "", kind, sequence, "demo", 0))
        label.set("已处理模拟事件：" + kind + "。实际显示由 Windows 通知设置决定。")

    def toggle():
        controller.configure(not controller.enabled, 0)
        label.set("通知已" + ("开启" if controller.enabled else "关闭"))

    for title, kind in (("模拟登录成功", "connected"), ("模拟认证未通过", "credentials"),
                        ("模拟需人工处理", "manual"), ("模拟仅校内网", "campus_only")):
        ttk.Button(root, text=title, command=lambda kind=kind: emit(kind)).pack(pady=4)
    ttk.Button(root, text="开启 / 关闭通知", command=toggle).pack(pady=4)

    def close():
        controller.close()
        icon.stop()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    ttk.Button(root, text="退出演示", command=close).pack(pady=4)

    def capture(name):
        if args.capture:
            from PIL import ImageGrab
            width = ctypes.windll.user32.GetSystemMetrics(0)
            height = ctypes.windll.user32.GetSystemMetrics(1)
            path = output / (name + ".png")
            # Only the small toast area; do not capture the rest of the desktop.
            ImageGrab.grab(bbox=(max(0, width - 570), max(0, height - 260),
                                 max(1, width - 20), max(1, height - 90))).save(path)
            report["captures"].append(path.name)

    def setup(tray):
        tray.visible = True
        actions.put("ready")

    def run():
        try:
            icon.run(setup=setup)
        except Exception:
            actions.put("error")

    def drain():
        try:
            while True:
                action = actions.get_nowait()
                if action == "ready":
                    controller.set_ready(True)
                    label.set("托盘已准备好，可点击按钮测试。所有结果都是模拟。")
                    if args.auto:
                        root.after(500, lambda: emit("connected"))
                        root.after(2500, lambda: capture("connected"))
                        root.after(3500, lambda: emit("connected"))  # cooldown: no duplicate
                        root.after(4000, remove)
                        root.after(5500, lambda: emit("credentials"))
                        root.after(7500, lambda: capture("credentials"))
                        root.after(8500, lambda: emit("credentials"))  # same fault: silent
                        root.after(9000, remove)
                        root.after(10500, lambda: emit("campus_only"))
                        root.after(12500, lambda: capture("campus-only"))
                        root.after(15000, toggle)
                        root.after(16000, lambda: emit("manual"))  # disabled: silent
                else:
                    label.set("托盘未能启动；演示不会改用弹窗。")
                    report["tray_error"] = True
        except queue.Empty:
            pass
        root.after(100, drain)

    threading.Thread(target=run, name="notification-demo", daemon=True).start()
    root.after(100, drain)
    if args.auto:
        root.after(20000, close)
    root.mainloop()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
