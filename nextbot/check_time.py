# Функция check_time для NextBot.
# Параметры, которые агент заполняет из диалога:
#   doctor_calendar_id    ID календаря из ответа get_doctors_and_services (предпочтительно)
#   doctor_name           ФИО врача, запасной путь
#   appointment_duration  длительность услуги в минутах
#   start_time, end_time  диапазон поиска, ДД.ММ.ГГГГ ЧЧ:ММ
import datetime

CONFIG = dict(DEFAULT_CONFIG)
CONFIG.update({
    "webhook_url": "https://example.bitrix24.ru/rest/1/REPLACE_ME/",
    "directory": {"entity_type_id": 0, "field_doctor_ids": "ufCrm0Doctors", "field_doctor_names": "ufCrm0DoctorFio"},
})

result = check_time(CONFIG, Bitrix(CONFIG["webhook_url"]), args)
