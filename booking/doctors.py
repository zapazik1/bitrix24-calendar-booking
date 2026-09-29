"""Какой календарь открыть: врач по справочнику, а не поиском по ФИО на портале.

Поиск сотрудника по ФИО через user.search ошибался: в профилях к ФИО дописана
специальность, встречаются буквы национальных алфавитов и тёзки. Теперь в CRM есть
справочник «Услуги и врачи» (смарт-процесс): в каждой строке услуги перечислены
врачи и ID сотрудника — владельца календаря. Функция каталога услуг отдаёт агенту
doctor_calendar_id, и запись идёт строго в этот календарь.

Правило: при любой неоднозначности вернуть ошибку с подсказкой агенту, а не угадывать.
"""
LETTERS = str.maketrans("әғқңөұүһіё", "агкноуухие")


def norm_name(value):
    """Регистр, пунктуация, двойные пробелы и буквы вроде «ә» или «ё» не важны."""
    text = str(value or "").lower().translate(LETTERS)
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def name_words_match(query, fio):
    """Каждое слово запроса совпадает со своим словом ФИО с учётом падежа:
    «к Ивановой Анне» -> «Иванова Анна Сергеевна»."""
    free = fio.split()
    for word in query.split():
        hit = None
        for i, candidate in enumerate(free):
            shortest = min(len(word), len(candidate))
            # у коротких слов падеж меняет последнюю букву, у длинных — до двух
            stem = max(3, shortest - 1) if shortest <= 5 else max(4, shortest - 2)
            if word == candidate or (shortest >= 4 and word[:stem] == candidate[:stem]):
                hit = i
                break
        if hit is None:
            return False
        free.pop(hit)
    return True


def build_directory(rows, field_doctor_ids, field_doctor_names):
    """Строки справочника -> {ФИО: множество ID календарей}, {ID календаря: [ФИО]}."""
    by_name, by_id = {}, {}
    for row in rows:
        ids = {int(i) for i in (row.get(field_doctor_ids) or [])}
        for fio in row.get(field_doctor_names) or []:
            fio = str(fio).strip()
            by_name.setdefault(fio, set()).update(ids)
            for calendar_id in ids:
                names = by_id.setdefault(calendar_id, [])
                if fio not in names:
                    names.append(fio)
    return by_name, by_id


def resolve_doctor(directory, calendar_id=None, name=None):
    """-> (ID календаря, ФИО для сообщений, текст ошибки для агента)."""
    by_name, by_id = directory
    name = str(name or "").strip()

    candidates, ids_by_name = [], set()
    if name:
        query = norm_name(name)
        candidates = [fio for fio in by_name if norm_name(fio) == query]
        if not candidates:
            candidates = [fio for fio in by_name if name_words_match(query, norm_name(fio))]
        for fio in candidates:
            ids_by_name |= by_name[fio]

    if calendar_id not in (None, ""):
        try:
            calendar_id = int(str(calendar_id).strip())
        except ValueError:
            return None, None, f"doctor_calendar_id должен быть числом, получено: «{calendar_id}»."
        if calendar_id not in by_id:
            return None, None, ("Такого календаря нет в справочнике. "
                                "Возьми doctor_calendar_id из ответа get_doctors_and_services.")
        if candidates and calendar_id not in ids_by_name:
            return None, None, (f"Врач «{name}» и календарь {calendar_id} ({', '.join(by_id[calendar_id])}) "
                                "не совпадают. Возьми врача и его календарь из одной строки справочника.")
        return calendar_id, name or ", ".join(by_id[calendar_id]), None

    if not name:
        return None, None, "Не передан врач: нужен doctor_calendar_id или doctor_name."
    if not candidates:
        return None, None, f"Врач «{name}» не найден в справочнике услуг и врачей."
    if not ids_by_name:
        return None, None, f"У врача «{name}» нет календаря в Bitrix24: записать через агента нельзя."
    if len(ids_by_name) > 1:
        options = "; ".join(f"{fio} ({', '.join(map(str, sorted(by_name[fio])))})" for fio in candidates)
        return None, None, f"Под «{name}» подходят разные врачи: {options}. Уточни у пациента ФИО."
    return next(iter(ids_by_name)), name, None
