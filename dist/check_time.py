# Собрано scripts/build_nextbot.py из booking/ и nextbot/check_time.py. Не редактировать вручную.

from zoneinfo import ZoneInfo
import datetime
import json
import math
import requests

"""Часовые пояса календаря Bitrix24.

Что показала работа с порталом клиники:
  * calendar.event.get отдаёт DATE_FROM во времени пояса самого события (TZ_FROM),
    а не того, кто читает; сравнивать DATE_FROM разных событий как строки нельзя;
  * поле DATE_FROM_TS_UTC расходилось с DATE_FROM на несколько часов, ему не доверяем;
  * у врачей одного портала бывают разные пояса, а у части сотрудников пояс не задан
    и календарь живёт в поясе портала по умолчанию.

Поэтому всё время приводится к одному эталонному поясу — поясу клиники.
В нём агент ищет слоты и в нём называет время пациенту.
"""

BITRIX_DATETIME = "%d.%m.%Y %H:%M:%S"


def parse_bitrix_datetime(value):
    """'ДД.ММ.ГГГГ ЧЧ:ММ[:СС]' -> datetime без пояса или None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    for pattern in (BITRIX_DATETIME, "%d.%m.%Y %H:%M"):
        try:
            return datetime.datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def to_clinic_time(naive, source_tz, clinic_tz):
    """Время события из его пояса -> время клиники, без tzinfo."""
    if not source_tz or source_tz == clinic_tz:
        return naive
    aware = naive.replace(tzinfo=ZoneInfo(source_tz))
    return aware.astimezone(ZoneInfo(clinic_tz)).replace(tzinfo=None)


def clinic_now(clinic_tz, now_utc=None):
    moment = now_utc or datetime.datetime.now(datetime.timezone.utc)
    return moment.astimezone(ZoneInfo(clinic_tz)).replace(tzinfo=None)


def format_for_patient(dt):
    return dt.strftime("%d.%m.%Y %H:%M")


"""Поиск свободного времени в календаре врача. Все datetime — во времени клиники, без tzinfo."""


def overlaps(start_a, end_a, start_b, end_b):
    """Пересекаются ли интервалы. Касание концами пересечением не считается."""
    return start_a < end_b and end_a > start_b


def is_free(busy, start, end):
    return not any(overlaps(start, end, item["start"], item["end"]) for item in busy)


def round_up_to_grid(dt, step_minutes):
    """Вверх до сетки step_minutes от начала суток: 10:05 при шаге 20 -> 10:20."""
    if step_minutes <= 0:
        return dt
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    step = step_minutes * 60
    seconds = (dt - day_start).total_seconds()
    return day_start + datetime.timedelta(seconds=math.ceil(seconds / step) * step)


def free_slots_in_range(busy, start, end, duration_minutes, work_start, work_end, not_before=None, limit=None):
    """Все свободные слоты сетки в диапазоне [start, end] с учётом рабочих часов.

    busy: список {"start", "end"}; work_start, work_end: datetime.time.
    not_before: не предлагать слоты раньше этого момента, например «сейчас + 30 минут».
    """
    step = datetime.timedelta(minutes=duration_minutes)
    slots = []
    day = start.date()
    while day <= end.date():
        day_open = max(start, datetime.datetime.combine(day, work_start))
        day_close = min(end, datetime.datetime.combine(day, work_end))
        if not_before is not None:
            day_open = max(day_open, not_before)
        cursor = round_up_to_grid(day_open, duration_minutes)
        while cursor + step <= day_close:
            slot_end = cursor + step
            blocker = next((b for b in busy if overlaps(cursor, slot_end, b["start"], b["end"])), None)
            if blocker is None:
                slots.append(cursor)
                if limit and len(slots) >= limit:
                    return slots
                cursor = slot_end
            else:
                # Сразу за конец мешающего события, снова по сетке.
                cursor = round_up_to_grid(blocker["end"], duration_minutes)
        day += datetime.timedelta(days=1)
    return slots


"""Какой календарь открыть: врач по справочнику, а не поиском по ФИО на портале.

Поиск сотрудника по ФИО через user.search ошибался: в профилях к ФИО дописана
специальность, встречаются буквы национальных алфавитов и тёзки. Теперь в CRM есть
справочник «Услуги и врачи» (смарт-процесс): в каждой строке услуги перечислены
врачи и ID сотрудника — владельца календаря. Функция каталога услуг отдаёт агенту
doctor_calendar_id, и запись идёт строго в этот календарь.

