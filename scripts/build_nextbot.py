"""Собирает однофайловые функции для NextBot.

Платформа принимает функцию одним файлом: пакет booking/ туда не положить.
Сборщик склеивает модули пакета с точкой входа, поднимает import стандартной
библиотеки и requests наверх, убирает import самого пакета и проверяет, что файл компилируется.

Запуск: python scripts/build_nextbot.py
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = ["booking/timezones.py", "booking/slots.py", "booking/doctors.py", "booking/bitrix.py", "booking/service.py"]
ENTRY_POINTS = ["nextbot/check_time.py", "nextbot/create_appointment.py"]
IMPORT_RE = re.compile(r"^(import \w[\w.]*|from [\w.]+ import [^(]+)$")


def split_imports(source):
    """-> (внешние import, тело без import). Многострочные import пакета booking вырезаются целиком."""
    imports, body, skipping = [], [], False
    for line in source.splitlines():
        if skipping:
            skipping = ")" not in line
            continue
        if line.startswith("from booking"):
            skipping = "(" in line and ")" not in line
            continue
        if IMPORT_RE.match(line):
            imports.append(line)
            continue
        body.append(line)
    return imports, "\n".join(body).strip() + "\n"


def build():
    built = []
    parts = [split_imports((ROOT / m).read_text(encoding="utf-8")) for m in MODULES]
    for entry in ENTRY_POINTS:
        entry_imports, entry_body = split_imports((ROOT / entry).read_text(encoding="utf-8"))
        imports = sorted(set(entry_imports + [i for p in parts for i in p[0]]))
        text = "\n\n".join(
            [f"# Собрано scripts/build_nextbot.py из booking/ и {entry}. Не редактировать вручную.",
             "\n".join(imports)] + [p[1] for p in parts] + [entry_body]
        )
        target = ROOT / "dist" / pathlib.Path(entry).name
        target.parent.mkdir(exist_ok=True)
        target.write_text(text, encoding="utf-8")
        compile(text, str(target), "exec")
        built.append(target)
    return built


if __name__ == "__main__":
    for path in build():
        print(path.relative_to(ROOT))
