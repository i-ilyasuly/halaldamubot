from bot_sender import send_message, send_photo_message, edit_message, edit_reply_markup, answer_callback, set_message_reaction, send_gift_invoice
from db_core import set_user_gender, log_to_bigquery, get_item_by_id, check_access, get_search_session
from search_logic import get_nearby_companies
from formatters import format_detail_message
from payments import handle_buy_premium_callback
from gift_state import (set_awaiting_username, clear_state, get_pending_username,
                        set_pending_anon, get_pending_anon)

SYMBAT_ID = 1042456426
EFFECT_HALAL = "5046509860389126442"
EFFECT_EXPIRED = "5104858069142078462"

def _ask_tariff_for_gift(chat_id, message_id, gift_type, recipient_username=None):
    """Сыйлық үшін тариф таңдату"""
    from tariffs import TARIFFS
    r = recipient_username or ""
    text = (
        "🎁 <b>Қанша мерзімге сыйлағыңыз келеді?</b>\n\n"
        "Тарифті таңдаңыз 👇"
    )
    keyboard = []
    for t in TARIFFS:
        if t["discount"] > 0:
            btn_text = f"{t['emoji']} {t['label']} — {t['stars']} ⭐ (-{t['discount']}%)"
        else:
            btn_text = f"{t['emoji']} {t['label']} — {t['stars']} ⭐"
        keyboard.append([{"text": btn_text, "callback_data": f"gift_tariff:{t['id']}:{gift_type}:{r}"}])
    edit_message(chat_id, message_id, text, {"inline_keyboard": keyboard})


