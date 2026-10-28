import requests
from functools import partial
from contextvars import ContextVar

# Тұрақты TCP/TLS байланыс үшін Keep-Alive қолдайтын сессия (Connection Pool)
session = requests.Session()

# HTTP сұраныстардың қатып қалуын болдырмау үшін дефолттық тайм-аут орнату (5 секунд)
# 5 секундтан асса, сұраныс автоматты түрде үзіледі және ағын босатылады.
session.post = partial(session.post, timeout=5)
session.get = partial(session.get, timeout=5)

# Барлық файлдарда requests.post және requests.get қолдану үшін модуль деңгейінде алмастыру
requests.post = session.post
requests.get = session.get

message_thread_id_var = ContextVar("message_thread_id", default=None)

from config import BOT_TOKEN

TG_MAX_LENGTH = 4096  # Telegram хабарлама лимиті

def _truncate_text(text, limit=TG_MAX_LENGTH):
    """Мәтін Telegram лимитінен асса — қысқартады (HTML тегтерді қауіпсіз жабады)."""
    if len(text) <= limit:
        return text
    truncated = text[:limit - 30]
    # Жабылмаған HTML тегтерді тазалау
    open_tags = []
    import re
    for m in re.finditer(r'<(/?)(\w+)', truncated):
        if m.group(1):  # closing tag
            if open_tags and open_tags[-1] == m.group(2):
                open_tags.pop()
        else:
            open_tags.append(m.group(2))
    suffix = "\n\n<i>… (мәтін қысқартылды)</i>"
    for tag in reversed(open_tags):
        suffix = f"</{tag}>" + suffix
    return truncated + suffix


def send_message(chat_id, text, reply_markup=None, message_effect_id=None, reply_to_message_id=None, message_thread_id=None):
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "disable_web_page_preview": True
    }

    if message_thread_id:
        payload["message_thread_id"] = message_thread_id
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if message_effect_id:
        payload["message_effect_id"] = str(message_effect_id)
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}

    for attempt in range(4):
        resp = requests.post(url, json=payload).json()
        if resp.get("ok"):
            return resp["result"]["message_id"]

        desc = resp.get("description", "").lower()
        print(f"[send_message] Сынақ {attempt+1} сәтсіз: {desc}")

        # 1. Мәтін тым ұзын болса — қысқартып қайталап көру
        if "too long" in desc:
            print(f"[send_message] Мәтінді қысқарту...")
            payload["text"] = _truncate_text(payload["text"])
            continue

        # 2. Хабарлама эффектісін қабылдамаса — эффектсіз қайталап көру
        if "message effect" in desc or "can't use message effects" in desc:
            print(f"[send_message] Эффектті өшіру...")
            payload.pop("message_effect_id", None)
            continue

        # 3. Reply хабарлама табылмаса — reply-сіз қайталап көру
        if "reply" in desc or "not found" in desc:
            print(f"[send_message] Reply параметрін өшіру...")
            payload.pop("reply_parameters", None)
            continue

        # Басқа белгісіз қателіктер кезінде циклді тоқтату
        break

    print(f"[send_message] Жіберу сәтсіз аяқталды: {payload.get('text', '')[:100]}...")
    return None


def send_message_draft(chat_id, text, draft_id, message_thread_id=None):
    """
    Bot API 9.5 — streaming AI жауабы үшін.
    Бір draft_id арқылы бірнеше рет шақырылады,
    пайдаланушыда мәтін бірте-бірте пайда болады.
    """
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessageDraft"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "draft_id": draft_id
    }
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        # Қате болса үнсіз өтеміз — streaming үзілмесін
        print(f"[send_message_draft] Қате: {resp.get('description', '')}")
        return False
    return True


