import requests
from config import BOT_TOKEN

def send_message(chat_id, text, reply_markup=None, message_effect_id=None, reply_to_message_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "link_preview_options": {"is_disabled": True}}
    
    if reply_markup: 
        payload["reply_markup"] = reply_markup
        
    if message_effect_id: 
        payload["message_effect_id"] = str(message_effect_id)
        
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}
    
    resp = requests.post(url, json=payload).json()
    
    if resp.get("ok"):
        return resp["result"]["message_id"]

    # Эффект қабылдамаса — эффектсіз қайта жіберу
    if message_effect_id:
        print(f"Telegram Эффект қабылдамады: {resp}")
        del payload["message_effect_id"]
        resp = requests.post(url, json=payload).json()
        if resp.get("ok"):
            return resp["result"]["message_id"]

    print(f"[send_message] Қате: {resp}")
    return None


def send_message_draft(chat_id, text, draft_id):
    """
    Bot API 9.5 — streaming AI жауабы үшін.
    Бір draft_id арқылы бірнеше рет шақырылады,
    пайдаланушыда мәтін бірте-бірте пайда болады.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessageDraft"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "draft_id": draft_id
    }
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        # Қате болса үнсіз өтеміз — streaming үзілмесін
        print(f"[send_message_draft] Қате: {resp.get('description', '')}")
        return False
    return True


def send_photo_message(chat_id, photo_url, caption, reply_markup=None,
                       message_effect_id=None, reply_to_message_id=None):
    """
    Сурет + мәтін хабары жіберу (мекеме суреті үшін).
    Сурет жүктелмесе немесе қате болса — тікелей send_message шақырылады.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if message_effect_id:
        payload["message_effect_id"] = str(message_effect_id)
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}

    resp = requests.post(url, json=payload).json()

    if resp.get("ok"):
        return resp["result"]["message_id"]

    # Сурет жүктелмесе — fallback: тікелей мәтін хабары
    print(f"[send_photo_message] Сурет жүктелмеді, мәтін жіберіледі: {resp.get('description', '')}")
    return send_message(chat_id, caption, reply_markup=reply_markup,
                        message_effect_id=message_effect_id,
                        reply_to_message_id=reply_to_message_id)

def edit_message(chat_id=None, message_id=None, text=None, reply_markup=None, inline_message_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"text": text, "parse_mode": "HTML",
               "link_preview_options": {"is_disabled": True}}
    if inline_message_id:
        payload["inline_message_id"] = inline_message_id
    else:
        payload["chat_id"] = chat_id
        payload["message_id"] = message_id
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[edit_message] Қате: {resp}")

