"""Read-only Windows IP Helper APIs. No netsh commands or route changes."""

import ctypes as c
from ctypes import wintypes as w
import ipaddress
import socket
import uuid

from .models import NetworkConnection, NetworkSnapshot
from .windows import GUID, read_wifi_snapshot


class SocketAddress(c.Structure):
    _fields_ = [("address", c.c_void_p), ("length", c.c_int)]


class AddressNode(c.Structure):
    pass


AddressNode._fields_ = [("alignment", c.c_ulonglong), ("next", c.POINTER(AddressNode)),
                       ("socket", SocketAddress)]


class Adapter(c.Structure):
    pass


# IP_ADAPTER_ADDRESSES_LH prefix, including gateway/metric/LUID fields.
Adapter._fields_ = [
    ("length", w.ULONG), ("index", w.DWORD), ("next", c.POINTER(Adapter)),
    ("adapter_name", c.c_char_p), ("unicast", c.POINTER(AddressNode)),
    ("anycast", c.c_void_p), ("multicast", c.c_void_p), ("dns", c.c_void_p),
    ("dns_suffix", w.LPWSTR), ("description", w.LPWSTR), ("friendly_name", w.LPWSTR),
    ("physical_address", w.BYTE * 8), ("physical_address_length", w.DWORD),
    ("flags", w.DWORD), ("mtu", w.DWORD), ("if_type", w.DWORD),
    ("oper_status", w.DWORD), ("ipv6_index", w.DWORD), ("zones", w.DWORD * 16),
    ("prefix", c.c_void_p), ("transmit_speed", c.c_ulonglong), ("receive_speed", c.c_ulonglong),
    ("wins", c.c_void_p), ("gateway", c.POINTER(AddressNode)),
    ("ipv4_metric", w.ULONG), ("ipv6_metric", w.ULONG), ("luid", c.c_ulonglong),
]


class InterfaceRowPrefix(c.Structure):
    # MIB_IF_ROW2 prefix through InterfaceAndOperStatusFlags.
    _fields_ = [
        ("luid", c.c_ulonglong), ("index", w.ULONG), ("guid", GUID),
        ("alias", w.WCHAR * 257), ("description", w.WCHAR * 257),
        ("physical_length", w.ULONG), ("physical", w.BYTE * 32), ("permanent", w.BYTE * 32),
        ("mtu", w.ULONG), ("if_type", w.ULONG), ("tunnel_type", w.ULONG),
        ("media_type", w.ULONG), ("physical_medium", w.ULONG),
        ("access_type", w.ULONG), ("direction", w.ULONG), ("status_flags", w.BYTE),
    ]


def _ipv4_addresses(pointer):
    result = []
    for _ in range(256):
        if not pointer:
            break
        node = pointer.contents
        if node.socket.address and node.socket.length >= 16:
            family = c.cast(node.socket.address, c.POINTER(w.WORD))[0]
            if family == socket.AF_INET:
                value = socket.inet_ntoa(c.string_at(node.socket.address + 4, 4))
                address = ipaddress.IPv4Address(value)
                if not (address.is_unspecified or address.is_link_local or address.is_loopback):
                    result.append(value)
        pointer = node.next
    return result


def _physical_ethernet(api, index):
    # The API writes a whole MIB_IF_ROW2. Allocate more than its full size while
    # reading only the documented prefix; never pass a short prefix as output.
    buffer = c.create_string_buffer(4096)
    row = c.cast(buffer, c.POINTER(InterfaceRowPrefix)).contents
    row.index = index
    error = api.GetIfEntry2(buffer)
    if error:
        raise OSError(error, "无法识别有线网卡类型")
    return row.if_type == 6 and bool(row.status_flags & 1)  # HardwareInterface


def network_snapshot() -> NetworkSnapshot:
    api = c.WinDLL("iphlpapi", use_last_error=True)
    api.GetAdaptersAddresses.argtypes = [w.ULONG, w.ULONG, c.c_void_p, c.c_void_p, c.POINTER(w.ULONG)]
    api.GetAdaptersAddresses.restype = w.ULONG
    api.GetIfEntry2.argtypes = [c.c_void_p]
    api.GetIfEntry2.restype = w.ULONG
    size = w.ULONG(15000)
    for _ in range(3):
        buffer = c.create_string_buffer(size.value)
        # GAA_FLAG_INCLUDE_GATEWAYS, AF_INET: authentication uses IPv4.
        error = api.GetAdaptersAddresses(socket.AF_INET, 0x80, None, buffer, c.byref(size))
        if error != 111:  # ERROR_BUFFER_OVERFLOW
            break
    if error == 232:  # ERROR_NO_DATA
        return NetworkSnapshot()
    if error:
        raise OSError(error, "无法读取网络连接")
    entries = []
    pointer = c.cast(buffer, c.POINTER(Adapter))
    for _ in range(256):
        if not pointer:
            break
        adapter = pointer.contents
        if adapter.length < Adapter.luid.offset + c.sizeof(c.c_ulonglong):
            raise OSError("Windows 网卡信息格式不受支持")
        if adapter.oper_status == 1 and adapter.if_type in (6, 71):
            if adapter.if_type == 71 or _physical_ethernet(api, adapter.index):
                addresses, gateways = _ipv4_addresses(adapter.unicast), _ipv4_addresses(adapter.gateway)
                identity = (adapter.adapter_name or b"").decode("ascii", errors="replace").lower()
                entries.append((identity, adapter.index, adapter.if_type,
                                adapter.friendly_name or "网卡", addresses, gateways))
        pointer = adapter.next
    wireless, wifi_error = {}, False
    if any(entry[2] == 71 for entry in entries):
        try:
            read = read_wifi_snapshot()
            wifi_error = read.incomplete
            wireless = {"{" + str(uuid.UUID(bytes_le=bytes.fromhex(item.interface_id))) + "}": item
                        for item in read.connections}
        except OSError:
            wifi_error = True
    result = []
    for identity, index, if_type, name, addresses, gateways in entries:
        wifi = wireless.get(identity)
        if if_type == 71 and wifi is None:
            continue
        result.append(NetworkConnection(identity, index, "ethernet" if if_type == 6 else "wifi", name,
                                        addresses[0] if addresses else "", gateways[0] if gateways else "",
                                        wifi.ssid if wifi else "", wifi.bssid if wifi else ""))
    return NetworkSnapshot(tuple(sorted(result, key=lambda item: item.interface_index)), wifi_error)
