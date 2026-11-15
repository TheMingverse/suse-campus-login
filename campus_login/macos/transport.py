"""Darwin interface binding, with no fallback to an unbound connection."""
import socket
import requests
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager
from urllib3.connection import HTTPConnection
from urllib3.connectionpool import HTTPConnectionPool

from ..transport import connect_ipv4, InterfaceHTTPConnection
from ..network import NetworkProbe
from ..portal import PortalClient

# <netinet/in.h>, native int (unlike Windows IP_UNICAST_IF's network byte order).
IP_BOUND_IF = 25


class BoundConnection(InterfaceHTTPConnection):
    pass


class BoundPool(HTTPConnectionPool):
    ConnectionCls = BoundConnection


class BoundAdapter(HTTPAdapter):
    def __init__(self, connection):
        if not connection.ready:
            raise ValueError('连接地址尚未就绪')
        self.connection = connection
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        options = list(HTTPConnection.default_socket_options)
        options.append((socket.IPPROTO_IP, IP_BOUND_IF, self.connection.interface_index))
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block,
                                      source_address=(self.connection.ipv4, 0), socket_options=options)
        self.poolmanager.pool_classes_by_scheme = {'http': BoundPool}


class NetworkContext:
    def __init__(self, connection):
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.adapters.clear()
        self.session.mount('http://', BoundAdapter(connection))
        self.probe, self.portal = NetworkProbe(self.session), PortalClient(self.session)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()
