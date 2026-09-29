"""Две функции для ИИ-агента: проверить время и записать пациента.

Ответ каждой функции адресован модели: статус, факты и инструкция, что говорить клиенту.
Главное правило: если запись не подтвердил Bitrix24, агент не подтверждает её клиенту.
"""
import datetime

from booking.bitrix import find_employee_id, get_busy_intervals, start_booking_workflow
from booking.slots import (
    format_datetime,
    is_free,
    parse_datetime,
    shift_timezone,
    suggest_alternatives,
)

DEFAULT_CONFIG = {
    "webhook_url": "https://example.bitrix24.ru/rest/1/REPLACE_ME/",
    "clinic_tz": "Asia/Yekaterinburg",
    "work_start": "08:00",
    "work_end": "20:00",
    "booking_template_id": 0,
    "days_to_search": 3,
    "slots_to_suggest": 3,
}


def parse_clock(value):
    parts = value.split(":")
    return datetime.time(int(parts[0]), int(parts[1]))


def clinic_now(clinic_tz):
    utc_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return shift_timezone(utc_now, "UTC", clinic_tz)


def error_result(reason):
    return {
        "status": "error",
        "reason": reason,
        "instruction": "Запись не создана. Не подтверждай время клиенту. Передай диалог администратору.",
    }


def collect_busy(config, doctor_id, first_day):
    """Занятость врача на несколько дней вперёд: список пар [дата, интервалы]."""
    days = []
    for offset in range(config["days_to_search"]):
        day = first_day + datetime.timedelta(days=offset)
        loaded = get_busy_intervals(config["webhook_url"], doctor_id, day, config["clinic_tz"])
        if not loaded["ok"]:
            return {"ok": False, "days": [], "error": loaded["error"]}
        days.append([day, loaded["busy"]])
    return {"ok": True, "days": days, "error": None}


def validate_request(config, doctor_name, requested, duration_minutes):
    """Проверки до обращения к календарю. Возвращает текст ошибки или None."""
    if not doctor_name:
        return "Не указан врач."
    if requested is None:
        return "Дата и время не распознаны. Ожидается ДД.ММ.ГГГГ ЧЧ:ММ."
    if duration_minutes <= 0:
        return "Длительность приёма должна быть больше нуля."
    if requested < clinic_now(config["clinic_tz"]):
        return "Запрошенное время уже прошло."
    start = parse_clock(config["work_start"])
    end = parse_clock(config["work_end"])
    finish = requested + datetime.timedelta(minutes=duration_minutes)
    if requested.time() < start or finish.time() > end or finish.date() != requested.date():
        return f"Приём возможен с {config['work_start']} до {config['work_end']}."
    return None


def check_time(config, doctor_name, requested_text, duration_minutes):
    """Функция агента check_time: свободно ли время и какие есть варианты."""
    requested = parse_datetime(requested_text)
    problem = validate_request(config, doctor_name, requested, duration_minutes)
    if problem:
        return {"status": "invalid", "reason": problem,
                "instruction": "Уточни у клиента данные и вызови функцию снова."}

    doctor_id = find_employee_id(config["webhook_url"], doctor_name)
    if doctor_id is None:
        return {"status": "invalid", "reason": f"Врач «{doctor_name}» не найден.",
                "instruction": "Уточни у клиента имя врача по списку специалистов."}

    loaded = collect_busy(config, doctor_id, requested.date())
    if not loaded["ok"]:
        return error_result(loaded["error"])

    finish = requested + datetime.timedelta(minutes=duration_minutes)
    if is_free(loaded["days"][0][1], requested, finish):
        return {"status": "free", "slot": format_datetime(requested), "doctor_id": doctor_id,
                "instruction": "Время свободно. Получи согласие клиента и вызови create_appointment."}

    alternatives = suggest_alternatives(
        loaded["days"], requested, duration_minutes,
        parse_clock(config["work_start"]), parse_clock(config["work_end"]),
        limit=config["slots_to_suggest"],
    )
    return {
        "status": "busy",
        "alternatives": [format_datetime(slot) for slot in alternatives],
        "instruction": "Время занято. Предложи клиенту только эти варианты, другого времени не называй."
        if alternatives else "Свободного времени в ближайшие дни нет. Предложи записаться к другому врачу.",
    }


def create_appointment(config, doctor_name, requested_text, duration_minutes, deal_id, service_name):
    """Функция агента create_appointment: повторная проверка и запуск бизнес-процесса записи.

    Время проверяется ещё раз прямо перед записью: между check_time и согласием клиента
    слот мог занять администратор или другой пациент.
    """
    checked = check_time(config, doctor_name, requested_text, duration_minutes)
    if checked["status"] != "free":
        return checked

    requested = parse_datetime(requested_text)
    started = start_booking_workflow(
        config["webhook_url"], config["booking_template_id"], deal_id,
        {
            "Service": service_name,
            "StartDate": requested.isoformat(),
            "Employee": f"user_{checked['doctor_id']}",
            "Duration": duration_minutes,
        },
    )
    if not started["ok"]:
        return error_result(started["error"])
    return {
        "status": "success",
        "slot": format_datetime(requested),
        "workflow_id": started["workflow_id"],
        "instruction": "Запись создана. Подтверди клиенту врача, дату и время.",
    }
