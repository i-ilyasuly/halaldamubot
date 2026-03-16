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
    log_to_bigquery(chat_id, "payment", f"{amount} Stars", "Сәтті төлем", is_premium=True, stars_spent=amount)

    # 1. ӨЗІНЕ АЛСА — барлық тарифтер
    from tariffs import get_tariff_by_id
    own_tariff = get_tariff_by_id(payload)
    if own_tariff:
        grant_premium(chat_id, days=own_tariff["days"])
        success_text = (
            f"🎉 Төлем сәтті өтті! Құттықтаймыз!\n\n"
            f"Енді сіз — Premium қолданушысыз 👑\n"
            f"Алдағы <b>{own_tariff['label']}</b> бойы сізге мыналар қолжетімді:\n\n"
            "✅ Шексіз іздеу — күніне қанша іздесеңіз де\n"
            "📸 Суретпен тану — өнімнің суретін жіберіп тексеріңіз\n"
            "📍 Жақын маңдағы халал мекемелер — орныңызды жіберіп бірден табыңыз\n"
            "🗺 Картадан көру батырмасы — мекемеге бірден жол салыңыз\n"
            "⚡ Реакция мен эффектілер — сұрауыңызға жылдам жауап\n\n"
            "Жобамызды қолдағаныңыз үшін рақмет! ❤️"
        )
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")

    # 2. СІЛТЕМЕ АРҚЫЛЫ СЫЙЛЫҚ (кез келген тариф)
    elif "_link:" in payload and payload.startswith("gift_premium_"):
        parts = payload.split("_link:", 1)
        tariff_id = parts[0].lstrip("gift_")  # premium_30_days т.б.
        buyer_name = parts[1] or username
        from tariffs import get_tariff_by_id
        t = get_tariff_by_id(tariff_id) or {"label": "30 күн", "days": 30}
        code = create_gift_code(chat_id, buyer_name, tariff_id=tariff_id)
        bot_username = "alladalbot"
        gift_link = f"https://t.me/{bot_username}?start={code}"
        success_text = (
            f"🎁 <b>Сыйлық сәтті сатып алынды!</b>\n\n"
            f"Мерзімі: <b>{t['label']}</b>\n"
            "Төмендегі сілтемені досыңызға жіберіңіз:\n\n"
            f"👉 {gift_link}\n\n"
            "<i>Ескерту: Бұл сілтемені тек 1 адам ғана қолдана алады!</i>"
        )
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")

    # 3. ТЕЛЕГРАМ ИНЛАЙН АРҚЫЛЫ СЫЙЛЫҚ (кез келген тариф)
    elif "_inline:" in payload and payload.startswith("gift_premium_"):
        parts = payload.split("_inline:", 1)
        tariff_id = parts[0].lstrip("gift_")
        buyer_name = parts[1] or username
        from tariffs import get_tariff_by_id
        t = get_tariff_by_id(tariff_id) or {"label": "30 күн", "days": 30}
        code = create_gift_code(chat_id, buyer_name, tariff_id=tariff_id)
        success_text = (
            f"🎁 <b>Сыйлық сәтті сатып алынды!</b>\n\n"
            f"Мерзімі: <b>{t['label']}</b>\n"
            "Төмендегі батырманы басып, досыңызды таңдаңыз!\n\n"
            "<i>Ескерту: Бұл сыйлықты тек 1 адам ғана аша алады!</i>"
        )
        gift_markup = {
            "inline_keyboard": [[
                {"text": "🎁 Сыйлықты жіберу", "switch_inline_query": f"giftbox_{code}"}
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
        t = get_tariff_by_id(tariff_id) or {"label": "30 күн", "days": 30}
        if not buyer_name:
            buyer_name = username

        bot_username = "alladalbot"
        recipient_id = get_telegram_user_id_by_username(recipient_username)
        direct_sent = False

        if recipient_id:
            code = create_gift_code(chat_id, buyer_name, recipient_username=recipient_username, tariff_id=tariff_id)
            gift_link = f"https://t.me/{bot_username}?start={code}"
            recipient_text = (
                f"🎁 <b>Сізге сыйлық келді!</b>\n\n"
                f"<b>{buyer_name}</b> сізге <b>{t['label']} Premium</b> сыйлады!\n\n"
                f"Сыйлықты қабылдау үшін төмендегі батырманы басыңыз 👇\n\n"
                f"<i>Батырманы басқан сәтте Premium {t['label']}ге автоматты іске қосылады.</i>"
            )
            recipient_markup = {
                "inline_keyboard": [[
                    {"text": "🎁 Сыйлықты қабылдау", "url": gift_link}
                ]]
            }
            result = send_message(recipient_id, recipient_text, reply_markup=recipient_markup, message_effect_id="5046509860389126442")
            direct_sent = result is not None
        else:
            code = create_gift_code(chat_id, buyer_name, recipient_username=recipient_username, tariff_id=tariff_id)
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
                f"⭐️ <b>Маңызды:</b> Досыңыз сілтемені басқан сәтте Premium <b>автоматты {t['label']}ге іске қосылады!</b>\n\n"
                f"<i>Бұл сілтемені тек 1 адам ғана қолдана алады!</i>"
            )
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")
