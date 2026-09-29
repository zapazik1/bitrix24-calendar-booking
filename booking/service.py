"""Функции агента: check_time и create_appointment.

Ответ — в структурированном контракте платформы: tool_result читает модель,
tags помечают диалог. Главное правило: если Bitrix24 не подтвердил запись,
агент не подтверждает её пациенту.
"""
import datetime
import json

from booking.bitrix import BitrixError
from booking.doctors import resolve_doctor
from booking.slots import free_slots_in_range, is_free
from booking.timezones import clinic_now, format_for_patient, parse_bitrix_datetime

DEFAULT_CONFIG = {
    "clinic_tz": "Asia/Yekaterinburg",       # эталонный пояс: в нём ищем и называем время
    "webhook_owner_tz": "Europe/Moscow",     # пояс пользователя, от имени которого вебхук
    "work_start": datetime.time(8, 0),
    "work_end": datetime.time(20, 0),
    "min_lead_minutes": 30,                  # не предлагать слоты раньше, чем через 30 минут
    "max_slots": 30,
    "directory": {"entity_type_id": 0, "field_doctor_ids": "", "field_doctor_names": ""},
    "booking_template_id": 0,
    "lead_booking_fields": [],               # поля лида, заполненные первой записью
}


def reply(status, instruction, tags=None, **facts):
    payload = {"status": status, **facts, "instruction": instruction}
    result = {"tool_result": json.dumps(payload, ensure_ascii=False, default=str)}
    if tags:
        result["tags"] = tags
    return result


def failed(reason):
    return reply("error", "Запись не создана. Не подтверждай время пациенту, передай диалог администратору.",
                 tags=["booking_error"], reason=reason)


def doctor_from_args(cfg, bitrix, args):
    d = cfg["directory"]
    directory = bitrix.load_directory(d["entity_type_id"], d["field_doctor_ids"], d["field_doctor_names"])
    return resolve_doctor(directory, args.get("doctor_calendar_id"), args.get("doctor_name"))


def check_time(cfg, bitrix, args, now_utc=None):
    """Свободные слоты врача в диапазоне start_time–end_time (ДД.ММ.ГГГГ ЧЧ:ММ)."""
    try:
        doctor_id, doctor_name, problem = doctor_from_args(cfg, bitrix, args)
        if problem:
            return reply("invalid", problem)
        start = parse_bitrix_datetime(args.get("start_time"))
        end = parse_bitrix_datetime(args.get("end_time"))
        duration = int(args.get("appointment_duration") or 0)
        if start is None or end is None or duration <= 0 or start >= end:
            return reply("invalid", "Нужны start_time и end_time в формате ДД.ММ.ГГГГ ЧЧ:ММ и длительность больше нуля.")

        not_before = clinic_now(cfg["clinic_tz"], now_utc) + datetime.timedelta(minutes=cfg["min_lead_minutes"])
        busy = bitrix.busy_intervals(doctor_id, start.date(), end.date(), cfg["clinic_tz"])
        slots = free_slots_in_range(busy, start, end, duration, cfg["work_start"], cfg["work_end"],
                                    not_before=not_before, limit=cfg["max_slots"])
    except BitrixError as exc:
        return failed(str(exc))

    if not slots:
        return reply("no_slots", "В этом диапазоне свободного времени нет. Предложи другой день или другого врача.",
                     doctor=doctor_name)
    return reply("success", "Назови пациенту только эти варианты. Другого времени не предлагай.",
                 doctor=doctor_name, doctor_calendar_id=doctor_id,
                 slots=[format_for_patient(s) for s in slots])


def create_appointment(cfg, bitrix, args, now_utc=None):
    """Запись пациента. Первая запись по лиду — бизнес-процессом, следующие — событием в календаре."""
    try:
        doctor_id, doctor_name, problem = doctor_from_args(cfg, bitrix, args)
        if problem:
            return reply("invalid", problem)
        start = parse_bitrix_datetime(args.get("appointment_datetime"))
        duration = int(args.get("appointment_duration") or 0)
        lead_id = int(str(args.get("bitrixEntityId") or "").replace("LEAD_", "") or 0)
        if start is None or duration <= 0 or not lead_id:
            return reply("invalid", "Нужны время приёма ДД.ММ.ГГГГ ЧЧ:ММ, длительность и лид диалога.")
        end = start + datetime.timedelta(minutes=duration)
        if start < clinic_now(cfg["clinic_tz"], now_utc):
            return reply("invalid", "Это время уже прошло. Предложи пациенту другое.")
        if start.time() < cfg["work_start"] or end.time() > cfg["work_end"] or end.date() != start.date():
            return reply("invalid", "Время вне часов приёма клиники.")

        busy = bitrix.busy_intervals(doctor_id, start.date(), start.date(), cfg["clinic_tz"])
        if not is_free(busy, start, end):
            return reply("busy", "Время уже занято. Вызови check_time и предложи пациенту свободные варианты.")

        service = str(args.get("medical_services") or "")
        if bitrix.lead_has_booking(lead_id, cfg["lead_booking_fields"]):
            # Повторная проверка прямо перед записью: слот могли занять за секунды разговора.
            busy = bitrix.busy_intervals(doctor_id, start.date(), start.date(), cfg["clinic_tz"])
            if not is_free(busy, start, end):
                return reply("busy", "Слот только что заняли. Вызови check_time и предложи другое время.")
            event_id = bitrix.add_calendar_event(
                doctor_id, start, duration, cfg["clinic_tz"],
                name=f"Доп. запись: {service} | лид {lead_id}",
                description="Создано ИИ-агентом",
            )
            booking = {"calendar_event_id": event_id}
        else:
            workflow_id = bitrix.start_booking_workflow(
                cfg["booking_template_id"], lead_id, start, cfg["clinic_tz"], cfg["webhook_owner_tz"],
                {"Service": service, "Employee": f"user_{doctor_id}", "duration": duration},
            )
            booking = {"workflow_id": workflow_id}
    except BitrixError as exc:
        return failed(str(exc))

    if not any(booking.values()):
        return failed("Bitrix24 не вернул ID записи")
    return reply("success", "Запись создана. Подтверди пациенту врача, дату и время.",
                 tags=["booked"], doctor=doctor_name, slot=format_for_patient(start), **booking)
