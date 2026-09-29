"""Защита от записи в Bitrix24 при проверке на живом портале.

Пока защита включена, каждый HTTP-запрос проходит через неё:
  * читающие методы уходят на портал;
  * всё остальное не отправляется: запрос пишется в журнал, код получает
    фиктивный успешный ответ и продолжает работу, так видно, что он записал бы;
  * batch пропускается, только если все команды в нём читающие;
  * запросы не на портал блокируются.

    with ReadOnlyGuard("https://portal.bitrix24.ru/") as guard:
        ...запуск функций агента...
    guard.blocked   # что код пытался записать
"""
import json
import urllib.parse

import requests

READ_METHODS = {
    "calendar.event.get", "calendar.section.get", "calendar.event.getbyid",
    "crm.item.list", "crm.item.get", "crm.lead.get", "crm.lead.list",
    "user.get", "user.search", "profile",
}
FAKE_RESULTS = {"calendar.event.add": 999000001, "bizproc.workflow.start": "FAKE-WORKFLOW-ID"}
VERBS = ("post", "get", "put", "delete", "patch")


def method_of(url):
    name = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    return name[:-5] if name.endswith(".json") else name


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class WriteAttemptBlocked(Exception):
    pass


class ReadOnlyGuard:
    def __init__(self, portal):
        self.portal = portal
        self.sent, self.blocked = [], []
        self.originals = {}

    def allowed(self, url, body):
        if not url.startswith(self.portal):
            return False
        method = method_of(url)
        if method == "batch":
            commands = (body or {}).get("cmd") or {}
            return all(str(c).split("?")[0] in READ_METHODS for c in commands.values())
        return method in READ_METHODS

    def handle(self, verb, url, kwargs):
        body = kwargs.get("json") if isinstance(kwargs.get("json"), dict) else {}
        method = method_of(url)
        if self.allowed(url, body):
            self.sent.append(method)
            return self.originals[verb](url, **kwargs)
        self.blocked.append({"method": method, "body": body})
        if method in FAKE_RESULTS:
            return FakeResponse({"result": FAKE_RESULTS[method]})
        raise WriteAttemptBlocked(f"{method}: запрос заблокирован и не отправлен")

    def __enter__(self):
        for verb in VERBS:
            self.originals[verb] = getattr(requests, verb)
            setattr(requests, verb, lambda url, _v=verb, **kw: self.handle(_v, url, kw))
        return self

    def __exit__(self, *exc):
        for verb, original in self.originals.items():
            setattr(requests, verb, original)
        return False