def edit_reply_markup(chat_id=None, message_id=None, reply_markup=None, inline_message_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup"
    payload = {}
    if inline_message_id:
        payload["inline_message_id"] = inline_message_id
    else:
        payload["chat_id"] = chat_id
        payload["message_id"] = message_id
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[edit_reply_markup] Қате: {resp}")

def answer_callback(callback_query_id, text=None, show_alert=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[answer_callback] Қате: {resp}")

def answer_inline_query(inline_query_id, results, button=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    payload = {"inline_query_id": inline_query_id, "results": results, "cache_time": 300}
    if button:
        payload["button"] = button
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[answer_inline_query] Қате: {resp}")

def download_photo(file_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    resp = requests.get(url).json()
    if not resp.get("ok"):
        print(f"[download_photo] getFile қатесі: {resp}")
        return None
    file_path = resp["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    return requests.get(download_url).content

def send_invoice(chat_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendInvoice"
    payload = {
        "chat_id": chat_id,
        "title": "⭐️ Premium Жазылым (30 күн)",
        "description": "Шексіз іздеу, суретпен тану және жақын маңдағы орындарды шектеусіз көру мүмкіндігі!",
        "payload": "premium_30_days",
        "provider_token": "", 
        "currency": "XTR",    
        "prices": [{"label": "Premium", "amount": 100}]
    }
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[send_invoice] Қате: {resp}")

def answer_pre_checkout_query(pre_checkout_query_id, ok=True, error_message=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerPreCheckoutQuery"
    payload = {"pre_checkout_query_id": pre_checkout_query_id, "ok": ok}
    if not ok and error_message:
        payload["error_message"] = error_message
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[answer_pre_checkout_query] Қате: {resp}")

def send_chat_action(chat_id, action="typing"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendChatAction"
    payload = {"chat_id": chat_id, "action": action}
    requests.post(url, json=payload)

def delete_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[delete_message] Қате: {resp}")

def set_message_reaction(chat_id, message_id, emoji, is_big=True):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}],
        "is_big": is_big
    }
    requests.post(url, json=payload)

def send_gift_invoice(chat_id, gift_type, recipient_username=None, buyer_name=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendInvoice"

    # Payload 128 символдан аспауы керек — buyer_name-ді қысқартамыз
    safe_name = (buyer_name or "")[:40].strip()

    if gift_type == "inline":
        desc = "Төлем жасалғаннан кейін сіз сыйлықты досыңыздың чатына тікелей жібере аласыз."
        invoice_payload = f"gift_premium_30_days_inline:{safe_name}"
    elif gift_type == "username" and recipient_username:
        clean = recipient_username.lstrip("@")[:32]
        desc = f"Төлем жасалғаннан кейін @{clean} пайдаланушысына сыйлық автоматты жіберіледі."
        invoice_payload = f"gift_premium_30_days_username:{clean}:{safe_name}"
    else:
        desc = "Төлем жасалғаннан кейін сізге арнайы сыйлық сілтемесі беріледі."
        invoice_payload = f"gift_premium_30_days_link:{safe_name}"

    payload = {
        "chat_id": chat_id,
        "title": "🎁 Premium Сыйлық (30 күн)",
        "description": desc,
        "payload": invoice_payload,
        "provider_token": "", 
        "currency": "XTR",    
        "prices": [{"label": "Premium Сыйлық", "amount": 100}]
    }
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[send_gift_invoice] Қате: {resp}")

def send_tariff_invoice(chat_id, tariff_id, buyer_name=None):
    """Белгілі тарифке шот жіберу — өзіне алу үшін"""
    from tariffs import get_tariff_by_id
    t = get_tariff_by_id(tariff_id)
    if not t:
        print(f"[send_tariff_invoice] Тариф табылмады: {tariff_id}")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendInvoice"
    if t["discount"] > 0:
        desc = f"Шексіз іздеу, суретпен тану және жақын маңдағы орындарды {t['label']} бойы шектеусіз пайдаланыңыз! ({t['discount']}% үнемдеу)"
    else:
        desc = "Шексіз іздеу, суретпен тану және жақын маңдағы орындарды шектеусіз көру мүмкіндігі!"
    payload = {
        "chat_id": chat_id,
        "title": f"⭐️ Premium — {t['label']}",
        "description": desc,
        "payload": tariff_id,
        "provider_token": "",
        "currency": "XTR",
        "prices": [{"label": f"Premium {t['label']}", "amount": t['stars']}]
    }
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[send_tariff_invoice] Қате: {resp}")


def send_gift_tariff_invoice(chat_id, tariff_id, gift_type, recipient_username=None, buyer_name=None):
    """Белгілі тарифке сыйлық шоты"""
    from tariffs import get_tariff_by_id
    t = get_tariff_by_id(tariff_id)
    if not t:
        print(f"[send_gift_tariff_invoice] Тариф табылмады: {tariff_id}")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendInvoice"
    safe_name = (buyer_name or "")[:40].strip()

    if gift_type == "inline":
        desc = f"Төлем жасалғаннан кейін сіз сыйлықты досыңыздың чатына тікелей жібере аласыз ({t['label']})."
        invoice_payload = f"gift_{tariff_id}_inline:{safe_name}"
    elif gift_type == "username" and recipient_username:
        clean = recipient_username.lstrip("@")[:32]
        desc = f"Төлем жасалғаннан кейін @{clean} пайдаланушысына {t['label']} Premium сыйлық жіберіледі."
        invoice_payload = f"gift_{tariff_id}_username:{clean}:{safe_name}"
    else:
        desc = f"Төлем жасалғаннан кейін сізге {t['label']} Premium сыйлық сілтемесі беріледі."
        invoice_payload = f"gift_{tariff_id}_link:{safe_name}"

    payload = {
        "chat_id": chat_id,
        "title": f"🎁 Premium Сыйлық — {t['label']}",
        "description": desc,
        "payload": invoice_payload,
        "provider_token": "",
        "currency": "XTR",
        "prices": [{"label": f"Premium Сыйлық {t['label']}", "amount": t['stars']}]
    }
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[send_gift_tariff_invoice] Қате: {resp}")
