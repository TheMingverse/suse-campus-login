"""Only the confirmed campus host can receive authentication requests."""

import json
import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import quote, urljoin, urlsplit

import requests

from .models import PORTAL_HOST, PortalError, Settings, ServiceOption, valid_service_name


def parse_services(data):
    try:
        items = data["serviceJson"]
        if isinstance(items, str):
            items = json.loads(items)
        if not isinstance(items, list) or not items:
            raise ValueError()
        grouped = {}
        for item in items:
            if not isinstance(item, dict) or not valid_service_name(item.get("serviceName")):
                raise ValueError()
            name = item["serviceName"]
            # Compare all configuration fields, not just the display name.
            signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
            hidden = str(item.get("aceNotShow", "false")).lower()
            extra = str(item.get("domainName", "false")).lower()
            available = hidden == "false" and extra == "false"
            reason = "" if available else "需要官方页面处理"
            if name in grouped and grouped[name][0] != signature:
                available, reason = False, "同名服务配置存在冲突"
                signature = None
            grouped[name] = (signature, ServiceOption(name, available, reason))
        return tuple(option for _, option in grouped.values())
    except (KeyError, ValueError, TypeError):
        raise PortalError("service_required", "学校服务列表为空或格式无法识别，请刷新服务列表或打开官方页面。") from None


@dataclass
class PreparedLogin:
    owner: object = field(repr=False)
    portal_url: str = field(repr=False)
    info: dict = field(repr=False)
    services: tuple[ServiceOption, ...]
    used: bool = False


def require_service(options, name):
    matches = [item for item in options if item.name == name]
    if len(matches) != 1 or not matches[0].available:
        raise PortalError("service_required", "原上网服务不存在或无法自动使用，请从学校最新列表重新选择并保存。")
    return matches[0]


def component(value: str) -> str:
    # JavaScript encodeURIComponent, including its treatment of !'()*.
    return quote(value, safe="~()*!.'-_")


def form(fields: dict[str, str], double: bool = False) -> bytes:
    def encode(value):
        return component(component(value)) if double else component(value)
    return "&".join(f"{key}={encode(value)}" for key, value in fields.items()).encode("ascii")


def trusted_portal(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "http" and parts.hostname == PORTAL_HOST
            and parts.port in (None, 80, 8080) and not parts.username
            and not parts.password and parts.path.lower() == "/eportal/index.jsp"
        )
    except ValueError:
        return False


def connection_query(url: str) -> str:
    if not trusted_portal(url):
        raise PortalError("manual", "登录页面地址与已确认的校园网不一致，请打开官方页面处理。")
    query = urlsplit(url).query
    # Keep the raw query intact: it contains opaque values, not reusable settings.
    required = ("wlanuserip", "wlanacname", "mac")
    if len(query) > 16000 or any(not re.search(r"(?:^|&)" + key + r"=[^&]+", query) for key in required):
        raise PortalError("manual", "没有获取到本次连接的完整认证参数，请打开官方页面重试。")
    return query


