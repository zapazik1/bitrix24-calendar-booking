# Точка входа функции create_appointment в NextBot.
# scripts/build_nextbot.py ставит перед этим файлом код из booking/ без строк import.
# args["bitrixEntityId"] NextBot передаёт сам: сделка диалога вида "DEAL_123".

CONFIG = dict(DEFAULT_CONFIG)
CONFIG.update({
    "webhook_url": "https://example.bitrix24.ru/rest/1/REPLACE_ME/",
    "clinic_tz": "Asia/Yekaterinburg",
    "booking_template_id": 0,
})


def deal_id_from_entity(value):
    text = str(value or "")
    if text.startswith("DEAL_"):
        text = text[len("DEAL_"):]
    return int(text) if text.isdigit() else None


deal_id = deal_id_from_entity(args.get("bitrixEntityId"))
if deal_id is None:
    result = error_result("Нет сделки в Bitrix24 для этого диалога.")
else:
    result = create_appointment(
        CONFIG,
        args.get("doctor_name", ""),
        args.get("appointment_datetime", ""),
        int(args.get("duration_minutes") or 20),
        deal_id,
        args.get("service_name", ""),
    )
