"""Тонкий клиент Bitrix24 REST API через входящий вебхук.

Совместим с песочницей NextBot: requests и json там уже загружены.
"""
import datetime

import requests

from booking.slots import parse_datetime, shift_timezone


def bitrix_call(webhook_url, method, params):
    """Вызывает метод REST API. Возвращает {"ok", "result", "error"} и не бросает исключений."""
    url = webhook_url.rstrip("/") + "/" + method
    try:
        response = requests.post(url, json=params, timeout=15)
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        return {"ok": False, "result": None, "error": f"{method}: {exc}"}
    if response.status_code != 200 or "error" in data:
        message = data.get("error_description") or data.get("error") or response.status_code
        return {"ok": False, "result": None, "error": f"{method}: {message}"}
    return {"ok": True, "result": data.get("result"), "error": None}


def find_employee_id(webhook_url, full_name):
    """ID активного сотрудника по имени. При нескольких совпадениях берёт точное совпадение ФИО."""
    call = bitrix_call(webhook_url, "user.search", {
        "FILTER": {"FIND": full_name, "USER_TYPE": "employee", "ACTIVE": "Y"},
    })
    if not call["ok"] or not call["result"]:
        return None
    wanted = " ".join(full_name.lower().split())
    for user in call["result"]:
        name = " ".join(f"{user.get('LAST_NAME', '')} {user.get('NAME', '')}".lower().split())
        reverse = " ".join(f"{user.get('NAME', '')} {user.get('LAST_NAME', '')}".lower().split())
        if wanted in (name, reverse):
            return int(user["ID"])
    return int(call["result"][0]["ID"])


def get_busy_intervals(webhook_url, user_id, day, clinic_tz):
    """Занятые интервалы врача на день во времени клиники.

    Каждое событие приводится к поясу клиники по полю TZ_FROM:
    события, созданные из другого часового пояса, иначе сдвигаются на разницу поясов.
    Обеды и перерывы в календаре тоже считаются занятым временем.
    """
    call = bitrix_call(webhook_url, "calendar.event.get", {
        "type": "user",
        "ownerId": str(user_id),
        "from": datetime.datetime.combine(day, datetime.time.min).isoformat(),
        "to": datetime.datetime.combine(day, datetime.time.max).isoformat(),
    })
    if not call["ok"]:
        return {"ok": False, "busy": [], "error": call["error"]}

    busy = []
    for event in call["result"] or []:
        start = parse_datetime(event.get("DATE_FROM"))
        end = parse_datetime(event.get("DATE_TO"))
        if start is None or end is None:
            continue
        event_tz = event.get("TZ_FROM") or clinic_tz
        busy.append({
            "start": shift_timezone(start, event_tz, clinic_tz),
            "end": shift_timezone(end, event_tz, clinic_tz),
        })
    return {"ok": True, "busy": busy, "error": None}


def start_booking_workflow(webhook_url, template_id, deal_id, parameters):
    """Запускает бизнес-процесс записи на сделке. Бизнес-процесс создаёт событие в календаре врача."""
    call = bitrix_call(webhook_url, "bizproc.workflow.start", {
        "TEMPLATE_ID": template_id,
        "DOCUMENT_ID": ["crm", "CCrmDocumentDeal", f"DEAL_{deal_id}"],
        "PARAMETERS": parameters,
    })
    if not call["ok"]:
        return {"ok": False, "workflow_id": None, "error": call["error"]}
    return {"ok": True, "workflow_id": call["result"], "error": None}

