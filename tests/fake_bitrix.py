"""Подменённый портал для сценарных тестов: отвечает на методы по имени."""
import booking.bitrix as bitrix_module

PORTAL = "https://example.bitrix24.ru/rest/1/test/"
DIRECTORY_ROWS = [
    {"id": 1, "ufCrm0Doctors": [101], "ufCrm0DoctorFio": ["Иванова Анна Сергеевна"]},
    {"id": 2, "ufCrm0Doctors": [101], "ufCrm0DoctorFio": ["Иванова Анна Сергеевна"]},
    {"id": 3, "ufCrm0Doctors": [202], "ufCrm0DoctorFio": ["Петров Олег Игоревич"]},
    {"id": 4, "ufCrm0Doctors": [303], "ufCrm0DoctorFio": ["Петрова Ольга Ивановна"]},
    {"id": 5, "ufCrm0Doctors": [], "ufCrm0DoctorFio": ["Сидоренко Жанна Олеговна"]},
]


class Resp:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakePortal:
    def __init__(self, events=None, lead=None, fail=None):
        self.events = events or {}          # ownerId -> список событий
        self.lead = lead or {}
        self.fail = fail or set()
        self.calls = []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json))
        if method in self.fail:
            return Resp({"error": "ACCESS_DENIED", "error_description": "Нет прав"}, 403)
        if method == "batch":
            return Resp({"result": {"result": {"p0": {"items": DIRECTORY_ROWS}}}})
        if method == "calendar.event.get":
            return Resp({"result": self.events.get(json["ownerId"], [])})
        if method == "crm.lead.get":
            return Resp({"result": self.lead})
        if method == "calendar.section.get":
            return Resp({"result": [{"ID": "7"}]})
        if method == "calendar.event.add":
            return Resp({"result": 5555})
        if method == "bizproc.workflow.start":
            return Resp({"result": "wf-1"})
        raise AssertionError(method)

    def install(self, monkeypatch):
        monkeypatch.setattr(bitrix_module.requests, "post", self.post)
        return self
