# Барлық тарифтер бір жерде — өзгерту оңай болсын
# Теңге бағасы жуықтап көрсетіледі (~), нақты баға Stars сатып алу кезінде белгілі болады

TARIFFS = [
    {
        "id": "premium_30_days",
        "days": 30,
        "label": "1 ай",
        "stars": 100,
        "discount": 0,
        "emoji": "🥉",
        "kzt": "~1 000"
    },
    {
        "id": "premium_90_days",
        "days": 90,
        "label": "3 ай",
        "stars": 250,
        "discount": 17,
        "emoji": "🥈",
        "kzt": "~2 300"
    },
    {
        "id": "premium_180_days",
        "days": 180,
        "label": "6 ай",
        "stars": 500,
        "discount": 17,
        "emoji": "🥇",
        "kzt": "~4 600"
    },
    {
        "id": "premium_365_days",
        "days": 365,
        "label": "12 ай",
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

def get_tariff_keyboard(callback_prefix="buy"):
    """
    Тариф таңдау inline батырмалары.
    callback_prefix: 'buy' немесе 'gift' — сыйлық/өзіне алу үшін
    """
    keyboard = []
    for t in TARIFFS:
        if t["discount"] > 0:
            btn_text = f"{t['emoji']} {t['label']} — {t['stars']} ⭐ ({t['kzt']} ₸, -{t['discount']}%)"
        else:
            btn_text = f"{t['emoji']} {t['label']} — {t['stars']} ⭐ ({t['kzt']} ₸)"
        keyboard.append([{"text": btn_text, "callback_data": f"{callback_prefix}_tariff:{t['id']}"}])
    return {"inline_keyboard": keyboard}

def get_tariff_description(tariff_id):
    t = get_tariff_by_id(tariff_id)
    if not t:
        return ""
    if t["discount"] > 0:
        return f"{t['emoji']} <b>{t['label']}</b> — {t['stars']} ⭐ <i>({t['kzt']} ₸, -{t['discount']}% үнемдеу)</i>"
    return f"{t['emoji']} <b>{t['label']}</b> — {t['stars']} ⭐ <i>({t['kzt']} ₸)</i>"