Правило: при любой неоднозначности вернуть ошибку с подсказкой агенту, а не угадывать.
"""
LETTERS = str.maketrans("әғқңөұүһіё", "агкноуухие")


def norm_name(value):
    """Регистр, пунктуация, двойные пробелы и буквы вроде «ә» или «ё» не важны."""
    text = str(value or "").lower().translate(LETTERS)
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def name_words_match(query, fio):
    """Каждое слово запроса совпадает со своим словом ФИО с учётом падежа:
    «к Ивановой Анне» -> «Иванова Анна Сергеевна»."""
    free = fio.split()
    for word in query.split():
        hit = None
        for i, candidate in enumerate(free):
            shortest = min(len(word), len(candidate))
            # у коротких слов падеж меняет последнюю букву, у длинных — до двух
            stem = max(3, shortest - 1) if shortest <= 5 else max(4, shortest - 2)
            if word == candidate or (shortest >= 4 and word[:stem] == candidate[:stem]):
                hit = i
                break
        if hit is None:
            return False
        free.pop(hit)
    return True


def build_directory(rows, field_doctor_ids, field_doctor_names):
    """Строки справочника -> {ФИО: множество ID календарей}, {ID календаря: [ФИО]}."""
    by_name, by_id = {}, {}
    for row in rows:
        ids = {int(i) for i in (row.get(field_doctor_ids) or [])}
        for fio in row.get(field_doctor_names) or []:
            fio = str(fio).strip()
            by_name.setdefault(fio, set()).update(ids)
            for calendar_id in ids:
                names = by_id.setdefault(calendar_id, [])
                if fio not in names:
                    names.append(fio)
    return by_name, by_id


def resolve_doctor(directory, calendar_id=None, name=None):
    """-> (ID календаря, ФИО для сообщений, текст ошибки для агента)."""
    by_name, by_id = directory
    name = str(name or "").strip()

    candidates, ids_by_name = [], set()
    if name:
        query = norm_name(name)
        candidates = [fio for fio in by_name if norm_name(fio) == query]
        if not candidates:
            candidates = [fio for fio in by_name if name_words_match(query, norm_name(fio))]
        for fio in candidates:
            ids_by_name |= by_name[fio]

    if calendar_id not in (None, ""):
        try:
            calendar_id = int(str(calendar_id).strip())
        except ValueError:
            return None, None, f"doctor_calendar_id должен быть числом, получено: «{calendar_id}»."
        if calendar_id not in by_id:
            return None, None, ("Такого календаря нет в справочнике. "
                                "Возьми doctor_calendar_id из ответа get_doctors_and_services.")
        if candidates and calendar_id not in ids_by_name:
            return None, None, (f"Врач «{name}» и календарь {calendar_id} ({', '.join(by_id[calendar_id])}) "
                                "не совпадают. Возьми врача и его календарь из одной строки справочника.")
        return calendar_id, name or ", ".join(by_id[calendar_id]), None

    if not name:
        return None, None, "Не передан врач: нужен doctor_calendar_id или doctor_name."
    if not candidates:
        return None, None, f"Врач «{name}» не найден в справочнике услуг и врачей."
    if not ids_by_name:
        return None, None, f"У врача «{name}» нет календаря в Bitrix24: записать через агента нельзя."
    if len(ids_by_name) > 1:
        options = "; ".join(f"{fio} ({', '.join(map(str, sorted(by_name[fio])))})" for fio in candidates)
        return None, None, f"Под «{name}» подходят разные врачи: {options}. Уточни у пациента ФИО."
    return next(iter(ids_by_name)), name, None


"""Вызовы Bitrix24 REST через входящий вебхук."""



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


"""Функции агента: check_time и create_appointment.

