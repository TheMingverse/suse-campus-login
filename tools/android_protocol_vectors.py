"""Generate/check synthetic Android fixtures using the unchanged Python protocol implementation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from campus_login.models import PortalError
from campus_login.portal import component, form, connection_query, parse_services, classify_login


def fixtures():
    query = "wlanuserip=fresh-user&wlanacname=fresh-ac&mac=ab%3Acd&ssid=fresh-ssid"
    forms = []
    for double in (False, True):
        fields = {"userId": "student+&%", "password": "a+b&c=汉字🙂!", "queryString": query, "service": "新服务+&汉字"}
        forms.append({"fields": fields, "double": double, "expected": form(fields, double).decode("ascii")})
    catalogs = []
    for entries in ([{"serviceName": "新服务+&汉字"}], [{"serviceName": "A"}, {"serviceName": "A"}],
                    [{"serviceName": "A", "id": 1}, {"serviceName": "A", "id": 2}, {"serviceName": "A", "id": 2}],
                    [{"serviceName": "A", "aceNotShow": True}], [{"serviceName": "A", "domainName": "unexpected"}]):
        payload = {"serviceJson": entries}
        catalogs.append({"payload": payload, "expected": [{"name": o.name, "available": o.available} for o in parse_services(payload)]})
    outcomes = []
    for data in ({"result": "success"}, {"result": "success", "message": "false::PWD_COMPLEX_OFFLINE_WEB::5"},
                 *({"result": "fail", "message": m} for m in ("用户student密码错误", "验证码错误", "服务器繁忙", "终端数量上限", "unknown student synthetic-secret"))):
        try:
            expected = classify_login(data)
        except PortalError as error:
            expected = error.kind
        outcomes.append({"data": data, "expected": expected})
    return {"source": "Unchanged local Python protocol; synthetic credentials and connection parameters only.",
            "query": query, "portal": "http://10.23.2.4/eportal/index.jsp?" + query,
            "components": [{"input": x, "expected": component(x)} for x in ("!~*'() ", "汉字🙂+&%", "a/b:c?d=e")],
            "forms": forms, "catalogs": catalogs, "outcomes": outcomes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "android/core/src/test/fixtures/python_protocol.json"
    value = fixtures()
    if args.check:
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise SystemExit("Android fixtures differ from Python protocol")
        print("Python/Android synthetic protocol fixtures: OK")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Synthetic protocol fixtures generated")


if __name__ == "__main__":
    main()
