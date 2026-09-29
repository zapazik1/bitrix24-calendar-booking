import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_nextbot  # noqa: E402


def test_built_functions_pass_sandbox_rules():
    assert build_nextbot.build() == []
    for name in ("check_time.py", "create_appointment.py"):
        text = (build_nextbot.ROOT / "dist" / name).read_text(encoding="utf-8")
        assert "\nresult = " in text or "\n    result = " in text
