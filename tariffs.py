# Барлық тарифтер бір жерде — өзгерту оңай болсын
# Теңге бағасы жуықтап көрсетіледі (~), нақты баға Stars сатып алу кезінде белгілі болады

TARIFFS = [
    {
        "id": "premium_30_days",
        "days": 30,
        "label": "1 ай",
        "label_ru": "1 месяц",
        "stars": 100,
        "discount": 0,
        "emoji": "🥉",
        "kzt": "~1 000"
    },
    {
        "id": "premium_90_days",
        "days": 90,
        "label": "3 ай",
        "label_ru": "3 месяца",
        "stars": 250,
        "discount": 17,
        "emoji": "🥈",
        "kzt": "~2 300"
    },
    {
        "id": "premium_180_days",
        "days": 180,
        "label": "6 ай",
        "label_ru": "6 месяцев",
        "stars": 500,
        "discount": 17,
        "emoji": "🥇",
        "kzt": "~4 600"
    },
    {
        "id": "premium_365_days",
        "days": 365,
        "label": "12 ай",
        "label_ru": "12 месяцев",
        "stars": 1000,
        "discount": 17,
        "emoji": "💎",
        "kzt": "~9 100"
    },
]

def get_tariff_by_id(tariff_id):
    for t in TARIFFS:
        if t["id"] == tariff_id:
            return t
    return None

def get_tariff_keyboard(callback_prefix="buy", lang="kz"):
    keyboard = []
    for t in TARIFFS:
        label = t["label_ru"] if lang == "ru" else t["label"]
        if t["discount"] > 0:
            btn_text = f"{t['emoji']} {label} — {t['stars']} ⭐ ({t['kzt']} ₸, -{t['discount']}%)"
        else:
            btn_text = f"{t['emoji']} {label} — {t['stars']} ⭐ ({t['kzt']} ₸)"
        keyboard.append([{"text": btn_text, "callback_data": f"{callback_prefix}_tariff:{t['id']}", "style": "success"}])
    return {"inline_keyboard": keyboard}

def get_tariff_description(tariff_id, lang="kz"):
    t = get_tariff_by_id(tariff_id)
    if not t:
        return ""
    label = t["label_ru"] if lang == "ru" else t["label"]
    if t["discount"] > 0:
        return f"{t['emoji']} <b>{label}</b> — {t['stars']} ⭐ <i>({t['kzt']} ₸, -{t['discount']}% үнемдеу)</i>"
    return f"{t['emoji']} <b>{label}</b> — {t['stars']} ⭐ <i>({t['kzt']} ₸)</i>"
