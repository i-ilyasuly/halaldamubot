import requests
from bot_sender import send_message, send_invoice, answer_pre_checkout_query, send_gift_invoice
from db_core import grant_premium, record_payment, log_to_bigquery, create_gift_code
from config import BOT_TOKEN

def get_premium_keyboard():
    return {
        "inline_keyboard": [[{"text": "⭐️ Premium алу (100 ⭐️)", "callback_data": "buy_premium"}]]
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
    payment_info = message["successful_payment"]

    amount = payment_info["total_amount"]
    payload = payment_info["invoice_payload"]
    charge_id = payment_info["telegram_payment_charge_id"]

    record_payment(chat_id, username, amount, payload, charge_id)
    log_to_bigquery(chat_id, "payment", f"{amount} Stars", "Сәтті төлем")

    # 1. ӨЗІНЕ АЛСА
    if payload == "premium_30_days":
        grant_premium(chat_id, days=30)
        success_text = (
            "🎉 <b>Төлем сәтті өтті! Құттықтаймыз!</b>\n\n"
            "Сіз енді <b>Premium</b> қолданушысыз 👑\n"
            "Алдағы 30 күн бойы барлық шектеулер алынып тасталды. Жобамызды қолдағаныңыз үшін үлкен рақмет! ❤️"
        )
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")

    # 2. СІЛТЕМЕ АРҚЫЛЫ СЫЙЛЫҚ
    elif payload.startswith("gift_premium_30_days_link:"):
        buyer_name = payload.split(":", 1)[1] or username
        code = create_gift_code(chat_id, buyer_name)
        bot_username = "alladalbot"
        gift_link = f"https://t.me/{bot_username}?start={code}"
        success_text = (
            "🎁 <b>Сыйлық сәтті сатып алынды!</b>\n\n"
            "Төмендегі сілтемені досыңызға жіберіңіз:\n\n"
            f"👉 {gift_link}\n\n"
            "<i>Ескерту: Бұл сілтемені тек 1 адам ғана қолдана алады!</i>"
        )
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")

    # 3. ТЕЛЕГРАМ ИНЛАЙН АРҚЫЛЫ СЫЙЛЫҚ
    elif payload.startswith("gift_premium_30_days_inline:"):
        buyer_name = payload.split(":", 1)[1] or username
        code = create_gift_code(chat_id, buyer_name)
        success_text = (
            "🎁 <b>Сыйлық сәтті сатып алынды!</b>\n\n"
            "Төмендегі батырманы басып, досыңызды таңдаңыз!\n\n"
            "<i>Ескерту: Бұл сыйлықты тек 1 адам ғана аша алады!</i>"
        )
        gift_markup = {
            "inline_keyboard": [[
                {"text": "🎁 Сыйлықты жіберу", "switch_inline_query": f"giftbox_{code}"}
            ]]
        }
        send_message(chat_id, success_text, reply_markup=gift_markup, message_effect_id="5046509860389126442")

    # 4. @USERNAME АРҚЫЛЫ СЫЙЛЫҚ
    elif payload.startswith("gift_premium_30_days_username:"):
        # payload: gift_premium_30_days_username:aibek_kz:Аяулым
        parts = payload.split(":")
        recipient_username = parts[1] if len(parts) > 1 else ""
        buyer_name = parts[2] if len(parts) > 2 else username
        if not buyer_name:
            buyer_name = username

        bot_username = "alladalbot"
        recipient_id = get_telegram_user_id_by_username(recipient_username)
        direct_sent = False

        if recipient_id:
            code = create_gift_code(chat_id, buyer_name, recipient_username=recipient_username)
            gift_link = f"https://t.me/{bot_username}?start={code}"
            recipient_text = (
                f"🎁 <b>Сізге сыйлық келді!</b>\n\n"
                f"<b>{buyer_name}</b> сізге <b>30 күн Premium</b> сыйлады!\n\n"
                f"Сыйлықты қабылдау үшін төмендегі батырманы басыңыз 👇\n\n"
                f"<i>Батырманы басқан сәтте Premium 30 күнге автоматты іске қосылады.</i>"
            )
            recipient_markup = {
                "inline_keyboard": [[
                    {"text": "🎁 Сыйлықты қабылдау", "url": gift_link}
                ]]
            }
            result = send_message(recipient_id, recipient_text, reply_markup=recipient_markup, message_effect_id="5046509860389126442")
            direct_sent = result is not None
        else:
            code = create_gift_code(chat_id, buyer_name, recipient_username=recipient_username)
            gift_link = f"https://t.me/{bot_username}?start={code}"

        if direct_sent:
            success_text = (
                f"🎁 <b>Сыйлық сәтті жіберілді!</b>\n\n"
                f"<b>@{recipient_username}</b> пайдаланушысына хабар жетті.\n"
                f"Ол батырманы басқан сәтте Premium автоматты іске қосылады.\n\n"
                f"<i>Запасқа сілтеме:</i>\n👉 {gift_link}\n\n"
                f"<i>Бұл сілтемені тек 1 адам ғана қолдана алады!</i>"
            )
        else:
            success_text = (
                f"🎁 <b>Сыйлық сәтті сатып алынды!</b>\n\n"
                f"<b>@{recipient_username}</b> ботқа бұрын жазбағандықтан хабар тікелей жете алмады.\n\n"
                f"📎 Сілтемені досыңызға жіберіңіз:\n👉 {gift_link}\n\n"
                f"⭐️ <b>Маңызды:</b> Досыңыз сілтемені басқан сәтте Premium <b>автоматты 30 күнге іске қосылады!</b>\n\n"
                f"<i>Бұл сілтемені тек 1 адам ғана қолдана алады!</i>"
            )
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")
