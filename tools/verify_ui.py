"""Show an empty sample UI, capture only its window, never load user settings."""
import ctypes
import os
from pathlib import Path
import sys
import tkinter as tk

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LOCALAPPDATA"] = str(ROOT / "build" / "ui-qa")
ctypes.windll.shcore.SetProcessDpiAwareness(1)

from campus_login.gui import Application
from campus_login.models import ServiceCatalogEvent, ServiceOption

root = tk.Tk()
root.withdraw()
app = Application(root, ui_check=True)
root.deiconify()


def capture():
    root.update_idletasks()
    left, top = root.winfo_rootx(), root.winfo_rooty()
    width, height = root.winfo_width(), root.winfo_height()

    def check(widget):
        if widget.winfo_ismapped():
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            assert left <= x and top <= y, "Widget outside window"
            assert x + widget.winfo_width() <= left + width, f"Widget clipped horizontally: {widget} {x=} width={widget.winfo_width()} bound={left + width}"
            assert y + widget.winfo_height() <= top + height, f"Widget clipped vertically: {widget} {y=} height={widget.winfo_height()} bound={top + height}"
        for child in widget.winfo_children():
            check(child)

    check(root)
    # Capture the actual window, even if another app covers it while the user works.
    ImageGrab.grab(window=root.winfo_id()).save(ROOT / "docs" / "settings-window.png")
    print(f"Sample window verified: {width}x{height}")
    if "--service-cases" in sys.argv:
        directory = ROOT / "build" / "service-ui-qa"
        directory.mkdir(parents=True, exist_ok=True)
        long_name = "长服务名称布局验证" * 20
        cases = [("long-name", (ServiceOption(long_name), ServiceOption("另一服务")), long_name),
                 ("missing", (ServiceOption("新套餐A"), ServiceOption("新套餐B")), "宜宾移动"),
                 ("unavailable", (ServiceOption("额外认证", False, "需人工处理"),), "宜宾移动"),
                 ("empty", (), "宜宾移动")]
        for name, options, selected in cases:
            app.service_choices = {selected: selected}
            app.service.set(selected)
            app._show_services(ServiceCatalogEvent(app.engine.generation, app.engine.catalog_sequence,
                                                   app.engine.snapshot, options=options,
                                                   text="学校服务列表为空或格式无法识别，请刷新服务列表或打开官方页面。"
                                                   if not options else "学校服务列表已更新，选择后点击保存并测试。"))
            root.update_idletasks()
            check(root)
            ImageGrab.grab(window=root.winfo_id()).save(directory / f"{name}.png")
        root.geometry(f"{root.minsize()[0]}x{root.minsize()[1]}")
        root.update()
        # Recompute bounds for the minimum permitted window size.
        width, height = root.winfo_width(), root.winfo_height()
        left, top = root.winfo_rootx(), root.winfo_rooty()
        check(root)
        ImageGrab.grab(window=root.winfo_id()).save(directory / "minimum-window.png")
        print(f"Synthetic service layouts verified: {len(cases) + 1}; no network or personal settings")
    root.after(100, app.exit)


def checked_capture():
    try:
        capture()
    except Exception:
        app.exit()
        raise


failed = []
def callback_error(kind, value, traceback):
    failed.append(value)
    sys.__excepthook__(kind, value, traceback)
root.report_callback_exception = callback_error
root.after(1000, checked_capture)
root.mainloop()
if failed:
    raise SystemExit(1)
