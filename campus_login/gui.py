import datetime
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from PIL import Image, ImageDraw
import pystray

from . import __version__
from .engine import LoginEngine
from .models import PORTAL_HOME, SERVICES, Settings, Status, ServiceCatalogEvent, valid_service_name
from .adapters import network_snapshot
from .diagnostics import connection_report
from .transport import NetworkContext
from .storage import SettingsStore, data_dir, status_logger
from .notifications import NotificationController
from .windows import set_autostart


def icon_image(color="#24ad78"):
    image = Image.new("RGBA", (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=16, fill=color)
    draw.arc((12, 13, 52, 53), 220, 320, fill="white", width=5)
    draw.arc((20, 25, 44, 49), 220, 320, fill="white", width=5)
    draw.ellipse((28, 42, 36, 50), fill="white")
    return image


class Application:
    def __init__(self, root, background=False, ui_check=False):
        self.root, self.ui_check = root, ui_check
        self.queue = queue.Queue()
        self.logger = status_logger()
        self.store = SettingsStore()
        self.last_log = None
        self.last_status = None
        self.exiting = False
        self.icon = None
        self.tray_ready = False
        self.paused = False
        load_error = False
        try:
            settings = Settings() if ui_check else self.store.load()
        except (OSError, ValueError, KeyError, TypeError):
            settings, load_error = Settings(), True
        self.engine = LoginEngine(network_snapshot, NetworkContext, self.queue.put)
        self.engine.update_settings(settings)
        self.notifications = NotificationController(self._send_notification, self._remove_notification,
                                                    enabled=settings.notifications_enabled,
                                                    generation=self.engine.generation)
        self._build(settings)
        root.protocol("WM_DELETE_WINDOW", self.hide)
        root.after(150, self._drain)
        if not ui_check:
            self._start_tray()
            self.engine.start()
        if background and settings.username and settings.password and not load_error:
            root.withdraw()
        if load_error:
            root.after(200, lambda: messagebox.showwarning("请重新填写", "无法读取原来的设置或受保护密码。请重新填写并保存；原密码不会上传到任何服务器。"))
        if ui_check:
            self._status(Status("online", "示例：这条连接已能上网，无需重复登录。", "已连接网线 · 以太网"))
            root.after(8000, self.exit)

    def _build(self, settings):
        root = self.root
        root.title("校园网自动登录 · SUSE")
        scale = max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
        width = min(round(780 * scale), root.winfo_screenwidth() - 80)
        height = min(round(740 * scale), root.winfo_screenheight() - 100)
        root.geometry(f"{width}x{height}")
        root.minsize(min(round(740 * scale), width), min(round(700 * scale), height))
        root.configure(bg="#f3f6fb")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f6fb")
        style.configure("TLabel", background="#f3f6fb", foreground="#20324a", font=("Microsoft YaHei UI", 10))
        style.configure("TCheckbutton", background="#f3f6fb", font=("Microsoft YaHei UI", 10))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 8))
        style.configure("Primary.TButton", background="#167f68", foreground="white")
        style.map("Primary.TButton", background=[("active", "#116653")])
        style.configure("TEntry", padding=7, font=("Microsoft YaHei UI", 11))
        body = ttk.Frame(root, padding=(30, 24))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="连上校园网，登录交给它。", font=("Microsoft YaHei UI", 21, "bold")).pack(anchor="w")
        ttk.Label(body, text="宿舍网线 + SUSE_Hostel / SUSE · 有线优先 · 在线时跳过登录", foreground="#5e7088").pack(anchor="w", pady=(7, 18))
        panel = tk.Frame(body, bg="white", padx=18, pady=14, highlightbackground="#dce5ed", highlightthickness=1)
        panel.pack(fill="x")
        self.network_text = tk.StringVar(value="等待检查网络")
        self.status_text = tk.StringVar(value="首次使用请填写自己的校园网账号、密码和运营商。")
        tk.Label(panel, textvariable=self.network_text, bg="white", fg="#167f68", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        tk.Label(panel, textvariable=self.status_text, bg="white", fg="#40536b", justify="left", wraplength=650,
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(7, 0))
        self.username = tk.StringVar(value=settings.username)
        self.password = tk.StringVar(value=settings.password)
        label = next((label for label, value in SERVICES.items() if value == settings.service), settings.service)
        self.service = tk.StringVar(value=label)
        self.service_choices = {label: settings.service}
        self.catalog_event = None
        self.service_hint = tk.StringVar(value="保留已保存的服务；发现学校认证要求后自动更新列表。")
        self.autostart = tk.BooleanVar(value=settings.autostart)
        self.notifications_enabled = tk.BooleanVar(value=settings.notifications_enabled)
        form = ttk.Frame(body)
        form.pack(fill="x", pady=(16, 0))
        form.columnconfigure(1, weight=1)
        for row, label in enumerate(("校园网账号", "校园网密码", "上网服务")):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 20), pady=7)
        ttk.Entry(form, textvariable=self.username).grid(row=0, column=1, sticky="ew", pady=7)
        password_row = ttk.Frame(form)
        password_row.grid(row=1, column=1, sticky="ew", pady=7)
        password_row.columnconfigure(0, weight=1)
        self.password_entry = ttk.Entry(password_row, textvariable=self.password, show="●")
        self.password_entry.grid(row=0, column=0, sticky="ew")
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(password_row, text="显示", variable=show,
                        command=lambda: self.password_entry.configure(show="" if show.get() else "●")).grid(row=0, column=1, padx=(10, 0))
        service_row = ttk.Frame(form)
        service_row.grid(row=2, column=1, sticky="ew", pady=7)
        service_row.columnconfigure(0, weight=1)
        self.service_box = ttk.Combobox(service_row, textvariable=self.service, values=list(self.service_choices),
                                        state="readonly", font=("Microsoft YaHei UI", 10), width=22)
        self.service_box.grid(row=0, column=0, sticky="ew", ipady=5)
        self.refresh_button = ttk.Button(service_row, text="刷新服务列表", command=self.refresh_services)
        self.refresh_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(form, textvariable=self.service_hint, wraplength=560, foreground="#5e7088").grid(
            row=3, column=1, sticky="w", pady=(0, 3))
        ttk.Checkbutton(body, text="开机自动运行（点击保存后生效）", variable=self.autostart).pack(anchor="w", pady=(12, 4))
        ttk.Checkbutton(body, text="显示系统通知（点击保存后生效）",
                        variable=self.notifications_enabled).pack(anchor="w", pady=(0, 4))
        ttk.Label(body, text="密码由 Windows 在本机保护；每位同学填写自己的账号。", foreground="#5e7088").pack(anchor="w")
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(16, 0))
        self.save_button = ttk.Button(actions, text="保存并测试", style="Primary.TButton", command=self.save)
        self.save_button.pack(side="left")
        ttk.Button(actions, text="立即检查", command=self.check_now).pack(side="left", padx=8)
        self.pause_button = ttk.Button(actions, text="暂停自动登录", command=self.toggle_pause)
        self.pause_button.pack(side="left")
        links = ttk.Frame(body)
        links.pack(fill="x", pady=(10, 0))
        ttk.Button(links, text="打开官方登录页", command=lambda: webbrowser.open(PORTAL_HOME)).pack(side="left")
        ttk.Button(links, text="打开记录文件夹", command=lambda: os.startfile(data_dir())).pack(side="left", padx=8)
        self.diagnose_button = ttk.Button(links, text="连接诊断", command=self.diagnose)
        self.diagnose_button.pack(side="left")
        ttk.Button(links, text="退出程序", command=self.exit).pack(side="right")
        ttk.Label(body, text="短时间断开再连接仍能上网时，无需重新登录。\n关闭窗口后继续在右下角小图标中运行；要停止请点击“退出程序”。",
                  foreground="#5e7088", justify="left").pack(anchor="w", pady=(18, 0))
        self.updated = tk.StringVar(value=f"版本 {__version__} · 每 15 秒检查一次")
        ttk.Label(body, textvariable=self.updated, foreground="#75849a", font=("Microsoft YaHei UI", 9)).pack(anchor="w", side="bottom", pady=(10, 0))

    def _start_tray(self):
        def send(action):
            return lambda *args: self.queue.put(action)
        self.icon = pystray.Icon("SUSECampusLogin", icon_image(), "校园网自动登录",
                                 pystray.Menu(
                                     pystray.MenuItem("打开设置", send("show"), default=True),
                                     pystray.MenuItem("立即检查", send("check")),
                                     pystray.MenuItem("暂停 / 恢复", send("pause")),
                                     pystray.MenuItem("退出程序", send("exit")),
                                 ))
        def setup(icon):
            try:
                icon.visible = True
                self.queue.put("tray_ready")
            except Exception:
                self.queue.put("tray_error")

        def run():
            try:
                self.icon.run(setup=setup)
            except Exception:
                self.queue.put("tray_error")
        threading.Thread(target=run, name="campus-tray", daemon=True).start()

    def _drain(self):
        if self.exiting:
            return
        try:
            while True:
                item = self.queue.get_nowait()
                if isinstance(item, Status):
                    self._status(item)
                elif isinstance(item, ServiceCatalogEvent):
                    self._show_services(item)
                elif isinstance(item, tuple) and item[0] == "diagnosis":
                    self._show_diagnosis(item[1])
                elif item == "show":
                    self.show()
                elif item == "check":
                    self.check_now()
                elif item == "pause":
                    self.toggle_pause()
                elif item == "exit":
                    self.exit()
                    return
                elif item == "tray_ready":
                    if self.icon is not None:
                        self.tray_ready = True
                        self.notifications.set_ready(True)
                elif item == "tray_error":
                    self.tray_ready = False
                    self.notifications.set_ready(False)
                    if self.icon is not None:
                        try:
                            self.icon.stop()
                        except Exception:
                            pass
                    self.icon = None
                    self.show()
                    self._status(Status("tray_error", "任务栏小图标未能启动，请保留本窗口运行；系统通知暂不可用。"))
        except queue.Empty:
            pass
        self.root.after(150, self._drain)

    def _status(self, status):
        if status.generation is not None and status.generation != self.engine.generation:
            return
        self.network_text.set(status.connection_label or "校园网助手")
        self.status_text.set(status.text)
        self.updated.set(f"最近检查 {datetime.datetime.now():%H:%M:%S} · 版本 {__version__} · 每 15 秒检查一次")
        if self.icon and status.code != self.last_status:
            self.icon.title = "校园网自动登录 · " + status.text[:60]
            self.icon.icon = icon_image("#24ad78" if status.code == "online" else "#dd9a34")
        self.last_status = status.code
        # Only fixed status codes are logged, never server responses or identifiers.
        if status.code != self.last_log:
            self.logger.info("state=%s", status.code)
            self.last_log = status.code
        if not self.ui_check:
            self.notifications.observe(status)

    def _send_notification(self, message, title):
        if self.ui_check or not self.tray_ready or self.icon is None or not self.icon.HAS_NOTIFICATION:
            return False
        self.icon.notify(message, title)
        return True

    def _remove_notification(self):
        if self.tray_ready and self.icon is not None:
            self.icon.remove_notification()

    def save(self):
        if self.ui_check:
            return
        username, password = self.username.get().strip(), self.password.get()
        if not username or not password:
            messagebox.showwarning("还差一点", "请填写校园网账号和密码，密码不需要发给任何人。")
            return
        if len(username) > 200 or len(password) > 1000:
            messagebox.showwarning("请检查输入", "账号或密码过长，请填写你平时在学校页面使用的登录信息。")
            return
        service = self.service_choices.get(self.service.get())
        event = self.catalog_event
        current = event is not None and self.engine.catalog_event_current(event) and event.outcome == "ready"
        allowed = {item.name for item in event.options if item.available} if current else set()
        if (not valid_service_name(service) or (current and service not in allowed)
                or (service != self.engine.settings.service and (not current or service not in allowed))):
            messagebox.showwarning("请确认上网服务", "请刷新学校服务列表，选择一个可自动使用的服务，再保存并测试。")
            return
        settings = Settings(username, password, service, self.autostart.get(),
                            self.notifications_enabled.get())
        try:
            self.store.save(settings)
        except (OSError, ValueError):
            messagebox.showerror("保存未成功", "无法在本机保护并保存密码，请检查用户文件夹权限后重试。")
            return
        try:
            set_autostart(settings.autostart)
        except OSError:
            messagebox.showwarning("开机启动未设置成功", "登录设置已保存，但开机启动设置失败。可以手动启动程序，或取消勾选后再次保存。")
        self.paused = False
        self.pause_button.configure(text="暂停自动登录")
        self.engine.set_paused(False)
        previous = self.engine.settings
        self.engine.update_settings(settings)
        credentials_changed = ((previous.username, previous.password, previous.service)
                               != (settings.username, settings.password, settings.service))
        self.notifications.configure(settings.notifications_enabled, self.engine.generation,
                                     credentials_changed=credentials_changed)
        self._status(Status("saved", "设置已保存，正在检查当前网络。密码不会写入运行记录。"))

    def refresh_services(self):
        if self.ui_check:
            return
        self.refresh_button.configure(text="正在刷新…", state="disabled")
        self.service_hint.set("只读取学校服务列表，不提交账号密码。")
        self.engine.request_services()

    def _show_services(self, event):
        if self.exiting or not self.engine.catalog_event_current(event):
            return
        self.refresh_button.configure(text="刷新服务列表", state="normal")
        self.service_hint.set(event.text)
        current_label = self.service.get()
        current_name = self.service_choices.get(current_label, current_label)
        self.catalog_event = event
        if event.outcome == "ready":
            self.service_choices = {item.name: item.name for item in event.options if item.available}
            # Keep the user's actual choice, including an unsaved or obsolete choice.
            self.service.set(current_name)
            if current_name not in self.service_choices:
                self.service_choices[current_name] = current_name
                self.service_hint.set("原选择已保留但当前不可用；请从最新列表重新选择后保存。")
            self.service_box.configure(values=[item.name for item in event.options if item.available])
            if not event.options:
                self.service_hint.set(event.text or "暂未取得可用服务，请刷新列表或打开官方登录页。")
            elif not any(item.available for item in event.options):
                self.service_hint.set("当前服务均无法自动使用，请打开官方登录页处理。原选择已保留。")
        elif event.outcome == "invalidated":
            self.service_choices = {current_label: current_name}
            self.service_box.configure(values=[current_label])

    def check_now(self):
        if self.paused:
            self.toggle_pause()
        self.engine.check_now()

    def diagnose(self):
        if self.ui_check:
            return
        self.diagnose_button.configure(state="disabled", text="诊断中…")

        def run():
            try:
                report = connection_report()
            except Exception:
                report = "只读诊断未完成，请稍后重试。"
            self.queue.put(("diagnosis", report))

        threading.Thread(target=run, name="campus-diagnosis", daemon=True).start()

    def _show_diagnosis(self, report):
        self.diagnose_button.configure(state="normal", text="连接诊断")
        window = tk.Toplevel(self.root)
        window.title("连接诊断 · 不提交账号密码")
        window.geometry("780x520")
        box = tk.Text(window, wrap="word", padx=18, pady=18, font=("Microsoft YaHei UI", 10))
        box.pack(fill="both", expand=True)
        box.insert("1.0", report)
        box.configure(state="disabled")

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(report)
            button.configure(text="已复制，可粘贴给维护者")

        button = ttk.Button(window, text="复制诊断结果", command=copy)
        button.pack(pady=10)

    def toggle_pause(self):
        self.paused = not self.paused
        self.engine.set_paused(self.paused)
        self.notifications.configure(self.engine.settings.notifications_enabled, self.engine.generation)
        self.pause_button.configure(text="恢复自动登录" if self.paused else "暂停自动登录")

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        if self.ui_check:
            self.exit()
        elif self.icon:
            self.root.withdraw()
        else:
            messagebox.showinfo("请保留窗口", "任务栏小图标未启动，请保留窗口或点击“退出程序”。")

    def exit(self):
        if self.exiting:
            return
        self.exiting = True
        self.engine.stop()
        self.notifications.close()
        if self.icon:
            self.icon.stop()
        self.root.destroy()

