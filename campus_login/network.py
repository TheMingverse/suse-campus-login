import re
from html import unescape
from urllib.parse import urljoin, urlsplit

import requests

from .models import ProbeResult, ProbeState, PortalError, PORTAL_HOST
from .portal import trusted_portal, connection_query

# Distinct services reduce false failures if one public detector is unavailable.
PROBES = (
    ("http://www.msftconnecttest.com/connecttest.txt", b"Microsoft Connect Test"),
    ("http://detectportal.firefox.com/success.txt", b"success"),
)


def portal_from_response(response, require_parameters=True) -> str | None:
    candidates = [response.headers.get("Location", ""), response.headers.get("Refresh", "")]
    text = response.content.decode("utf-8", errors="replace")
    # Only extract redirects. A link or mention in an unrelated page is insufficient.
    patterns = [
        r'''(?:window\.|top\.|self\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']''',
        r'''location\.replace\(\s*["']([^"']+)["']''',
        r'''<meta\b[^>]*http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*["'][^"']*?url\s*=\s*([^"'>]+)''',
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text, re.I))
    for candidate in candidates:
        if "url=" in candidate.lower() and candidate.lower().startswith(("0;", "0 ;")):
            candidate = re.split(r"url\s*=", candidate, flags=re.I, maxsplit=1)[-1]
        url = urljoin(response.url, unescape(candidate.strip(" \t\r\n\"'")))
        if trusted_portal(url):
            if not require_parameters:
                return url
            try:
                connection_query(url)
                return url
            except PortalError:
                continue
    return None


def portal_diagnostic(url):
    """Only a confirmed server and parameter names, never values or raw URLs."""
    if not trusted_portal(url):
        return "未发现已确认的学校认证服务器"
    names = {part.split("=", 1)[0] for part in urlsplit(url).query.split("&") if part}
    names = sorted(name for name in names if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,39}", name))[:40]
    return f"认证服务器：{PORTAL_HOST}；参数名称：{'、'.join(names) or '无'}"


class NetworkProbe:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.trust_env = False

    def close(self):
        self.session.close()

    def check(self, guard=lambda: None) -> ProbeResult:
        detected = None
        for url, expected in PROBES:
            guard()
            try:
                # Never follow a captive redirect to an unconfirmed host.
                with self.session.get(url, timeout=(3, 4), allow_redirects=False,
                                      stream=True, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"}) as response:
                    content = bytearray()
                    for chunk in response.iter_content(4096):
                        content.extend(chunk)
                        if len(content) > 65536:
                            break
                    response._content = bytes(content[:65536])
                    guard()
                    if response.status_code == 200 and response.content.strip() == expected:
                        return ProbeResult(ProbeState.ONLINE)
                    if response.status_code in (200, 301, 302, 303, 307, 308):
                        portal = portal_from_response(response, require_parameters=False)
                        if portal:
                            try:
                                connection_query(portal)
                                detected = ProbeResult(ProbeState.PORTAL, portal)
                            except PortalError:
                                if detected is None:
                                    detected = ProbeResult(ProbeState.UNSUPPORTED, portal)
            except requests.RequestException:
                guard()
                continue
        return detected or ProbeResult(ProbeState.UNKNOWN)
