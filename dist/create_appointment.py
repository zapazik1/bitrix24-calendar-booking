# Собрано scripts/build_nextbot.py из booking/ и nextbot/create_appointment.py. Не редактировать вручную.
"""Поиск свободного времени в календаре врача.

Код совместим с песочницей Python на платформе NextBot:
без распаковки кортежей, без strptime/strftime, без функций с «_» в начале имени.
Строки import удаляет сборщик scripts/build_nextbot.py: в песочнице модули уже загружены.
"""

# Смещения от UTC для поясов без перехода на летнее время.
# В песочнице нет zoneinfo, поэтому таблица задана явно.
UTC_OFFSETS_HOURS = {
    "UTC": 0,
    "Europe/Moscow": 3,
    "Europe/Samara": 4,
    "Asia/Yekaterinburg": 5,
    "Asia/Almaty": 5,
    "Asia/Tashkent": 5,
    "Asia/Omsk": 6,
    "Asia/Novosibirsk": 7,
}


def parse_datetime(value):
    """'ДД.ММ.ГГГГ ЧЧ:ММ[:СС]' -> datetime без пояса или None."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(" ")
    if len(parts) != 2:
        return None
    date_parts = parts[0].split(".")
    time_parts = parts[1].split(":")
    if len(date_parts) != 3 or len(time_parts) not in (2, 3):
        return None
    try:
        second = int(time_parts[2]) if len(time_parts) == 3 else 0
        return datetime.datetime(
            int(date_parts[2]), int(date_parts[1]), int(date_parts[0]),
            int(time_parts[0]), int(time_parts[1]), second,
        )
    except ValueError:
        return None


def format_datetime(dt):
    """datetime -> 'ДД.ММ.ГГГГ ЧЧ:ММ' без strftime."""
    return f"{dt.day:02d}.{dt.month:02d}.{dt.year:04d} {dt.hour:02d}:{dt.minute:02d}"


def shift_timezone(dt, from_tz, to_tz):
    """Переводит время из пояса from_tz в пояс to_tz."""
    if not from_tz or not to_tz or from_tz == to_tz:
        return dt
    if from_tz not in UTC_OFFSETS_HOURS or to_tz not in UTC_OFFSETS_HOURS:
        raise ValueError(f"Нет смещения для пояса: {from_tz} или {to_tz}")
    hours = UTC_OFFSETS_HOURS[to_tz] - UTC_OFFSETS_HOURS[from_tz]
    return dt + datetime.timedelta(hours=hours)


def overlaps(start_a, end_a, start_b, end_b):
    """Пересекаются ли два интервала. Касание концами не считается пересечением."""
    return start_a < end_b and end_a > start_b


def is_free(busy, start, end):
    """Свободен ли интервал [start, end) при заданных занятых интервалах."""
    for item in busy:
        if overlaps(start, end, item["start"], item["end"]):
            return False
    return True


def round_up_to_grid(dt, step_minutes):
    """Округляет вверх до сетки step_minutes от начала суток: 10:05 при шаге 20 -> 10:20."""
    if step_minutes <= 0:
        return dt
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds = (dt - day_start).total_seconds()
    step = step_minutes * 60
    return day_start + datetime.timedelta(seconds=math.ceil(seconds / step) * step)


def find_free_slots(busy, day, duration_minutes, work_start, work_end, limit=3, not_before=None):
    """Свободные слоты на день по сетке длительности приёма.

    busy: список {"start": datetime, "end": datetime} во времени клиники.
    work_start, work_end: datetime.time рабочего дня врача.
    not_before: не предлагать слоты раньше этого момента (например, «сейчас»).
    """
    step = datetime.timedelta(minutes=duration_minutes)
    day_open = datetime.datetime.combine(day, work_start)
    day_close = datetime.datetime.combine(day, work_end)

    cursor = day_open
    if not_before is not None and not_before > cursor:
        cursor = not_before
    cursor = round_up_to_grid(cursor, duration_minutes)

    slots = []
    while len(slots) < limit and cursor + step <= day_close:
        slot_end = cursor + step
        blocker = None
        for item in busy:
            if overlaps(cursor, slot_end, item["start"], item["end"]):
                blocker = item
                break
        if blocker is None:
            slots.append(cursor)
            cursor = slot_end
        else:
            # Прыгаем сразу за конец мешающего события и выравниваем по сетке.
            cursor = round_up_to_grid(blocker["end"], duration_minutes)
    return slots


def suggest_alternatives(busy_by_day, requested_start, duration_minutes, work_start, work_end, limit=3):
    """Ближайшие свободные слоты после запрошенного времени, по дням подряд.

    busy_by_day: список пар [дата, занятые интервалы], отсортированный по дате.
    """
    found = []
    for entry in busy_by_day:
        day = entry[0]
        busy = entry[1]
        not_before = requested_start if day == requested_start.date() else None
        day_slots = find_free_slots(
            busy, day, duration_minutes, work_start, work_end,
            limit=limit - len(found), not_before=not_before,
        )
        found.extend(day_slots)
        if len(found) >= limit:
            break
    return found
"""Тонкий клиент Bitrix24 REST API через входящий вебхук.

Совместим с песочницей NextBot: requests и json там уже загружены.
"""




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

"""Две функции для ИИ-агента: проверить время и записать пациента.

