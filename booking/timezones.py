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
import datetime
from zoneinfo import ZoneInfo

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