def send_photo_message(chat_id, photo_url, caption, reply_markup=None,
                       message_effect_id=None, reply_to_message_id=None, message_thread_id=None):
    """
    Сурет + мәтін хабары жіберу (мекеме суреті үшін).
    Сурет жүктелмесе немесе қате болса — тікелей send_message шақырылады.
    Caption лимиті 1024 символ — асса send_message-ге ауысады.
    """
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
    # sendPhoto caption лимиті: 1024 символ
    if len(caption) > 1024:
        print(f"[send_photo_message] Caption тым ұзын ({len(caption)}), send_message-ге ауысады")
        return send_message(chat_id, caption, reply_markup=reply_markup,
                            message_effect_id=message_effect_id,
                            reply_to_message_id=reply_to_message_id,
                            message_thread_id=message_thread_id)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if message_effect_id:
        payload["message_effect_id"] = str(message_effect_id)
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}

    for attempt in range(4):
        resp = requests.post(url, json=payload).json()
        if resp.get("ok"):
            return resp["result"]["message_id"]

        desc = resp.get("description", "").lower()
        print(f"[send_photo_message] Сынақ {attempt+1} сәтсіз: {desc}")

        # 1. Хабарлама эффектісін қабылдамаса — эффектсіз қайталап көру
        if "message effect" in desc or "can't use message effects" in desc:
            print(f"[send_photo_message] Эффектті өшіру...")
            payload.pop("message_effect_id", None)
            continue

        # 2. Reply хабарлама табылмаса — reply-сіз қайталап көру
        if "reply" in desc or "not found" in desc:
            print(f"[send_photo_message] Reply параметрін өшіру...")
            payload.pop("reply_parameters", None)
            continue

        # Басқа белгісіз қателіктер кезінде циклді тоқтату
        break

    # Егер сурет жіберу мүлдем сәтсіз болса — мәтін хабарламасына ауысамыз (fallback)
    print(f"[send_photo_message] Сурет жіберу сәтсіз болды, мәтін жіберіледі")
    return send_message(chat_id, caption, reply_markup=reply_markup,
                        message_effect_id=message_effect_id,
                        reply_to_message_id=reply_to_message_id,
                        message_thread_id=message_thread_id)

def send_photo_bytes(chat_id, photo_bytes, caption, message_thread_id=None):
    """
    Сурет bytes арқылы тікелей Telegram-ға жіберу.
    GCS signed URL керек емес — multipart upload.
    """
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if message_thread_id:
        data["message_thread_id"] = message_thread_id
    try:
        resp = requests.post(
            url,
            data=data,
            files={"photo": ("photo.jpg", photo_bytes, "image/jpeg")}
        ).json()
        if resp.get("ok"):
            return resp["result"]["message_id"]
        print(f"[send_photo_bytes] Қате: {resp.get('description', '')}")
        return send_message(chat_id, caption, message_thread_id=message_thread_id)
    except Exception as e:
        print(f"[send_photo_bytes] Қате: {e}")
        return send_message(chat_id, caption, message_thread_id=message_thread_id)


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

def send_invoice(chat_id, message_thread_id=None):
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
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
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id
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

def send_chat_action(chat_id, action="typing", message_thread_id=None):
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendChatAction"
    payload = {"chat_id": chat_id, "action": action}
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id
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

def send_gift_invoice(chat_id, gift_type, recipient_username=None, buyer_name=None, message_thread_id=None):
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
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
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[send_gift_invoice] Қате: {resp}")

def send_tariff_invoice(chat_id, tariff_id, buyer_name=None, message_thread_id=None):
    """Белгілі тарифке шот жіберу — өзіне алу үшін"""
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
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
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[send_tariff_invoice] Қате: {resp}")


def send_gift_tariff_invoice(chat_id, tariff_id, gift_type, recipient_username=None, buyer_name=None, message_thread_id=None):
    """Белгілі тарифке сыйлық шоты"""
    if message_thread_id is None:
        message_thread_id = message_thread_id_var.get()
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
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[send_gift_tariff_invoice] Қате: {resp}")


def leave_chat(chat_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/leaveChat"
    payload = {"chat_id": chat_id}
    resp = requests.post(url, json=payload).json()
    if not resp.get("ok"):
        print(f"[leave_chat] Қате: {resp}")
    return resp.get("ok", False)
