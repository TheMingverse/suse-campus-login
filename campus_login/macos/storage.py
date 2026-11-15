"""Settings contain a reference to a Keychain item, never a password."""
import json
import os
import uuid
from pathlib import Path
from ..models import Settings, valid_service_name
from . import BUNDLE_ID


def data_dir():
    path = Path.home() / 'Library/Application Support/SUSECampusLogin'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


class Keychain:
    def __init__(self, keychain=None):
        self.keychain = keychain

    def query(self, account):
        import Security as S
        q = {S.kSecClass: S.kSecClassGenericPassword, S.kSecAttrService: BUNDLE_ID,
             S.kSecAttrAccount: account}
        if self.keychain is not None:
            q[S.kSecUseKeychain] = self.keychain
        return q

    def put(self, account, password):
        import Security as S
        from Foundation import NSData
        raw = password.encode('utf-8')
        value = NSData.dataWithBytes_length_(raw, len(raw))
        q = self.query(account)
        status = S.SecItemUpdate(q, {S.kSecValueData: value})
        if status == S.errSecItemNotFound:
            status, _ = S.SecItemAdd(dict(q, **{} ) | {S.kSecValueData: value}, None)
        if status != S.errSecSuccess:
            raise OSError('无法将密码保存到钥匙串')

    def get(self, account):
        import Security as S
        q = self.query(account)
        q.update({S.kSecReturnData: True, S.kSecMatchLimit: S.kSecMatchLimitOne})
        status, value = S.SecItemCopyMatching(q, None)
        if status != S.errSecSuccess:
            raise OSError('无法从钥匙串读取密码，请重新填写')
        return bytes(value).decode('utf-8')

    def delete(self, account):
        import Security as S
        status = S.SecItemDelete(self.query(account))
        if status not in (S.errSecSuccess, S.errSecItemNotFound):
            raise OSError('无法删除钥匙串条目')


class SettingsStore:
    def __init__(self, directory=None, keychain=None):
        self.directory = Path(directory) if directory else data_dir()
        self.path = self.directory / 'settings.json'
        self.keychain = keychain if keychain is not None else Keychain()

    def load(self):
        if not self.path.exists():
            return Settings()
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.validate(data)
        return Settings(data['username'], self.keychain.get(data['password_ref']), data['service'],
                        data['autostart'], data['notifications_enabled'])

    @staticmethod
    def validate(data):
        if (not isinstance(data.get('username'), str) or len(data['username']) > 200
                or not valid_service_name(data.get('service'))
                or not isinstance(data.get('password_ref'), str)
                or not all(isinstance(data.get(k), bool) for k in ('autostart', 'notifications_enabled'))):
            raise ValueError('设置格式无效')

    def save(self, settings):
        ref = str(uuid.uuid4())
        data = dict(username=settings.username, service=settings.service, password_ref=ref,
                    autostart=settings.autostart, notifications_enabled=settings.notifications_enabled)
        self.validate(data)
        previous = None
        if self.path.exists():
            previous = json.loads(self.path.read_text(encoding='utf-8')).get('password_ref')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.keychain.put(ref, settings.password)
        temporary = self.path.with_suffix('.tmp')
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temporary.replace(self.path)
        except Exception:
            self.keychain.delete(ref)
            raise
        if previous:
            try:
                self.keychain.delete(previous)
            except OSError:
                pass  # A stale item must not invalidate the successfully committed settings.
