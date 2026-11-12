from dataclasses import dataclass, field
from enum import Enum
import ipaddress
import unicodedata

ALLOWED_SSIDS = frozenset({"SUSE_Hostel", "SUSE"})
PORTAL_HOST = "10.23.2.4"
PORTAL_HOME = f"http://{PORTAL_HOST}/eportal/index.jsp"
SERVICES = {
    "宜宾移动校园宽带": "宜宾移动",
    "宜宾电信校园宽带": "宜宾电信",
    "宜宾联通校园宽带": "宜宾联通",
    "校园内网（仅校内资源）": "校园网",
}


def valid_service_name(value):
    return (isinstance(value, str) and 0 < len(value) <= 200 and bool(value.strip())
            and not any(unicodedata.category(ch).startswith("C") for ch in value))


@dataclass(frozen=True)
class ServiceOption:
    name: str
    available: bool = True
    reason: str = ""


@dataclass(frozen=True)
class ServiceCatalogEvent:
    generation: int
    request_id: int
    snapshot: "NetworkSnapshot | None" = field(repr=False)
    connection: "NetworkConnection | None" = field(default=None, repr=False)
    options: tuple[ServiceOption, ...] = ()
    outcome: str = "ready"
    text: str = ""


@dataclass(frozen=True)
class Settings:
    username: str = ""
    password: str = field(default="", repr=False)
    service: str = "宜宾移动"
    autostart: bool = True
    notifications_enabled: bool = True


@dataclass(frozen=True)
class NetworkConnection:
    interface_id: str
    interface_index: int
    kind: str
    name: str
    ipv4: str = field(default="", repr=False)
    gateway: str = field(default="", repr=False)
    ssid: str = ""
    bssid: str = field(default="", repr=False)

    @property
    def label(self):
        return f"已连接网线 · {self.name}" if self.kind == "ethernet" else f"校园 Wi-Fi · {self.ssid}"

    @property
    def eligible(self):
        return self.kind == "ethernet" or (self.kind == "wifi" and self.ssid in ALLOWED_SSIDS)

    @property
    def ready(self):
        try:
            address = ipaddress.IPv4Address(self.ipv4)
            gateway = ipaddress.IPv4Address(self.gateway)
            return (self.interface_index > 0 and not address.is_unspecified
                    and not address.is_link_local and not address.is_loopback
                    and not gateway.is_unspecified and not gateway.is_loopback)
        except ipaddress.AddressValueError:
            return False


@dataclass(frozen=True)
class NetworkSnapshot:
    connections: tuple[NetworkConnection, ...] = ()
    wifi_unavailable: bool = False

    @property
    def candidates(self):
        return tuple(sorted((item for item in self.connections if item.eligible and item.ready),
                            key=lambda item: (item.kind != "ethernet", item.interface_index)))


# Retained for the small WLAN-specific reader; the engine uses NetworkConnection.
@dataclass(frozen=True)
class WifiConnection:
    interface_id: str
    ssid: str
    bssid: str


@dataclass(frozen=True)
class WifiReadResult:
    connections: tuple[WifiConnection, ...] = ()
    incomplete: bool = False


class ProbeState(Enum):
    ONLINE = "online"
    PORTAL = "portal"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProbeResult:
    state: ProbeState
    portal_url: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Status:
    code: str
    text: str
    connection_label: str = ""
    notice_kind: str = ""
    notice_id: int = 0
    connection_key: str = field(default="", repr=False)
    generation: int | None = None


class Cancelled(Exception):
    """Network, settings, or pause state changed during an operation."""


class PortalError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind

