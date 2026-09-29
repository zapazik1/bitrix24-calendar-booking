"""Вызовы Bitrix24 REST через входящий вебхук."""
import datetime
from zoneinfo import ZoneInfo

import requests

from booking.doctors import build_directory
from booking.timezones import parse_bitrix_datetime, to_clinic_time

TIMEOUT = 15


class BitrixError(RuntimeError):
    pass


class Bitrix:
    def __init__(self, webhook_url):
        self.base = webhook_url.rstrip("/") + "/"

    def call(self, method, params=None):
        try:
            response = requests.post(self.base + method, json=params or {}, timeout=TIMEOUT)
            data = response.json()
        except (requests.exceptions.RequestException, ValueError) as exc:
            raise BitrixError(f"{method}: {exc}") from exc
        if response.status_code != 200 or "error" in data:
            raise BitrixError(f"{method}: {data.get('error_description') or data.get('error') or response.status_code}")
        return data.get("result")

    # ---------------------------------------------------------------- чтение
    def load_directory(self, entity_type_id, field_doctor_ids, field_doctor_names, pages=10):
        """Справочник «Услуги и врачи» одним batch-запросом, по 50 строк на страницу."""
        commands = {
            f"p{page}": (f"crm.item.list?entityTypeId={entity_type_id}&start={page * 50}"
                         f"&select[0]=id&select[1]={field_doctor_ids}&select[2]={field_doctor_names}")
            for page in range(pages)
        }
        result = self.call("batch", {"halt": 0, "cmd": commands}) or {}
        rows = []
        for page in range(pages):
            rows.extend(((result.get("result") or {}).get(f"p{page}") or {}).get("items") or [])
        return build_directory(rows, field_doctor_ids, field_doctor_names)

    def busy_intervals(self, user_id, first_day, last_day, clinic_tz):
        """Занятые интервалы врача во времени клиники. Обеды и перерывы тоже занятость.

        DATE_FROM приходит в поясе события (TZ_FROM), поэтому каждое событие
        переводится в пояс клиники отдельно.
        """
        events = self.call("calendar.event.get", {
            "type": "user",
            "ownerId": str(user_id),
            "from": datetime.datetime.combine(first_day, datetime.time.min).isoformat(),
            "to": datetime.datetime.combine(last_day, datetime.time.max).isoformat(),
        }) or []
        busy = []
        for event in events:
            start = parse_bitrix_datetime(event.get("DATE_FROM"))
            end = parse_bitrix_datetime(event.get("DATE_TO"))
            if start is None or end is None:
                continue
            event_tz = event.get("TZ_FROM") or clinic_tz
            busy.append({"start": to_clinic_time(start, event_tz, clinic_tz),
                         "end": to_clinic_time(end, event.get("TZ_TO") or event_tz, clinic_tz)})
        return busy

    def lead_has_booking(self, lead_id, booking_fields):
        lead = self.call("crm.lead.get", {"ID": int(lead_id)}) or {}
        return any(lead.get(field) for field in booking_fields)

    # ---------------------------------------------------------------- запись
    def add_calendar_event(self, user_id, start, duration_minutes, clinic_tz, name, description):
        """Событие прямо в календаре врача.

        Пояс передаётся ключами timezone_from / timezone_to. Старые ключи tzFrom / tzTo
        портал в какой-то момент начал молча игнорировать, и событие писалось в пояс
        владельца вебхука со сдвигом на разницу поясов.
        """
        end = start + datetime.timedelta(minutes=duration_minutes)
        sections = self.call("calendar.section.get", {"type": "user", "ownerId": int(user_id)}) or []
        params = {
            "type": "user",
            "ownerId": int(user_id),
            "from": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "to": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "timezone_from": clinic_tz,
            "timezone_to": clinic_tz,
            "name": name,
            "description": description,
            "skip_time": "N",
            "accessibility": "busy",
        }
        if sections:
            params["section"] = int(sections[0]["ID"])
        return self.call("calendar.event.add", params)

    def start_booking_workflow(self, template_id, lead_id, start, clinic_tz, owner_tz, parameters):
        """Первая запись идёт бизнес-процессом на лиде: он создаёт событие и заполняет поля лида.

        Бизнес-процесс понимает StartDate во времени владельца вебхука, поэтому время
        клиники переводится в его пояс, а не сдвигается на зашитую разницу часов.
        """
        owner_start = start.replace(tzinfo=ZoneInfo(clinic_tz)).astimezone(ZoneInfo(owner_tz)).replace(tzinfo=None)
        return self.call("bizproc.workflow.start", {
            "TEMPLATE_ID": template_id,
            "DOCUMENT_ID": ["crm", "CCrmDocumentLead", f"LEAD_{int(lead_id)}"],
            "PARAMETERS": dict(parameters, StartDate=owner_start.isoformat()),
        })
