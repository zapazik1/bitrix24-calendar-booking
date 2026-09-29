import sys
from pathlib import Path

import pytest
import requests

from tests.readonly_guard import ReadOnlyGuard, WriteAttemptBlocked

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_nextbot  # noqa: E402

PORTAL = "https://example.bitrix24.ru/"


def test_guard_never_lets_writes_through(monkeypatch):
    reached = []
    monkeypatch.setattr(requests, "post", lambda url, **kw: reached.append(url) or None)
    with ReadOnlyGuard(PORTAL) as guard:
        requests.post(PORTAL + "rest/1/x/calendar.event.get", json={})
        assert requests.post(PORTAL + "rest/1/x/calendar.event.add", json={}).json()["result"] == 999000001
        requests.post(PORTAL + "rest/1/x/batch", json={"cmd": {"a": "crm.item.list?x=1"}})
        with pytest.raises(WriteAttemptBlocked):
            requests.post(PORTAL + "rest/1/x/batch", json={"cmd": {"a": "crm.item.list", "b": "crm.item.update?id=1"}})
        with pytest.raises(WriteAttemptBlocked):
            requests.post("https://example.com/x", json={})
    assert reached == [PORTAL + "rest/1/x/calendar.event.get", PORTAL + "rest/1/x/batch"]
    assert [b["method"] for b in guard.blocked] == ["calendar.event.add", "batch", "x"]


def test_built_function_runs_as_single_file(monkeypatch):
    from tests.fake_bitrix import FakePortal
    build_nextbot.build()
    portal = FakePortal()
    monkeypatch.setattr(requests, "post", portal.post)
    scope = {"args": {"doctor_calendar_id": 101, "appointment_duration": 30,
                      "start_time": "15.06.2099 10:00", "end_time": "15.06.2099 11:00"}}
    exec((ROOT / "dist" / "check_time.py").read_text(encoding="utf-8"), scope)
    assert "tool_result" in scope["result"]
