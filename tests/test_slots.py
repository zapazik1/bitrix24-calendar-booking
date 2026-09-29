import datetime as dt

import pytest

from booking.slots import (
    find_free_slots,
    parse_datetime,
    round_up_to_grid,
    shift_timezone,
    suggest_alternatives,
)

DAY = dt.date(2099, 6, 15)
OPEN = dt.time(8, 0)
CLOSE = dt.time(20, 0)


def at(hour, minute=0, day=DAY):
    return dt.datetime.combine(day, dt.time(hour, minute))


def busy(start, end):
    return {"start": start, "end": end}


def test_parse_datetime_accepts_minutes_and_seconds():
    assert parse_datetime("15.06.2099 10:40") == at(10, 40)
    assert parse_datetime("15.06.2099 10:40:30") == at(10, 40).replace(second=30)


@pytest.mark.parametrize("value", ["", "2099-06-15 10:40", "15.06.2099", None, "31.02.2099 10:00"])
def test_parse_datetime_rejects_bad_input(value):
    assert parse_datetime(value) is None


def test_round_up_to_grid():
    assert round_up_to_grid(at(10, 5), 20) == at(10, 20)
    assert round_up_to_grid(at(10, 40), 20) == at(10, 40)


def test_free_slots_skip_busy_interval():
    slots = find_free_slots([busy(at(9), at(10))], DAY, 30, OPEN, CLOSE, limit=3)
    assert slots == [at(8), at(8, 30), at(10)]


def test_after_busy_event_search_continues_on_grid():
    slots = find_free_slots([busy(at(8), at(8, 50))], DAY, 20, OPEN, CLOSE, limit=1)
    assert slots == [at(9)]


def test_slot_must_end_before_closing():
    slots = find_free_slots([], DAY, 40, OPEN, dt.time(9, 0), limit=5)
    assert slots == [at(8)]


def test_not_before_moves_start_to_next_grid_step():
    slots = find_free_slots([], DAY, 20, OPEN, CLOSE, limit=1, not_before=at(12, 10))
    assert slots == [at(12, 20)]


def test_timezone_shift_between_moscow_and_yekaterinburg():
    assert shift_timezone(at(8), "Europe/Moscow", "Asia/Yekaterinburg") == at(10)
    assert shift_timezone(at(8), "Asia/Yekaterinburg", "Asia/Yekaterinburg") == at(8)
    with pytest.raises(ValueError):
        shift_timezone(at(8), "Mars/Olympus", "Asia/Yekaterinburg")


def test_alternatives_roll_over_to_next_day():
    next_day = DAY + dt.timedelta(days=1)
    full_day = [busy(at(8), at(20))]
    slots = suggest_alternatives(
        [[DAY, full_day], [next_day, []]], at(11), 30, OPEN, CLOSE, limit=2,
    )
    assert slots == [at(8, day=next_day), at(8, 30, day=next_day)]
