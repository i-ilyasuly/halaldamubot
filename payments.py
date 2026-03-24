import requests
from bot_sender import send_message, send_invoice, answer_pre_checkout_query, send_gift_invoice
from db_core import grant_premium, record_payment, log_to_bigquery, create_gift_code
from config import BOT_TOKEN

def get_premium_keyboard(lang='kz'):
    from translations import t
    return {
        "inline_keyboard": [[{"text": t("btn_premium_buy_inline", lang), "callback_data": "buy_premium", "style": "success"}]]
    }

def handle_buy_premium_callback(chat_id, callback_id):
    send_invoice(chat_id)

def process_pre_checkout(update):
    query_id = update["pre_checkout_query"]["id"]
    answer_pre_checkout_query(query_id, ok=True)

def get_telegram_user_id_by_username(username):
    clean = username.lstrip("@")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
    resp = requests.get(url, params={"chat_id": f"@{clean}"}).json()
    if resp.get("ok"):
        return resp["result"].get("id")
    return None

def process_successful_payment(message):
    chat_id = message["chat"]["id"]
    username = message["chat"].get("username", message["chat"].get("first_name", "Жақсы адам"))
    from db_core import get_user_language
    from translations import t
    lang = get_user_language(chat_id)
    payment_info = message["successful_payment"]

    amount = payment_info["total_amount"]
    payload = payment_info["invoice_payload"]
    charge_id = payment_info["telegram_payment_charge_id"]

    record_payment(chat_id, username, amount, payload, charge_id)

    # Төлем түрін анықтаймыз
    from tariffs import get_tariff_by_id
    if get_tariff_by_id(payload):
        payment_type = "own"
    elif "_link:" in payload:
        payment_type = "gift_link"
    elif "_inline:" in payload:
        payment_type = "gift_inline"
    elif "_username:" in payload:
        payment_type = "gift_username"
    else:
        payment_type = "unknown"

    log_to_bigquery(chat_id, "payment", f"{amount} Stars", "Сәтті төлем",
                    is_premium=True, stars_spent=amount, platform=payment_type)

    # 1. ӨЗІНЕ АЛСА — барлық тарифтер
    own_tariff = get_tariff_by_id(payload)
    if own_tariff:
        grant_premium(chat_id, days=own_tariff["days"])
        success_text = t("payment_success_own", lang, label=own_tariff["label"])
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")

    # 2. СІЛТЕМЕ АРҚЫЛЫ СЫЙЛЫҚ (кез келген тариф)
    elif "_link:" in payload and payload.startswith("gift_premium_"):
        parts = payload.split("_link:", 1)
        tariff_id = parts[0].lstrip("gift_")  # premium_30_days т.б.
        buyer_name = parts[1] or username
        from tariffs import get_tariff_by_id
        t_info = get_tariff_by_id(tariff_id) or {"label": "30 күн", "days": 30}
        code = create_gift_code(chat_id, buyer_name, tariff_id=tariff_id)
        bot_username = "halaldamu_bot"
        gift_link = f"https://t.me/{bot_username}?start={code}"
        success_text = t("payment_gift_link", lang, label=t_info["label"], link=gift_link)
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")

    # 3. ТЕЛЕГРАМ ИНЛАЙН АРҚЫЛЫ СЫЙЛЫҚ (кез келген тариф)
    elif "_inline:" in payload and payload.startswith("gift_premium_"):
        parts = payload.split("_inline:", 1)
        tariff_id = parts[0].lstrip("gift_")
        buyer_name = parts[1] or username
        from tariffs import get_tariff_by_id
        t_info = get_tariff_by_id(tariff_id) or {"label": "30 күн", "days": 30}
        code = create_gift_code(chat_id, buyer_name, tariff_id=tariff_id)
        success_text = t("payment_gift_inline", lang, label=t_info["label"])
        gift_markup = {
            "inline_keyboard": [[
                {"text": t("payment_btn_send_gift", lang), "switch_inline_query": f"giftbox_{code}", "style": "success"}
            ]]
        }
        send_message(chat_id, success_text, reply_markup=gift_markup, message_effect_id="5046509860389126442")

    # 4. @USERNAME АРҚЫЛЫ СЫЙЛЫҚ (кез келген тариф)
    elif "_username:" in payload and payload.startswith("gift_premium_"):
        # payload: gift_premium_30_days_username:aibek_kz:Аяулым
        # tariff_id = premium_30_days, recipient = aibek_kz, buyer_name = Аяулым
        pre, rest = payload.split("_username:", 1)
        tariff_id = pre.lstrip("gift_")   # premium_30_days
        rest_parts = rest.split(":", 1)
        recipient_username = rest_parts[0]
        buyer_name = rest_parts[1] if len(rest_parts) > 1 else username
        from tariffs import get_tariff_by_id
        t_info = get_tariff_by_id(tariff_id) or {"label": "30 күн", "days": 30}
        if not buyer_name:
            buyer_name = username

        bot_username = "halaldamu-bot"
        recipient_id = get_telegram_user_id_by_username(recipient_username)
        direct_sent = False

        if recipient_id:
            code = create_gift_code(chat_id, buyer_name, recipient_username=recipient_username, tariff_id=tariff_id)
            gift_link = f"https://t.me/{bot_username}?start={code}"
            from db_core import get_user_language as _get_lang
            recipient_lang = _get_lang(recipient_id)
            recipient_text = t("recipient_gift_text", recipient_lang, buyer=buyer_name, label=t_info["label"])
            recipient_markup = {
                "inline_keyboard": [[
                    {"text": t("btn_accept_gift", recipient_lang), "url": gift_link, "style": "success"}
                ]]
            }
            result = send_message(recipient_id, recipient_text, reply_markup=recipient_markup, message_effect_id="5046509860389126442")
            direct_sent = result is not None
        else:
            code = create_gift_code(chat_id, buyer_name, recipient_username=recipient_username, tariff_id=tariff_id)
            gift_link = f"https://t.me/{bot_username}?start={code}"

        if direct_sent:
            success_text = t("payment_gift_sent_direct", lang, recipient=recipient_username, link=gift_link)
        else:
            success_text = t("payment_gift_no_direct", lang, recipient=recipient_username, link=gift_link, label=t_info["label"])
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")
