import datetime as dt

from booking.slots import free_slots_in_range, round_up_to_grid
from booking.timezones import parse_bitrix_datetime, to_clinic_time

OPEN, CLOSE = dt.time(8), dt.time(20)


def at(day, h, m=0):
    return dt.datetime(2099, 6, day, h, m)


def test_event_time_is_read_in_its_own_timezone():
    # Событие создано из Москвы на 08:00, в клинике (UTC+5) это 10:00.
    assert to_clinic_time(at(15, 8), "Europe/Moscow", "Asia/Yekaterinburg") == at(15, 10)
    assert to_clinic_time(at(15, 8), "Asia/Novosibirsk", "Asia/Yekaterinburg") == at(15, 6)
    assert to_clinic_time(at(15, 8), None, "Asia/Yekaterinburg") == at(15, 8)


def test_parse_bitrix_datetime():
    assert parse_bitrix_datetime("15.06.2099 10:40:00") == at(15, 10, 40)
    assert parse_bitrix_datetime("15.06.2099 10:40") == at(15, 10, 40)
    assert parse_bitrix_datetime("2099-06-15") is None


def test_grid():
    assert round_up_to_grid(at(15, 10, 5), 20) == at(15, 10, 20)
    assert round_up_to_grid(at(15, 10, 40), 20) == at(15, 10, 40)


def test_range_spans_days_and_skips_busy():
    busy = [{"start": at(15, 8), "end": at(15, 19, 10)}]
    slots = free_slots_in_range(busy, at(15, 8), at(16, 9), 30, OPEN, CLOSE)
    assert slots == [at(15, 19, 30), at(16, 8), at(16, 8, 30)]


def test_not_before_and_limit():
    slots = free_slots_in_range([], at(15, 8), at(15, 20), 20, OPEN, CLOSE, not_before=at(15, 12, 10), limit=2)
    assert slots == [at(15, 12, 20), at(15, 12, 40)]