def rsa_password(password: str, mac: str, exponent: str, modulus: str) -> str:
    """Match security.js: reversed UTF-16 units, 16-bit limbs, raw RSA blocks.

    This is the school's legacy wire format, not PKCS#1/OAEP encryption.
    """
    try:
        e, n = int(exponent, 16), int(modulus, 16)
    except (ValueError, TypeError):
        raise PortalError("manual", "学校页面的密码加密配置无效，请使用官方页面。") from None
    if n.bit_length() < 512 or n.bit_length() > 4096 or not 1 < e < n:
        raise PortalError("manual", "学校页面的密码加密配置发生变化，请使用官方页面。")
    chunk = 2 * ((n.bit_length() - 1) // 16)
    raw = (password + ">" + mac).encode("utf-16-le", errors="surrogatepass")
    units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)][::-1]
    units += [0] * (-len(units) % chunk)
    def legacy_multiply(x, y):
        # security.js uses JS >>> 16 for carry (32-bit truncation), even
        # when non-Latin UTF-16 units overflow a nominal 16-bit limb.
        # Preserve that behavior instead of silently changing Unicode passwords.
        while len(x) > 1 and x[-1] == 0:
            x.pop()
        while len(y) > 1 and y[-1] == 0:
            y.pop()
        product = [0] * (len(x) + len(y))
        for i, b in enumerate(y):
            carry = 0
            for j, a in enumerate(x):
                value = product[i + j] + a * b + carry
                product[i + j] = value & 0xffff
                carry = (value & 0xffffffff) >> 16
            product[i + len(x)] = carry
        return sum(value << (16 * i) for i, value in enumerate(product))

    result = []
    for offset in range(0, len(units), chunk):
        digits = [units[offset + i] + (units[offset + i + 1] << 8) for i in range(0, chunk, 2)]
        initial = legacy_multiply([1], digits.copy()) % n if e & 1 else 1
        squared = legacy_multiply(digits.copy(), digits.copy()) % n
        encrypted = format(initial * pow(squared, e >> 1, n) % n, "x")
        result.append(encrypted.zfill((len(encrypted) + 3) // 4 * 4))
    return " ".join(result)


def login_fields(settings: Settings, query: str, info: dict) -> dict[str, str]:
    if info.get("validCodeUrl") or str(info.get("isCheckSmsAuth", "false")).lower() == "true":
        raise PortalError("manual", "学校现在要求验证码或短信验证，请打开官方页面完成登录。")
    if str(info.get("isToCasPage", "false")).lower() == "true":
        raise PortalError("manual", "学校要求跳转其他认证方式，请打开官方页面。")
    if info.get("prefixValue"):
        raise PortalError("manual", "学校启用了新的账号前缀规则，请使用官方页面。")
    encrypted = str(info.get("passwordEncrypt", "false")).lower() == "true"
    match = re.search(r"(?:^|&)mac=([^&]+)", query)
    password = settings.password
    if encrypted:
        password = rsa_password(password, match[1] if match else "111111111",
                                info.get("publicKeyExponent", ""), info.get("publicKeyModulus", ""))
    return {
        "userId": settings.username.strip(), "password": password,
        "service": settings.service, "queryString": query,
        "operatorPwd": "", "operatorUserId": "", "validcode": "",
        "passwordEncrypt": "true" if encrypted else "false",
    }


def classify_login(data: dict) -> str:
    message = unescape(re.sub(r"<[^>]*>", "", str(data.get("message", ""))))
    if data.get("result") == "success":
        if "PWD_COMPLEX_OFFLINE_WEB" in message:
            raise PortalError("manual", "学校提示密码强度不足，可能稍后断网，请到官方页面修改密码。")
        return "success"
    # Do not display/log raw server messages: they may echo account details.
    if re.search(r"验证码|短信|captcha|valid.?code|verify.?code", message, re.I):
        raise PortalError("manual", "学校要求验证码，请打开官方页面完成登录。")
    if re.search(r"密码|口令|用户不存在|账号不存在|帐号不存在|认证失败|password|credential|user.*not.*exist", message, re.I):
        raise PortalError("credentials", "账号或密码未通过认证，已停止自动尝试；请检查设置后保存并测试。")
    if re.search(r"欠费|停机|冻结|禁用|到期|过期|在线.*(数|上限)|终端.*(数|上限)|已.*在线|already.*online|limit", message, re.I):
        raise PortalError("manual", "学校限制了当前账号或设备的上网状态，请到官方页面查看详情。")
    if re.search(r"超时|繁忙|稍后|timeout|busy|暂时|服务器.*(失败|异常|错误)", message, re.I):
        raise PortalError("temporary", "校园网认证服务暂时不可用，稍后重试。")
    raise PortalError("manual", "学校未接受本次登录，已暂停自动尝试；请打开官方页面查看原因。")


class PortalClient:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.trust_env = False
        self._preparation = None

    def close(self):
        self._preparation = None
        self.session.close()

    def _post(self, url: str, body: bytes, guard):
        guard()
        try:
            response = self.session.post(url, data=body, timeout=(4, 6), allow_redirects=False,
                                         headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
            guard()
            response.raise_for_status()
            if response.is_redirect or len(response.content) > 200000:
                raise ValueError()
            data = json.loads(response.content.decode("utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except requests.RequestException:
            guard()
            raise PortalError("temporary", "暂时无法连接校园网认证服务器，稍后重试。") from None
        except (ValueError, UnicodeError):
            raise PortalError("manual", "学校认证页面返回了无法识别的信息，请打开官方页面。") from None

    def prepare(self, portal_url: str, guard=lambda: None):
        self._preparation = None
        query = connection_query(portal_url)
        base = urljoin(portal_url, "InterFace.do")
        info = self._post(base + "?method=pageInfo", form({"queryString": query}), guard)
        services = self._post(base + "?method=getServices&queryString=" + component(query), b"", guard)
        prepared = PreparedLogin(self, portal_url, info, parse_services(services))
        self._preparation = prepared
        return prepared

    def authenticate(self, portal_url: str, settings: Settings, guard=lambda: None, *, prepared=None):
        query = connection_query(portal_url)
        base = urljoin(portal_url, "InterFace.do")
        guard()
        prepared = prepared if prepared is not None else self.prepare(portal_url, guard)
        if (prepared is not self._preparation or prepared.owner is not self
                or prepared.portal_url != portal_url or prepared.used):
            raise PortalError("manual", "认证准备信息已失效，请重新检查当前连接。")
        prepared.used = True
        self._preparation = None
        require_service(prepared.services, settings.service)
        fields = login_fields(settings, query, prepared.info)
        data = self._post(base + "?method=login", form(fields, double=True), guard)
        return classify_login(data)