def _ask_anon(chat_id, message_id, gift_type, tariff_id, recipient_username=None):
    """Анонимді/атымен сұрау батырмаларын шығару"""
    text = (
        "🎭 <b>Сыйлықты қалай жібергіңіз келеді?</b>\n\n"
        "👤 <b>Атыңызбен</b> — алушы сіздің есіміңізді көреді\n"
        "🎭 <b>Анонимді</b> — алушы кімнен екенін білмейді"
    )
    r = recipient_username or ""
    markup = {
        "inline_keyboard": [
            [{"text": "👤 Атыммен", "callback_data": f"gift_anon:named:{gift_type}:{tariff_id}:{r}"}],
            [{"text": "🎭 Анонимді", "callback_data": f"gift_anon:anon:{gift_type}:{tariff_id}:{r}"}]
        ]
    }
    edit_message(chat_id, message_id, text, markup)


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

    # --- АНОНИМДІ/АТЫМЕН ТАҢДАУ ---
    # --- ТАРИФ ТАҢДАУ (өзіне алу) ---
    if data.startswith("buy_tariff:"):
        tariff_id = data.split(":", 1)[1]
        answer_callback(cb["id"])
        from tariffs import get_tariff_description
        from bot_sender import send_tariff_invoice
        confirm_text = (
            f"✅ Тариф таңдалды: {get_tariff_description(tariff_id)}\n\n"
            "Төмендегі шотты төлегеннен кейін Premium іске қосылады 👇"
        )
        edit_message(chat_id, message_id, confirm_text)
        send_tariff_invoice(chat_id, tariff_id)

    # --- ТАРИФ ТАҢДАУ (сыйлық) ---
    elif data.startswith("gift_tariff:"):
        parts = data.split(":")
        # gift_tariff:premium_30_days:link:  немесе  gift_tariff:premium_30_days:username:aibek_kz
        tariff_id = parts[1]
        gift_type = parts[2]
        recipient = parts[3] if len(parts) > 3 else ""
        answer_callback(cb["id"])
        # Тариф таңдалды — енді анонимді/атымен сұраймыз
        _ask_anon(chat_id, message_id, gift_type, tariff_id, recipient_username=recipient if recipient else None)

    elif data.startswith("gift_anon:"):
        parts = data.split(":")
        # gift_anon:named:link:premium_30_days:  немесе  gift_anon:anon:username:premium_90_days:aibek_kz
        anon_type  = parts[1]   # "named" / "anon"
        gift_type  = parts[2]   # "link" / "inline" / "username"
        tariff_id  = parts[3]   # "premium_30_days" т.б.
        recipient  = parts[4] if len(parts) > 4 else ""

        answer_callback(cb["id"])

        from tariffs import get_tariff_description
        from bot_sender import send_gift_tariff_invoice
        buyer_name_display = cb["from"].get("first_name", "Жанашыр") if anon_type == "named" else "Жасырын жанашыр"

        if gift_type == "username" and recipient:
            confirm_text = (
                f"✅ Расталды!\n\n"
                f"Тариф: {get_tariff_description(tariff_id)}\n"
                f"Алушы: <b>@{recipient}</b>\n"
                f"Сіз: <b>{buyer_name_display}</b>\n\n"
                "Төмендегі шотты төлегеннен кейін сыйлық жіберіледі 👇"
            )
            edit_message(chat_id, message_id, confirm_text)
            send_gift_tariff_invoice(chat_id, tariff_id, "username", recipient_username=recipient, buyer_name=buyer_name_display)
        else:
            confirm_text = (
                f"✅ Расталды!\n\n"
                f"Тариф: {get_tariff_description(tariff_id)}\n"
                f"Сіз: <b>{buyer_name_display}</b>\n\n"
                "Төмендегі шотты төлегеннен кейін сыйлықты жіберуге нұсқаулық беріледі 👇"
            )
            edit_message(chat_id, message_id, confirm_text)
            send_gift_tariff_invoice(chat_id, tariff_id, gift_type, buyer_name=buyer_name_display)

    # --- USERNAME АРҚЫЛЫ СЫЙЛЫҚ: РАСТАУ ---
    elif data.startswith("gift_username_confirm:"):
        username_to_gift = data.split(":", 1)[1]
        answer_callback(cb["id"])
        clear_state(user_id)
        # Username расталды — алдымен тариф таңдатамыз
        _ask_tariff_for_gift(chat_id, message_id, "username", recipient_username=username_to_gift)

    # --- USERNAME АРҚЫЛЫ СЫЙЛЫҚ: БАС ТАРТУ ---
    elif data == "gift_username_cancel":
        answer_callback(cb["id"])
        clear_state(user_id)
        # Негізгі сыйлық таңдау мәзіріне қайтарамыз
        gift_text = (
            "🎁 <b>Premium сыйлау</b>\n\n"
            "Сыйлықты досыңызға қалай жібергіңіз келеді?\n\n"
            "1️⃣ <b>Сілтеме арқылы</b> — WhatsApp, Инстаграм немесе басқа желілер арқылы.\n"
            "2️⃣ <b>Телеграм арқылы</b> — Досыңыздың чатына әдемі қорап болып барады.\n"
            "3️⃣ <b>@username арқылы</b> — Telegram юзернеймін білсеңіз тікелей жіберіледі."
        )
        gift_markup = {
            "inline_keyboard": [
                [{"text": "🔗 Сілтеме арқылы", "callback_data": "gift_type:link"}],
                [{"text": "💬 Телеграм арқылы (Әдемі)", "callback_data": "gift_type:inline"}],
                [{"text": "👤 @username арқылы", "callback_data": "gift_type:username"}]
            ]
        }
        edit_message(chat_id, message_id, gift_text, gift_markup)

    # --- USERNAME ӨЗГЕРТУ (растаудан кейін «Жоқ, өзгертемін») ---
    elif data == "gift_username_retry":
        answer_callback(cb["id"])
        clear_state(user_id)
        set_awaiting_username(user_id)
        retry_text = (
            "🔄 <b>Юзернейм өзгертілді.</b>\n\n"
            "Сыйлағыңыз келетін адамның Telegram юзернеймін қайта жазыңыз:\n\n"
            "✅ Дұрыс формат: <code>@username</code>"
        )
        cancel_markup = {
            "inline_keyboard": [[
                {"text": "❌ Бас тарту", "callback_data": "gift_username_cancel"}
            ]]
        }
        edit_message(chat_id, message_id, retry_text, cancel_markup)


    elif data == "buy_premium":
        answer_callback(cb["id"])
        handle_buy_premium_callback(chat_id, cb["id"])

    elif data.startswith("gift_type:"):
        gift_type = data.split(":")[1]
        answer_callback(cb["id"])

        if gift_type == "username":
            set_awaiting_username(user_id)
            prompt_text = (
                "👤 <b>@username арқылы сыйлау</b>\n\n"
                "Сыйлағыңыз келетін адамның Telegram юзернеймін жазыңыз.\n\n"
                "✅ Дұрыс формат: <code>@username</code>\n"
                "❌ Қате: <code>username</code> (@ жоқ)\n"
                "❌ Қате: кириллица әріптері\n\n"
                "<i>Юзернейм міндетті түрде @ белгісінен басталуы керек.</i>"
            )
            # Inline батырма — мәзірді бұзбайды, хабар астында тұрады
            cancel_markup = {
                "inline_keyboard": [[
                    {"text": "❌ Бас тарту", "callback_data": "gift_username_cancel"}
                ]]
            }
            edit_message(chat_id, message_id, prompt_text, cancel_markup)
        else:
            # Алдымен тариф таңдатамыз
            _ask_tariff_for_gift(chat_id, message_id, gift_type)

    elif data.startswith("settings:"):
        action = data.split(":")[1]
        answer_callback(cb["id"])
        if action == "gender":
            gender_text = (
                "🔄 <b>Жынысты өзгерту</b>\n\n"
                "Жынысыңызды таңдаңыз:"
            )
            gender_markup = {"inline_keyboard": [[
                {"text": "🙎‍♂️ Ер азамат", "callback_data": "gender:male"},
                {"text": "🙎‍♀️ Нәзік жанды", "callback_data": "gender:female"}
            ]]}
            edit_message(chat_id, message_id, gender_text, gender_markup)

    elif data.startswith("gender:"):
        gender_val = data.split(":")[1]
        gender_kz = "Ер" if gender_val == "male" else "Әйел"
        answer_callback(cb["id"])
        success_text = "Рақмет, сақталды! 👍\n\nЕнді бастайық 🚀\nМаған кез келген өнімнің атын жазыңыз, суретін жіберіңіз немесе жақын маңдағы халал дәмханаларды іздеп көріңіз!"
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

    elif data.startswith("srch:"):
        answer_callback(cb["id"])
        try:
            import math
            _, page_str, session_id = data.split(":", 2)
            page = int(page_str)
            items_meta = get_search_session(session_id)
            all_items = []
            for m in items_meta:
                t_code = "c" if m["t"] == "Мекеме" else "i"
                item = get_item_by_id(t_code, m["id"])
                if item:
                    item['confidence'] = m.get('c', 'exact')
                    all_items.append(item)

            per_page = 5
            total = len(all_items)
            total_pages = math.ceil(total / per_page) if total > 0 else 1
            if page > total_pages: page = total_pages
            if page < 1: page = 1

            start = (page - 1) * per_page
            items = all_items[start:start + per_page]

            reply_text = f"🔍 <b>Табылған нұсқалар:</b> {total} дана\n📄 {page}/{total_pages} бет\n\n"
            keyboard = []
            for idx, item in enumerate(items, start=start + 1):
                confidence = item.get('confidence', 'exact')
                prefix = "❓ " if confidence == 'fuzzy' else ""
                if item['type'] == 'Мекеме':
                    desc_text = f"📍 {item.get('address', '')}"
                else:
                    desc_text = f"🏷 {item.get('desc', '')}"
                reply_text += f"<b>{idx}. {prefix}«{item['title']}»</b>\n{desc_text}\n"
                if confidence == 'fuzzy':
                    reply_text += f"<i>⚠️ Ұқсас, бірақ нақты сәйкес емес</i>\n"
                reply_text += "\n"
                t_code = "c" if item['type'] == "Мекеме" else "i"
                keyboard.append([{"text": f"{idx}. {prefix}«{item['title']}»", "callback_data": f"itm:{t_code}:{item['id']}"}])

            nav = []
            if page > 1:
                nav.append({"text": "⬅️ Артқа", "callback_data": f"srch:{page-1}:{session_id}"})
            if page < total_pages:
                nav.append({"text": "Келесі ➡️", "callback_data": f"srch:{page+1}:{session_id}"})
            if nav:
                keyboard.append(nav)

            edit_message(chat_id, message_id, reply_text, {"inline_keyboard": keyboard})
        except Exception as e:
            print(f"[srch callback] Қате: {e}")

    elif data.startswith("loc:"):
        answer_callback(cb["id"])
        try:
            # "loc:2:43.2567:76.4521" → ["loc", "2", "43.2567", "76.4521"]
            _, page_str, lat_str, lon_str = data.split(":", 3)
            text, markup = get_nearby_companies(float(lat_str), float(lon_str), int(page_str))
            edit_message(chat_id, message_id, text, markup)
        except Exception as e:
            print(f"[loc callback] Қате: {e}, data={data}")

    elif data.startswith("itm:"):
        answer_callback(cb["id"])
        parts = data.split(":")
        t_code, item_id = parts[1], parts[2]
        print(f"[itm callback] t_code={t_code}, item_id={item_id}, chat_id={chat_id}")
        item = get_item_by_id(t_code, item_id)
        print(f"[itm callback] item={'табылды' if item else 'ТАБЫЛМАДЫ'}")
        if item:
            text, markup = format_detail_message(item, confidence='exact')
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
            image_url = item.get("image_url", "")
            if image_url:
                bot_msg_id = send_photo_message(chat_id, image_url, text,
                                                reply_markup=markup, message_effect_id=effect)
            else:
                bot_msg_id = send_message(chat_id, text, reply_markup=markup, message_effect_id=effect)
            print(f"[itm callback] bot_msg_id={bot_msg_id}")
            if reaction and bot_msg_id:
                set_message_reaction(chat_id, bot_msg_id, reaction)
        else:
            answer_callback(cb["id"], text="Мәлімет табылмады 😔", show_alert=True)

    # --- AI FEEDBACK ---
    elif data == "fb:good:ai":
        answer_callback(cb["id"], text="Пікіріңізге рақмет! ❤️")
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": []}, inline_msg_id)
        log_to_bigquery(user_id, "feedback", "👍 AI жауабы пайдалы", "Кері байланыс")

    elif data == "fb:bad:ai":
        answer_callback(cb["id"])
        new_kb = [
            [{"text": "📝 Қате ақпарат", "callback_data": "fb:reason:info:ai"}],
            [{"text": "🤖 ЖИ қатесі", "callback_data": "fb:reason:ai:ai"}],
            [{"text": "❌ Басқа", "callback_data": "fb:reason:other:ai"}]
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
                    new_kb.append([{"text": "🗺️ Картадан көру", "url": item["map_link"]}])
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
                    new_kb.append([{"text": "🗺️ Картадан көру", "url": item["map_link"]}])
        suffix = data[7:]
        new_kb.append([{"text": "📝 Қате ақпарат", "callback_data": f"fb:reason:info:{suffix}"}])
        new_kb.append([{"text": "🤖 ЖИ қатесі", "callback_data": f"fb:reason:ai:{suffix}"}])
        new_kb.append([{"text": "❌ Басқа", "callback_data": f"fb:reason:other:{suffix}"}])
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
                    new_kb.append([{"text": "🗺️ Картадан көру", "url": item["map_link"]}])
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": new_kb}, inline_msg_id)
        log_to_bigquery(user_id, "feedback", f"👎 Қате ({reason_text})", "Кері байланыс")