Ответ каждой функции адресован модели: статус, факты и инструкция, что говорить клиенту.
Главное правило: если запись не подтвердил Bitrix24, агент не подтверждает её клиенту.
"""


DEFAULT_CONFIG = {
    "webhook_url": "https://example.bitrix24.ru/rest/1/REPLACE_ME/",
    "clinic_tz": "Asia/Yekaterinburg",
    "work_start": "08:00",
    "work_end": "20:00",
    "booking_template_id": 0,
    "days_to_search": 3,
    "slots_to_suggest": 3,
}


def parse_clock(value):
    parts = value.split(":")
    return datetime.time(int(parts[0]), int(parts[1]))


def clinic_now(clinic_tz):
    utc_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return shift_timezone(utc_now, "UTC", clinic_tz)


def error_result(reason):
    return {
        "status": "error",
        "reason": reason,
        "instruction": "Запись не создана. Не подтверждай время клиенту. Передай диалог администратору.",
    }


def collect_busy(config, doctor_id, first_day):
    """Занятость врача на несколько дней вперёд: список пар [дата, интервалы]."""
    days = []
    for offset in range(config["days_to_search"]):
        day = first_day + datetime.timedelta(days=offset)
        loaded = get_busy_intervals(config["webhook_url"], doctor_id, day, config["clinic_tz"])
        if not loaded["ok"]:
            return {"ok": False, "days": [], "error": loaded["error"]}
        days.append([day, loaded["busy"]])
    return {"ok": True, "days": days, "error": None}


def validate_request(config, doctor_name, requested, duration_minutes):
    """Проверки до обращения к календарю. Возвращает текст ошибки или None."""
    if not doctor_name:
        return "Не указан врач."
    if requested is None:
        return "Дата и время не распознаны. Ожидается ДД.ММ.ГГГГ ЧЧ:ММ."
    if duration_minutes <= 0:
        return "Длительность приёма должна быть больше нуля."
    if requested < clinic_now(config["clinic_tz"]):
        return "Запрошенное время уже прошло."
    start = parse_clock(config["work_start"])
    end = parse_clock(config["work_end"])
    finish = requested + datetime.timedelta(minutes=duration_minutes)
    if requested.time() < start or finish.time() > end or finish.date() != requested.date():
        return f"Приём возможен с {config['work_start']} до {config['work_end']}."
    return None


def check_time(config, doctor_name, requested_text, duration_minutes):
    """Функция агента check_time: свободно ли время и какие есть варианты."""
    requested = parse_datetime(requested_text)
    problem = validate_request(config, doctor_name, requested, duration_minutes)
    if problem:
        return {"status": "invalid", "reason": problem,
                "instruction": "Уточни у клиента данные и вызови функцию снова."}

    doctor_id = find_employee_id(config["webhook_url"], doctor_name)
    if doctor_id is None:
        return {"status": "invalid", "reason": f"Врач «{doctor_name}» не найден.",
                "instruction": "Уточни у клиента имя врача по списку специалистов."}

    loaded = collect_busy(config, doctor_id, requested.date())
    if not loaded["ok"]:
        return error_result(loaded["error"])

    finish = requested + datetime.timedelta(minutes=duration_minutes)
    if is_free(loaded["days"][0][1], requested, finish):
        return {"status": "free", "slot": format_datetime(requested), "doctor_id": doctor_id,
                "instruction": "Время свободно. Получи согласие клиента и вызови create_appointment."}

    alternatives = suggest_alternatives(
        loaded["days"], requested, duration_minutes,
        parse_clock(config["work_start"]), parse_clock(config["work_end"]),
        limit=config["slots_to_suggest"],
    )
    return {
        "status": "busy",
        "alternatives": [format_datetime(slot) for slot in alternatives],
        "instruction": "Время занято. Предложи клиенту только эти варианты, другого времени не называй."
        if alternatives else "Свободного времени в ближайшие дни нет. Предложи записаться к другому врачу.",
    }


def create_appointment(config, doctor_name, requested_text, duration_minutes, deal_id, service_name):
    """Функция агента create_appointment: повторная проверка и запуск бизнес-процесса записи.

    Время проверяется ещё раз прямо перед записью: между check_time и согласием клиента
    слот мог занять администратор или другой пациент.
    """
    checked = check_time(config, doctor_name, requested_text, duration_minutes)
    if checked["status"] != "free":
        return checked

    requested = parse_datetime(requested_text)
    started = start_booking_workflow(
        config["webhook_url"], config["booking_template_id"], deal_id,
        {
            "Service": service_name,
            "StartDate": requested.isoformat(),
            "Employee": f"user_{checked['doctor_id']}",
            "Duration": duration_minutes,
        },
    )
    if not started["ok"]:
        return error_result(started["error"])
    return {
        "status": "success",
        "slot": format_datetime(requested),
        "workflow_id": started["workflow_id"],
        "instruction": "Запись создана. Подтверди клиенту врача, дату и время.",
    }

# Точка входа функции create_appointment в NextBot.
# scripts/build_nextbot.py ставит перед этим файлом код из booking/ без строк import.
# args["bitrixEntityId"] NextBot передаёт сам: сделка диалога вида "DEAL_123".

CONFIG = dict(DEFAULT_CONFIG)
CONFIG.update({
    "webhook_url": "https://example.bitrix24.ru/rest/1/REPLACE_ME/",
    "clinic_tz": "Asia/Yekaterinburg",
    "booking_template_id": 0,
})


def deal_id_from_entity(value):
    text = str(value or "")
    if text.startswith("DEAL_"):
        text = text[len("DEAL_"):]
    return int(text) if text.isdigit() else None


deal_id = deal_id_from_entity(args.get("bitrixEntityId"))
if deal_id is None:
    result = error_result("Нет сделки в Bitrix24 для этого диалога.")
else:
    result = create_appointment(
        CONFIG,
        args.get("doctor_name", ""),
        args.get("appointment_datetime", ""),
        int(args.get("duration_minutes") or 20),
        deal_id,
        args.get("service_name", ""),
    )