Ответ — в структурированном контракте платформы: tool_result читает модель,
tags помечают диалог. Главное правило: если Bitrix24 не подтвердил запись,
агент не подтверждает её пациенту.
"""


DEFAULT_CONFIG = {
    "clinic_tz": "Asia/Yekaterinburg",       # эталонный пояс: в нём ищем и называем время
    "webhook_owner_tz": "Europe/Moscow",     # пояс пользователя, от имени которого вебхук
    "work_start": datetime.time(8, 0),
    "work_end": datetime.time(20, 0),
    "min_lead_minutes": 30,                  # не предлагать слоты раньше, чем через 30 минут
    "max_slots": 30,
    "directory": {"entity_type_id": 0, "field_doctor_ids": "", "field_doctor_names": ""},
    "booking_template_id": 0,
    "lead_booking_fields": [],               # поля лида, заполненные первой записью
}


def reply(status, instruction, tags=None, **facts):
    payload = {"status": status, **facts, "instruction": instruction}
    result = {"tool_result": json.dumps(payload, ensure_ascii=False, default=str)}
    if tags:
        result["tags"] = tags
    return result


def failed(reason):
    return reply("error", "Запись не создана. Не подтверждай время пациенту, передай диалог администратору.",
                 tags=["booking_error"], reason=reason)


def doctor_from_args(cfg, bitrix, args):
    d = cfg["directory"]
    directory = bitrix.load_directory(d["entity_type_id"], d["field_doctor_ids"], d["field_doctor_names"])
    return resolve_doctor(directory, args.get("doctor_calendar_id"), args.get("doctor_name"))


def check_time(cfg, bitrix, args, now_utc=None):
    """Свободные слоты врача в диапазоне start_time–end_time (ДД.ММ.ГГГГ ЧЧ:ММ)."""
    try:
        doctor_id, doctor_name, problem = doctor_from_args(cfg, bitrix, args)
        if problem:
            return reply("invalid", problem)
        start = parse_bitrix_datetime(args.get("start_time"))
        end = parse_bitrix_datetime(args.get("end_time"))
        duration = int(args.get("appointment_duration") or 0)
        if start is None or end is None or duration <= 0 or start >= end:
            return reply("invalid", "Нужны start_time и end_time в формате ДД.ММ.ГГГГ ЧЧ:ММ и длительность больше нуля.")

        not_before = clinic_now(cfg["clinic_tz"], now_utc) + datetime.timedelta(minutes=cfg["min_lead_minutes"])
        busy = bitrix.busy_intervals(doctor_id, start.date(), end.date(), cfg["clinic_tz"])
        slots = free_slots_in_range(busy, start, end, duration, cfg["work_start"], cfg["work_end"],
                                    not_before=not_before, limit=cfg["max_slots"])
    except BitrixError as exc:
        return failed(str(exc))

    if not slots:
        return reply("no_slots", "В этом диапазоне свободного времени нет. Предложи другой день или другого врача.",
                     doctor=doctor_name)
    return reply("success", "Назови пациенту только эти варианты. Другого времени не предлагай.",
                 doctor=doctor_name, doctor_calendar_id=doctor_id,
                 slots=[format_for_patient(s) for s in slots])


def create_appointment(cfg, bitrix, args, now_utc=None):
    """Запись пациента. Первая запись по лиду — бизнес-процессом, следующие — событием в календаре."""
    try:
        doctor_id, doctor_name, problem = doctor_from_args(cfg, bitrix, args)
        if problem:
            return reply("invalid", problem)
        start = parse_bitrix_datetime(args.get("appointment_datetime"))
        duration = int(args.get("appointment_duration") or 0)
        lead_id = int(str(args.get("bitrixEntityId") or "").replace("LEAD_", "") or 0)
        if start is None or duration <= 0 or not lead_id:
            return reply("invalid", "Нужны время приёма ДД.ММ.ГГГГ ЧЧ:ММ, длительность и лид диалога.")
        end = start + datetime.timedelta(minutes=duration)
        if start < clinic_now(cfg["clinic_tz"], now_utc):
            return reply("invalid", "Это время уже прошло. Предложи пациенту другое.")
        if start.time() < cfg["work_start"] or end.time() > cfg["work_end"] or end.date() != start.date():
            return reply("invalid", "Время вне часов приёма клиники.")

        busy = bitrix.busy_intervals(doctor_id, start.date(), start.date(), cfg["clinic_tz"])
        if not is_free(busy, start, end):
            return reply("busy", "Время уже занято. Вызови check_time и предложи пациенту свободные варианты.")

        service = str(args.get("medical_services") or "")
        if bitrix.lead_has_booking(lead_id, cfg["lead_booking_fields"]):
            # Повторная проверка прямо перед записью: слот могли занять за секунды разговора.
            busy = bitrix.busy_intervals(doctor_id, start.date(), start.date(), cfg["clinic_tz"])
            if not is_free(busy, start, end):
                return reply("busy", "Слот только что заняли. Вызови check_time и предложи другое время.")
            event_id = bitrix.add_calendar_event(
                doctor_id, start, duration, cfg["clinic_tz"],
                name=f"Доп. запись: {service} | лид {lead_id}",
                description="Создано ИИ-агентом",
            )
            booking = {"calendar_event_id": event_id}
        else:
            workflow_id = bitrix.start_booking_workflow(
                cfg["booking_template_id"], lead_id, start, cfg["clinic_tz"], cfg["webhook_owner_tz"],
                {"Service": service, "Employee": f"user_{doctor_id}", "duration": duration},
            )
            booking = {"workflow_id": workflow_id}
    except BitrixError as exc:
        return failed(str(exc))

    if not any(booking.values()):
        return failed("Bitrix24 не вернул ID записи")
    return reply("success", "Запись создана. Подтверди пациенту врача, дату и время.",
                 tags=["booked"], doctor=doctor_name, slot=format_for_patient(start), **booking)


# Функция check_time для NextBot.
# Параметры, которые агент заполняет из диалога:
#   doctor_calendar_id    ID календаря из ответа get_doctors_and_services (предпочтительно)
#   doctor_name           ФИО врача, запасной путь
#   appointment_duration  длительность услуги в минутах
#   start_time, end_time  диапазон поиска, ДД.ММ.ГГГГ ЧЧ:ММ

CONFIG = dict(DEFAULT_CONFIG)
CONFIG.update({
    "webhook_url": "https://example.bitrix24.ru/rest/1/REPLACE_ME/",
    "directory": {"entity_type_id": 0, "field_doctor_ids": "ufCrm0Doctors", "field_doctor_names": "ufCrm0DoctorFio"},
})

result = check_time(CONFIG, Bitrix(CONFIG["webhook_url"]), args)
