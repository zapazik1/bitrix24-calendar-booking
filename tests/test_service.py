"""Сценарии функций агента на подменённом Bitrix24 API."""
import booking.bitrix as bitrix
from booking.service import DEFAULT_CONFIG, check_time, create_appointment

CONFIG = dict(DEFAULT_CONFIG, clinic_tz="Asia/Yekaterinburg", booking_template_id=7, days_to_search=2)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


def fake_bitrix(events, workflow_ok=True):
    """Подменяет requests.post: отвечает на методы по имени."""
    def post(url, json, timeout):
        method = url.rsplit("/", 1)[-1]
        if method == "user.search":
            return FakeResponse({"result": [{"ID": "42", "NAME": "Анна", "LAST_NAME": "Иванова"}]})
        if method == "calendar.event.get":
            day = json["from"][:10]
            return FakeResponse({"result": [e for e in events if e["day"] == day]})
        if method == "bizproc.workflow.start":
            if workflow_ok:
                return FakeResponse({"result": "wf-1"})
            return FakeResponse({"error": "ACCESS_DENIED", "error_description": "Нет прав"}, 403)
        raise AssertionError(method)
    return post


def event(day, start, end, tz="Asia/Yekaterinburg"):
    return {"day": day, "DATE_FROM": start, "DATE_TO": end, "TZ_FROM": tz}


def test_free_time(monkeypatch):
    monkeypatch.setattr(bitrix.requests, "post", fake_bitrix([]))
    answer = check_time(CONFIG, "Иванова Анна", "15.06.2099 10:00", 30)
    assert answer["status"] == "free"


def test_event_from_other_timezone_blocks_local_time(monkeypatch):
    # Событие создано из Москвы на 08:00, в клинике (UTC+5) это 10:00.
    events = [event("2099-06-15", "15.06.2099 08:00:00", "15.06.2099 09:00:00", tz="Europe/Moscow")]
    monkeypatch.setattr(bitrix.requests, "post", fake_bitrix(events))
    answer = check_time(CONFIG, "Иванова Анна", "15.06.2099 10:00", 30)
    assert answer["status"] == "busy"
    assert answer["alternatives"][0] == "15.06.2099 11:00"


def test_booking_error_tells_agent_not_to_confirm(monkeypatch):
    monkeypatch.setattr(bitrix.requests, "post", fake_bitrix([], workflow_ok=False))
    answer = create_appointment(CONFIG, "Иванова Анна", "15.06.2099 10:00", 30, 123, "Консультация")
    assert answer["status"] == "error"
    assert "Не подтверждай" in answer["instruction"]


def test_booking_success(monkeypatch):
    monkeypatch.setattr(bitrix.requests, "post", fake_bitrix([]))
    answer = create_appointment(CONFIG, "Иванова Анна", "15.06.2099 10:00", 30, 123, "Консультация")
    assert answer == {
        "status": "success",
        "slot": "15.06.2099 10:00",
        "workflow_id": "wf-1",
        "instruction": "Запись создана. Подтверди клиенту врача, дату и время.",
    }


def test_time_outside_working_hours_is_rejected(monkeypatch):
    monkeypatch.setattr(bitrix.requests, "post", fake_bitrix([]))
    answer = check_time(CONFIG, "Иванова Анна", "15.06.2099 19:50", 30)
    assert answer["status"] == "invalid"
