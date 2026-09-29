"""Поиск свободного времени в календаре врача.

Код совместим с песочницей Python на платформе NextBot:
без распаковки кортежей, без strptime/strftime, без функций с «_» в начале имени.
Строки import удаляет сборщик scripts/build_nextbot.py: в песочнице модули уже загружены.
"""
import datetime
import math

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
