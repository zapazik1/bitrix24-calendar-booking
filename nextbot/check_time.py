# Точка входа функции check_time в NextBot.
# scripts/build_nextbot.py ставит перед этим файлом код из booking/ без строк import.
# Параметры, которые агент заполняет из диалога:
#   args["doctor_name"]           ФИО врача из справочника
#   args["appointment_datetime"]  ДД.ММ.ГГГГ ЧЧ:ММ
#   args["duration_minutes"]      длительность услуги

CONFIG = dict(DEFAULT_CONFIG)
CONFIG.update({
    "webhook_url": "https://example.bitrix24.ru/rest/1/REPLACE_ME/",
    "clinic_tz": "Asia/Yekaterinburg",
})

result = check_time(
    CONFIG,
    args.get("doctor_name", ""),
    args.get("appointment_datetime", ""),
    int(args.get("duration_minutes") or 20),
)
