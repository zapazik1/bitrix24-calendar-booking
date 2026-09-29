# Функция create_appointment для NextBot.
# Параметры: doctor_calendar_id или doctor_name, appointment_datetime (ДД.ММ.ГГГГ ЧЧ:ММ),
# appointment_duration, medical_services. bitrixEntityId платформа передаёт сама: лид диалога.
import datetime

CONFIG = dict(DEFAULT_CONFIG)
CONFIG.update({
    "webhook_url": "https://example.bitrix24.ru/rest/1/REPLACE_ME/",
    "directory": {"entity_type_id": 0, "field_doctor_ids": "ufCrm0Doctors", "field_doctor_names": "ufCrm0DoctorFio"},
    "booking_template_id": 0,
    "lead_booking_fields": ["UF_CRM_BOOKING_DATE"],
})

result = create_appointment(CONFIG, Bitrix(CONFIG["webhook_url"]), args)
