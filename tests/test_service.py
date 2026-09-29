import datetime as dt
import json

from booking.bitrix import Bitrix
from booking.service import DEFAULT_CONFIG, check_time, create_appointment
from tests.fake_bitrix import PORTAL, FakePortal

CFG = dict(DEFAULT_CONFIG, booking_template_id=7, lead_booking_fields=["UF_CRM_BOOKING_DATE"],
           directory={"entity_type_id": 1, "field_doctor_ids": "ufCrm0Doctors", "field_doctor_names": "ufCrm0DoctorFio"})
NOW = dt.datetime(2099, 6, 14, 3, 0, tzinfo=dt.timezone.utc)   # 08:00 в клинике накануне


def payload(result):
    return json.loads(result["tool_result"])


def moscow_event(start, end):
    return {"DATE_FROM": start, "DATE_TO": end, "TZ_FROM": "Europe/Moscow", "TZ_TO": "Europe/Moscow"}


def test_check_time_reads_events_in_their_timezone(monkeypatch):
    # 08:00–09:00 по Москве = 10:00–11:00 в клинике.
    FakePortal({"101": [moscow_event("15.06.2099 08:00:00", "15.06.2099 09:00:00")]}).install(monkeypatch)
    args = {"doctor_calendar_id": 101, "appointment_duration": 30,
            "start_time": "15.06.2099 10:00", "end_time": "15.06.2099 12:00"}
    answer = payload(check_time(CFG, Bitrix(PORTAL), args, now_utc=NOW))
    assert answer["slots"] == ["15.06.2099 11:00", "15.06.2099 11:30"]


def test_first_booking_goes_through_workflow_in_owner_timezone(monkeypatch):
    portal = FakePortal(lead={}).install(monkeypatch)
    args = {"doctor_calendar_id": 101, "appointment_duration": 30, "appointment_datetime": "15.06.2099 10:00",
            "bitrixEntityId": "LEAD_77", "medical_services": "Консультация"}
    result = create_appointment(CFG, Bitrix(PORTAL), args, now_utc=NOW)
    assert payload(result)["status"] == "success" and result["tags"] == ["booked"]
    workflow = [body for method, body in portal.calls if method == "bizproc.workflow.start"][0]
    # 10:00 в UTC+5 — это 08:00 для владельца вебхука в UTC+3.
    assert workflow["PARAMETERS"]["StartDate"] == "2099-06-15T08:00:00"
    assert workflow["DOCUMENT_ID"] == ["crm", "CCrmDocumentLead", "LEAD_77"]


def test_additional_booking_writes_event_with_timezone_keys(monkeypatch):
    portal = FakePortal(lead={"UF_CRM_BOOKING_DATE": "2099-06-10"}).install(monkeypatch)
    args = {"doctor_name": "Ивановой Анне", "appointment_duration": 30, "appointment_datetime": "15.06.2099 10:00",
            "bitrixEntityId": "77", "medical_services": "Повторный приём"}
    assert payload(create_appointment(CFG, Bitrix(PORTAL), args, now_utc=NOW))["calendar_event_id"] == 5555
    event = [body for method, body in portal.calls if method == "calendar.event.add"][0]
    assert event["timezone_from"] == event["timezone_to"] == "Asia/Yekaterinburg"
    assert "tzFrom" not in event and event["from"] == "2099-06-15T10:00:00"


def test_bitrix_error_means_no_confirmation(monkeypatch):
    FakePortal(lead={}, fail={"bizproc.workflow.start"}).install(monkeypatch)
    args = {"doctor_calendar_id": 101, "appointment_duration": 30, "appointment_datetime": "15.06.2099 10:00",
            "bitrixEntityId": "77"}
    result = create_appointment(CFG, Bitrix(PORTAL), args, now_utc=NOW)
    assert payload(result)["status"] == "error"
    assert "Не подтверждай" in payload(result)["instruction"] and result["tags"] == ["booking_error"]


def test_busy_slot(monkeypatch):
    FakePortal({"101": [moscow_event("15.06.2099 08:00:00", "15.06.2099 09:00:00")]}, lead={}).install(monkeypatch)
    args = {"doctor_calendar_id": 101, "appointment_duration": 30, "appointment_datetime": "15.06.2099 10:30",
            "bitrixEntityId": "77"}
    assert payload(create_appointment(CFG, Bitrix(PORTAL), args, now_utc=NOW))["status"] == "busy"
