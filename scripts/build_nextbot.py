"""Собирает однофайловые функции для NextBot и проверяет ограничения песочницы.

В песочнице NextBot функция загружается одним файлом, модули уже импортированы,
а часть синтаксиса Python запрещена. Сборщик склеивает booking/*.py с точкой входа,
вырезает import и падает, если в итоговом коде есть запрещённые конструкции.

Запуск: python scripts/build_nextbot.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIBRARY = ["booking/slots.py", "booking/bitrix.py", "booking/service.py"]
ENTRY_POINTS = ["nextbot/check_time.py", "nextbot/create_appointment.py"]

FORBIDDEN = [
    (re.compile(r"^\s*(import|from)\s+\w", re.M), "import запрещён: модули уже загружены"),
    (re.compile(r"^\s*def\s+_", re.M), "имя функции не может начинаться с «_»"),
    (re.compile(r"\bstr[fp]time\("), "strptime и strftime в песочнице не работают"),
    (re.compile(r"^\s*[A-Za-z_]\w*\s*,\s*[A-Za-z_]\w*[ \t\w,]*=(?!=)", re.M), "распаковка кортежа запрещена"),
    (re.compile(r"^\s*for\s+\w+\s*,\s*\w+\s+in\b", re.M), "распаковка в цикле for запрещена"),
]


def strip_imports(source):
    """Удаляет строки import, включая многострочные from x import (...)."""
    lines = source.splitlines()
    kept = []
    skipping = False
    for line in lines:
        if skipping:
            if ")" in line:
                skipping = False
            continue
        if re.match(r"^(import|from)\s+\w", line):
            if "(" in line and ")" not in line:
                skipping = True
            continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def check(source, name):
    problems = []
    for pattern, message in FORBIDDEN:
        for match in pattern.finditer(source):
            line_no = source.count("\n", 0, match.start()) + 1
            problems.append(f"{name}:{line_no}: {message}")
    return problems


def build():
    library = "".join(strip_imports((ROOT / path).read_text(encoding="utf-8")) for path in LIBRARY)
    problems = []
    for entry in ENTRY_POINTS:
        body = (ROOT / entry).read_text(encoding="utf-8")
        header = f"# Собрано scripts/build_nextbot.py из booking/ и {entry}. Не редактировать вручную.\n"
        built = header + library + "\n" + body
        target = ROOT / "dist" / pathlib.Path(entry).name
        target.parent.mkdir(exist_ok=True)
        target.write_text(built, encoding="utf-8")
        compile(built, str(target), "exec")
        problems.extend(check(built, target.name))
    return problems


if __name__ == "__main__":
    found = build()
    if found:
        print("\n".join(found))
        sys.exit(1)
    print("Готово: dist/check_time.py, dist/create_appointment.py")
