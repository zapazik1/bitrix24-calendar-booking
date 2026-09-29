"""Поиск свободного времени в календаре врача. Все datetime — во времени клиники, без tzinfo."""
import datetime
import math


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
