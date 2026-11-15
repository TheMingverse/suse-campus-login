import json
import platform
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import replace
import uuid

from campus_login.models import Settings, NetworkConnection, NetworkSnapshot
from campus_login.macos.network import snapshot_from_records
from campus_login.macos.storage import SettingsStore


class MemoryKeychain:
    def __init__(self): self.items = {}
    def put(self, account, password): self.items[account] = password
    def get(self, account): return self.items[account]
    def delete(self, account): self.items.pop(account, None)


class MacLogicTests(unittest.TestCase):
    def test_physical_selection_permission_failure_and_wired_priority(self):
        common=dict(active=True,address='10.0.0.2',router='10.0.0.1',name='test')
        snapshot=snapshot_from_records([
            dict(common,kind='wifi',interface='en0',index=1,ssid=None),
            dict(common,kind='ethernet',interface='en1',index=2),
            dict(common,kind='vpn',interface='utun0',index=3),
        ])
        self.assertTrue(snapshot.wifi_unavailable)
        self.assertEqual([c.interface_id for c in snapshot.candidates], ['en1'])
        self.assertEqual(len(snapshot.connections),2)

    def test_campus_names_missing_address_and_disconnection(self):
        base=dict(active=True,address='10.0.0.2',router='10.0.0.1',name='test',kind='wifi',interface='en0',index=1)
        for ssid,expected in [('SUSE',1),('SUSE_Hostel',1),('Home',0),('',0)]:
            self.assertEqual(len(snapshot_from_records([dict(base,ssid=ssid)]).candidates),expected)
        self.assertFalse(snapshot_from_records([dict(base,ssid='SUSE',address='')]).candidates)
        self.assertFalse(snapshot_from_records([dict(base,ssid='SUSE',active=False)]).connections)

    def test_password_reference_atomic_save_and_new_names(self):
        with tempfile.TemporaryDirectory() as temp:
            keychain=MemoryKeychain()
            store=SettingsStore(temp,keychain)
            settings=Settings('synthetic','test-password','新服务+&汉字',False,False)
            store.save(settings)
            self.assertEqual(store.load(),settings)
            self.assertNotIn(settings.password,store.path.read_text())
            store.save(replace(settings,password='replacement'))
            self.assertEqual(len(keychain.items),1)
            with patch.object(Path,'replace',side_effect=OSError('synthetic')):
                with self.assertRaises(OSError): store.save(settings)
            self.assertEqual(store.load().password,'replacement')
            self.assertEqual(len(keychain.items),1)
            self.assertEqual(store.path.stat().st_mode & 0o777,0o600)

    def test_invalid_service_rejected_before_keychain_write(self):
        with tempfile.TemporaryDirectory() as temp:
            keychain=MemoryKeychain()
            store=SettingsStore(temp,keychain)
            for service in ['', ' ', 'bad\n', 'a'*201]:
                with self.assertRaises(ValueError): store.save(Settings('s','p',service))
            self.assertFalse(keychain.items)


@unittest.skipUnless(platform.system()=='Darwin','macOS native integration')
class MacIntegrationTests(unittest.TestCase):
    def test_framework_snapshot_has_stable_shape(self):
        from campus_login.macos.network import network_snapshot
        self.assertIsInstance(network_snapshot(),NetworkSnapshot)

    def test_darwin_bound_http_and_no_unbound_fallback(self):
        from campus_login.macos.transport import BoundConnection, BoundAdapter, IP_BOUND_IF
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'synthetic-ok')
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            index=socket.if_nametoindex('lo0')
            conn=BoundConnection('127.0.0.1',server.server_port,timeout=3,source_address=('127.0.0.1',0),
                                 socket_options=[(socket.IPPROTO_IP,IP_BOUND_IF,index)])
            conn.connect()
            self.assertEqual(conn.sock.getsockopt(socket.IPPROTO_IP,IP_BOUND_IF),index)
            conn.request('GET','/')
            self.assertEqual(conn.getresponse().data,b'synthetic-ok');conn.close()
            bad=BoundConnection('127.0.0.1',server.server_port,timeout=1,source_address=('127.0.0.1',0),
                                socket_options=[(socket.IPPROTO_IP,IP_BOUND_IF,999999)])
            with self.assertRaises(Exception): bad.connect()
            c=NetworkConnection('en0',index,'ethernet','synthetic','10.1.1.2','10.1.1.1')
            adapter=BoundAdapter(c)
            self.assertEqual(adapter.poolmanager.connection_pool_kw['source_address'],('10.1.1.2',0))
            adapter.close()
            from types import SimpleNamespace
            import requests
            session=requests.Session();session.trust_env=False;session.adapters.clear()
            session.mount('http://',BoundAdapter(SimpleNamespace(ready=True,ipv4='127.0.0.1',interface_index=index)))
            try:
                response=session.get(f'http://127.0.0.1:{server.server_port}/',timeout=3)
                self.assertEqual(response.content,b'synthetic-ok')
            finally:
                session.close()
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_native_keychain_with_temporary_keychain(self):
        import Security as S
        from campus_login.macos.storage import Keychain
        with tempfile.TemporaryDirectory() as temp:
            password=b'synthetic-keychain-password'
            status,keychain=S.SecKeychainCreate(str(Path(temp)/'test.keychain').encode(),len(password),password,False,None,None)
            self.assertEqual(status,0)
            try:
                store=Keychain(keychain)
                ref=str(uuid.uuid4())
                store.put(ref,'test-only+汉字')
                self.assertEqual(store.get(ref),'test-only+汉字')
                store.put(ref,'changed')
                self.assertEqual(store.get(ref),'changed')
                store.delete(ref)
                with self.assertRaises(OSError): store.get(ref)
            finally:
                S.SecKeychainDelete(keychain)

    def test_single_instance_lock_and_release(self):
        from campus_login.macos import system
        with tempfile.TemporaryDirectory() as temp, patch.object(system,'data_dir',return_value=Path(temp)):
            first=system.acquire_instance();self.assertIsNotNone(first)
            self.assertIsNone(system.acquire_instance())
            first.close()
            second=system.acquire_instance();self.assertIsNotNone(second);second.close()


if __name__=='__main__': unittest.main()
