"""Small wrappers around Windows WLAN, DPAPI, and per-user startup APIs."""

import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import sys

from .models import WifiConnection, WifiReadResult


class GUID(c.Structure):
    _fields_ = [("data1", w.DWORD), ("data2", w.WORD), ("data3", w.WORD), ("data4", w.BYTE * 8)]


class Interface(c.Structure):
    _fields_ = [("guid", GUID), ("description", w.WCHAR * 256), ("state", w.DWORD)]


class SSID(c.Structure):
    _fields_ = [("length", w.ULONG), ("value", w.BYTE * 32)]


class Association(c.Structure):
    _fields_ = [("ssid", SSID), ("bss_type", w.DWORD), ("bssid", w.BYTE * 6),
                ("phy_type", w.DWORD), ("phy_index", w.DWORD), ("quality", w.ULONG),
                ("rx_rate", w.ULONG), ("tx_rate", w.ULONG)]


class Connection(c.Structure):
    _fields_ = [("state", w.DWORD), ("mode", w.DWORD), ("profile", w.WCHAR * 256),
                ("association", Association), ("security", w.DWORD * 4)]


class Blob(c.Structure):
    _fields_ = [("size", w.DWORD), ("data", c.POINTER(c.c_ubyte))]


def read_wifi_snapshot() -> WifiReadResult:
    """Keep readable interfaces when another interface fails or disappears."""
    wlan = c.WinDLL("wlanapi", use_last_error=True)
    wlan.WlanOpenHandle.argtypes = [w.DWORD, c.c_void_p, c.POINTER(w.DWORD), c.POINTER(w.HANDLE)]
    wlan.WlanOpenHandle.restype = w.DWORD
    wlan.WlanEnumInterfaces.argtypes = [w.HANDLE, c.c_void_p, c.POINTER(c.c_void_p)]
    wlan.WlanEnumInterfaces.restype = w.DWORD
    wlan.WlanQueryInterface.argtypes = [w.HANDLE, c.POINTER(GUID), w.DWORD, c.c_void_p,
                                       c.POINTER(w.DWORD), c.POINTER(c.c_void_p), c.POINTER(w.DWORD)]
    wlan.WlanQueryInterface.restype = w.DWORD
    wlan.WlanFreeMemory.argtypes = [c.c_void_p]
    wlan.WlanCloseHandle.argtypes = [w.HANDLE, c.c_void_p]
    handle, version = w.HANDLE(), w.DWORD()
    error = wlan.WlanOpenHandle(2, None, c.byref(version), c.byref(handle))
    if error:
        raise OSError(error, "无法读取无线网络状态")
    interfaces = c.c_void_p()
    try:
        error = wlan.WlanEnumInterfaces(handle, None, c.byref(interfaces))
        if error:
            raise OSError(error, "无法读取无线网络状态")
        if not interfaces:
            raise OSError("无线接口列表为空指针")
        count = c.cast(interfaces, c.POINTER(w.DWORD))[0]
        found = []
        incomplete = count > 32
        for i in range(min(count, 32)):
            item = Interface.from_address(interfaces.value + 8 + i * c.sizeof(Interface))
            if item.state != 1:  # wlan_interface_state_connected
                continue
            size, value, opcode_type = w.DWORD(), c.c_void_p(), w.DWORD()
            try:
                error = wlan.WlanQueryInterface(handle, c.byref(item.guid), 7, None,
                                                c.byref(size), c.byref(value), c.byref(opcode_type))
                if error or not value or size.value < c.sizeof(Connection):
                    incomplete = True
                    continue
                info = c.cast(value, c.POINTER(Connection)).contents
                length = info.association.ssid.length
                if info.state != 1 or not 1 <= length <= 32:
                    incomplete = True
                    continue
                name = bytes(info.association.ssid.value[:length]).decode("utf-8")
                found.append(WifiConnection(bytes(item.guid).hex(), name, bytes(info.association.bssid).hex()))
            except (OSError, UnicodeDecodeError):
                incomplete = True
            finally:
                if value:
                    wlan.WlanFreeMemory(value)
        return WifiReadResult(tuple(found), incomplete)
    finally:
        if interfaces:
            wlan.WlanFreeMemory(interfaces)
        wlan.WlanCloseHandle(handle, None)


def connected_wifi() -> tuple[WifiConnection, ...]:
    """Compatibility entry point; detailed callers use read_wifi_snapshot."""
    return read_wifi_snapshot().connections


def current_wifi() -> WifiConnection | None:
    found = connected_wifi()
    if len(found) > 1:
        raise OSError("检测到多个已连接的无线网卡")
    return found[0] if found else None


def protect(data: bytes, decrypt=False) -> bytes:
    crypt = c.WinDLL("crypt32", use_last_error=True)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [c.c_void_p]
    kernel.LocalFree.restype = c.c_void_p
    buffer = c.create_string_buffer(data)
    source = Blob(len(data), c.cast(buffer, c.POINTER(c.c_ubyte)))
    output = Blob()
    # UI_FORBIDDEN; DPAPI defaults to this Windows user's protection scope.
    if decrypt:
        fn = crypt.CryptUnprotectData
    else:
        fn = crypt.CryptProtectData
    fn.argtypes = [c.POINTER(Blob), c.c_void_p, c.c_void_p, c.c_void_p,
                   c.c_void_p, w.DWORD, c.POINTER(Blob)]
    fn.restype = w.BOOL
    if not fn(c.byref(source), None, None, None, None, 1, c.byref(output)):
        raise OSError(c.get_last_error(), "无法读取或保护本机密码，请重新填写并保存")
    try:
        return c.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def set_autostart(enabled: bool):
    import winreg
    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        if enabled:
            if getattr(sys, "frozen", False):
                args = [sys.executable, "--background"]
            else:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                args = [str(pythonw), str(Path(__file__).resolve().parents[1] / "main.py"), "--background"]
            winreg.SetValueEx(key, "SUSECampusLogin", 0, winreg.REG_SZ, subprocess.list2cmdline(args))
        else:
            try:
                winreg.DeleteValue(key, "SUSECampusLogin")
            except FileNotFoundError:
                pass


def acquire_instance():
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
    kernel.CreateMutexW.restype = w.HANDLE
    handle = kernel.CreateMutexW(None, False, "Local\\SUSECampusLogin-1")
    if not handle:
        raise OSError(c.get_last_error(), "无法创建程序实例")
    if c.get_last_error() == 183:
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle(handle)
        return None
    return handle

