"""IPv4 sockets pinned to a Windows interface AND its current source address."""

import socket
import struct

import requests
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager
from urllib3.connection import HTTPConnection
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError

from .models import NetworkConnection

IP_UNICAST_IF = 31


def connect_ipv4(host, port, timeout, source_address, socket_options):
    last_error = None
    for family, kind, proto, _, destination in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            for level, option, value in socket_options:
                sock.setsockopt(level, option, value)
            sock.bind(source_address)
            sock.connect(destination)
            return sock
        except OSError as error:
            last_error = error
            sock.close()
    if last_error:
        raise last_error
    raise OSError("没有可用的 IPv4 目标地址")


class InterfaceHTTPConnection(HTTPConnection):
    def _new_conn(self):
        try:
            return connect_ipv4(self._dns_host, self.port, self.timeout,
                                self.source_address, self.socket_options)
        except socket.gaierror as error:
            raise NameResolutionError(self.host, self, error) from error
        except socket.timeout as error:
            raise ConnectTimeoutError(self, "指定网卡连接超时") from error
        except OSError as error:
            raise NewConnectionError(self, "无法通过指定网卡建立连接") from error


class InterfaceHTTPPool(HTTPConnectionPool):
    ConnectionCls = InterfaceHTTPConnection


class InterfaceAdapter(HTTPAdapter):
    def __init__(self, connection: NetworkConnection):
        if not connection.ready:
            raise ValueError("网卡尚未取得有效 IPv4 地址和网关")
        self.connection = connection
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        options = list(HTTPConnection.default_socket_options)
        options.append((socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", self.connection.interface_index)))
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block,
                                       source_address=(self.connection.ipv4, 0), socket_options=options)
        # Never mutate urllib3's shared global pool class mapping.
        self.poolmanager.pool_classes_by_scheme = {"http": InterfaceHTTPPool}


def interface_session(connection):
    session = requests.Session()
    session.trust_env = False
    # This project uses HTTP probes and the confirmed school's HTTP portal only.
    # Unsupported schemes must fail rather than silently use an unbound adapter.
    session.adapters.clear()
    session.mount("http://", InterfaceAdapter(connection))
    return session


class NetworkContext:
    def __init__(self, connection):
        from .network import NetworkProbe
        from .portal import PortalClient
        self.session = interface_session(connection)
        self.probe = NetworkProbe(self.session)
        self.portal = PortalClient(self.session)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()
