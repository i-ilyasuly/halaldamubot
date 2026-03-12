import requests
from config import BOT_TOKEN

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup: payload["reply_markup"] = reply_markup
    
    resp = requests.post(url, json=payload).json()
    if resp.get("ok"):
        return resp["result"]["message_id"]
    return None

def edit_message(chat_id=None, message_id=None, text=None, reply_markup=None, inline_message_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"text": text, "parse_mode": "HTML"}
    if inline_message_id:
        payload["inline_message_id"] = inline_message_id
    else:
        payload["chat_id"] = chat_id
        payload["message_id"] = message_id
    if reply_markup: payload["reply_markup"] = reply_markup
    requests.post(url, json=payload)

# ЖАҢА ФУНКЦИЯ: Тек батырмаларды ғана өзгертеді!
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
    requests.post(url, json=payload)

def answer_callback(callback_query_id, text=None, show_alert=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    requests.post(url, json=payload)

def answer_inline_query(inline_query_id, results, button=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    payload = {"inline_query_id": inline_query_id, "results": results, "cache_time": 300}
    if button:
        payload["button"] = button
    requests.post(url, json=payload)

def download_photo(file_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    resp = requests.get(url).json()
    if not resp.get("ok"): return None
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
        "prices":[{"label": "Premium", "amount": 100}]
    }
    requests.post(url, json=payload)

def answer_pre_checkout_query(pre_checkout_query_id, ok=True, error_message=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerPreCheckoutQuery"
    payload = {"pre_checkout_query_id": pre_checkout_query_id, "ok": ok}
    if not ok and error_message:
        payload["error_message"] = error_message
    requests.post(url, json=payload)
