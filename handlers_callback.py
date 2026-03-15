from bot_sender import send_message, edit_message, edit_reply_markup, answer_callback, set_message_reaction, send_gift_invoice
from db_core import set_user_gender, log_to_bigquery, get_item_by_id, check_access
from search_logic import get_nearby_companies
from formatters import format_detail_message
from payments import handle_buy_premium_callback
from gift_state import set_awaiting_username, clear_state, get_pending_username

SYMBAT_ID = 1042456426
EFFECT_HALAL = "5046509860389126442"
EFFECT_EXPIRED = "5104858069142078462"

def handle_callback(cb):
    user_id = cb["from"]["id"] 
    data = cb["data"]
    
    is_inline = "inline_message_id" in cb
    if is_inline:
        chat_id = None
        message_id = None
        inline_msg_id = cb["inline_message_id"]
    else:
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        inline_msg_id = None
    
    # --- USERNAME АРҚЫЛЫ СЫЙЛЫҚ: РАСТАУ ---
    elif data.startswith("gift_username_confirm:"):
        username_to_gift = data.split(":", 1)[1]
        answer_callback(cb["id"])
        clear_state(user_id)

        confirm_done = (
            f"✅ <b>@{username_to_gift}</b> расталды!\n\n"
            "Төмендегі шотты төлегеннен кейін сыйлық автоматты жіберіледі 👇"
        )
        edit_message(chat_id, message_id, confirm_done)
        send_gift_invoice(chat_id, "username", recipient_username=username_to_gift)

    # --- USERNAME АРҚЫЛЫ СЫЙЛЫҚ: БАС ТАРТУ ---
    elif data == "gift_username_cancel":
        answer_callback(cb["id"])
        clear_state(user_id)
        set_awaiting_username(user_id)

        cancel_text = (
            "🔄 <b>Юзернейм өзгертілді.</b>\n\n"
            "Сыйлағыңыз келетін адамның Telegram юзернеймін қайта жазыңыз:\n\n"
            "✅ Дұрыс формат: <code>@username</code>"
        )
        edit_message(chat_id, message_id, cancel_text)

    elif data == "buy_premium":
        answer_callback(cb["id"])
        handle_buy_premium_callback(chat_id, cb["id"])

    elif data.startswith("gift_type:"):
        gift_type = data.split(":")[1]
        answer_callback(cb["id"])

        if gift_type == "username":
            # Username енгізу режимін іске қосу
            from gift_state import set_awaiting_username
            set_awaiting_username(user_id)
            prompt_text = (
                "👤 <b>@username арқылы сыйлау</b>\n\n"
                "Сыйлағыңыз келетін адамның Telegram юзернеймін жазыңыз.\n\n"
                "✅ Дұрыс формат: <code>@username</code>\n"
                "❌ Қате: <code>username</code> (@ жоқ)\n"
                "❌ Қате: кириллица әріптері\n\n"
                "<i>Ескерту: юзернейм міндетті түрде @ белгісінен басталуы керек және тек латын әріптерінен тұруы тиіс.</i>"
            )
            edit_message(chat_id, message_id, prompt_text)
        else:
            text = "🎁 <b>Сыйлық әдісі таңдалды!</b>\n\nТөмендегі шотты төлегеннен кейін, сізге сыйлықты жіберуге арналған нұсқаулық беріледі 👇"
            edit_message(chat_id, message_id, text)
            send_gift_invoice(chat_id, gift_type)

    elif data.startswith("gender:"):
        gender_val = data.split(":")[1]
        gender_kz = "Ер" if gender_val == "male" else "Әйел"
        answer_callback(cb["id"])
        success_text = f"Рақмет, сақталды! 👍\n\nЕнді бастайық 🚀\nМаған кез келген өнімнің атын жазыңыз, суретін жіберіңіз немесе жақын маңдағы халал дәмханаларды іздеп көріңіз!"
        main_keyboard = {
            "keyboard": [
                [{"text": "📍 Тұрған орнымды жіберу", "request_location": True}],
                [{"text": "⭐️ Premium алу"}, {"text": "🎁 Premium сыйлау"}]
            ],
            "resize_keyboard": True
        }
        edit_message(chat_id, message_id, success_text)
        send_message(chat_id, "Мәзірдегі батырмаларды қолдана аласыз 👇", reply_markup=main_keyboard)
        set_user_gender(user_id, gender_kz)
        log_to_bigquery(user_id, "set_gender", gender_kz, "Профиль жаңартылды")
            
    elif data.startswith("loc:"):
        answer_callback(cb["id"])
        parts = data.split(":")
        page_str, lat_str, lon_str = parts[1], parts[2], parts[3]
        text, markup = get_nearby_companies(float(lat_str), float(lon_str), int(page_str))
        edit_message(chat_id, message_id, text, markup)

    elif data.startswith("itm:"):
        answer_callback(cb["id"])
        parts = data.split(":")
        t_code, item_id = parts[1], parts[2]
        item = get_item_by_id(t_code, item_id)
        if item:
            text, markup = format_detail_message(item)
            has_access, tier = check_access(user_id, user_id == SYMBAT_ID)
            
            effect = None
            reaction = None
            
            if tier in ["premium", "VIP"]:
                status_text = item.get("status", "")
                if "Белсенді" in status_text or "Рұқсат" in status_text: 
                    effect = EFFECT_HALAL
                    reaction = "🎉"
                elif "Мерзімі" in status_text or "⚠️" in status_text or "🚫" in status_text or "Қайтарып" in status_text: 
                    effect = EFFECT_EXPIRED
                    reaction = "👎"

            bot_msg_id = send_message(chat_id, text, reply_markup=markup, message_effect_id=effect)
            
            if reaction and bot_msg_id:
                set_message_reaction(chat_id, bot_msg_id, reaction)
                
        else:
            answer_callback(cb["id"], text="Мәлімет табылмады 😔", show_alert=True)

    # --- AI FEEDBACK (жаңа, нақты өңдеуші) ---
    elif data == "fb:good:ai":
        answer_callback(cb["id"], text="Пікіріңізге рақмет! ❤️")
        # AI жауабынан feedback батырмаларын алып тастаймыз
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": []}, inline_msg_id)
        log_to_bigquery(user_id, "feedback", "👍 AI жауабы пайдалы", "Кері байланыс")

    elif data == "fb:bad:ai":
        answer_callback(cb["id"])
        new_kb = [
            [{"text": "📝 Қате ақпарат", "callback_data": "fb:reason:info:ai", "style": "danger"}],
            [{"text": "🤖 ЖИ қатесі", "callback_data": "fb:reason:ai:ai", "style": "danger"}],
            [{"text": "❌ Басқа", "callback_data": "fb:reason:other:ai", "style": "danger"}]
        ]
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": new_kb}, inline_msg_id)

    # --- ӨНІМ FEEDBACK ---
    elif data.startswith("fb:good"):
        answer_callback(cb["id"], text="Пікіріңізге рақмет! ❤️")
        
        new_kb = []
        if not is_inline:
            existing_kb = cb["message"].get("reply_markup", {}).get("inline_keyboard", [])
            for row in existing_kb:
                new_row = [btn for btn in row if not (btn.get("callback_data", "").startswith("fb:"))]
                if new_row:
                    new_kb.append(new_row)
        else:
            parts = data.split(":")
            if len(parts) >= 5 and parts[2] == "itm":
                t_code, item_id = parts[3], parts[4]
                item = get_item_by_id(t_code, item_id)
                if item and item.get("map_link"):
                    new_kb.append([{"text": "🗺️ Картадан көру", "url": item["map_link"], "style": "primary"}])
                    
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": new_kb}, inline_msg_id)
        log_to_bigquery(user_id, "feedback", "👍 Пайдалы", "Кері байланыс")

    elif data.startswith("fb:bad"):
        answer_callback(cb["id"])
        
        new_kb = []
        if not is_inline:
            existing_kb = cb["message"].get("reply_markup", {}).get("inline_keyboard", [])
            for row in existing_kb:
                url_row = [btn for btn in row if "url" in btn]
                if url_row:
                    new_kb.append(url_row)
        else:
            parts = data.split(":")
            if len(parts) >= 5 and parts[2] == "itm":
                t_code, item_id = parts[3], parts[4]
                item = get_item_by_id(t_code, item_id)
                if item and item.get("map_link"):
                    new_kb.append([{"text": "🗺️ Картадан көру", "url": item["map_link"], "style": "primary"}])
        
        suffix = data[7:]
        new_kb.append([{"text": "📝 Қате ақпарат", "callback_data": f"fb:reason:info:{suffix}", "style": "danger"}])
        new_kb.append([{"text": "🤖 ЖИ қатесі", "callback_data": f"fb:reason:ai:{suffix}", "style": "danger"}])
        new_kb.append([{"text": "❌ Басқа", "callback_data": f"fb:reason:other:{suffix}", "style": "danger"}])
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": new_kb}, inline_msg_id)

    elif data.startswith("fb:reason:"):
        parts = data.split(":")
        reason_code = parts[2]
        reason_text = "Қате ақпарат" if reason_code == "info" else "ЖИ қатесі" if reason_code == "ai" else "Басқа"
        
        answer_callback(cb["id"], text="Рақмет! Түзетеміз 🛠", show_alert=True)
        
        new_kb = []
        if not is_inline:
            existing_kb = cb["message"].get("reply_markup", {}).get("inline_keyboard", [])
            for row in existing_kb:
                url_row = [btn for btn in row if "url" in btn]
                if url_row:
                    new_kb.append(url_row)
        else:
            if len(parts) >= 6 and parts[3] == "itm":
                t_code, item_id = parts[4], parts[5]
                item = get_item_by_id(t_code, item_id)
                if item and item.get("map_link"):
                    new_kb.append([{"text": "🗺️ Картадан көру", "url": item["map_link"], "style": "primary"}])
                    
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": new_kb}, inline_msg_id)
        log_to_bigquery(user_id, "feedback", f"👎 Қате ({reason_text})", "Кері байланыс")
