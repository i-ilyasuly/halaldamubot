from bot_sender import send_message, send_photo_message, edit_message, edit_reply_markup, answer_callback, set_message_reaction, send_gift_invoice
from db_core import set_user_gender, log_to_bigquery, get_item_by_id, check_access, get_search_session, get_user_language, set_user_language
from translations import t
from search_logic import get_nearby_companies
from formatters import format_detail_message
from payments import handle_buy_premium_callback
from gift_state import (set_awaiting_username, clear_state, get_pending_username,
                        set_pending_anon, get_pending_anon)

SYMBAT_ID = 1042456426
EFFECT_HALAL = "5046509860389126442"
EFFECT_EXPIRED = "5104858069142078462"

def _ask_tariff_for_gift(chat_id, message_id, gift_type, recipient_username=None, lang='kz'):
    """Сыйлық үшін тариф таңдату"""
    from tariffs import TARIFFS
    r = recipient_username or ""
    title_text = t("gift_tariff_title", lang)
    keyboard = []
    for tariff in TARIFFS:
        if tariff["discount"] > 0:
            btn_text = f"{tariff['emoji']} {tariff['label']} — {tariff['stars']} ⭐ ({tariff['kzt']} ₸, -{tariff['discount']}%)"
        else:
            btn_text = f"{tariff['emoji']} {tariff['label']} — {tariff['stars']} ⭐ ({tariff['kzt']} ₸)"
        keyboard.append([{"text": btn_text, "callback_data": f"gift_tariff:{tariff['id']}:{gift_type}:{r}", "style": "success"}])
    edit_message(chat_id, message_id, title_text, {"inline_keyboard": keyboard})


def _ask_anon(chat_id, message_id, gift_type, tariff_id, recipient_username=None, lang='kz'):
    """Анонимді/атымен сұрау батырмаларын шығару"""
    text = t("gift_ask_anon", lang)
    r = recipient_username or ""
    markup = {
        "inline_keyboard": [
            [{"text": t("gift_btn_named", lang), "callback_data": f"gift_anon:named:{gift_type}:{tariff_id}:{r}", "style": "success"}],
            [{"text": t("gift_btn_anon", lang), "callback_data": f"gift_anon:anon:{gift_type}:{tariff_id}:{r}", "style": "primary"}]
        ]
    }
    edit_message(chat_id, message_id, text, markup)


def handle_callback(cb):
    user_id = cb["from"]["id"]
    data = cb["data"]
    lang = get_user_language(user_id)

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
    # --- ТІЛ ТАҢДАУ ---
    if data.startswith("lang:"):
        chosen_lang = data.split(":")[1]  # 'kz' немесе 'ru'
        answer_callback(cb["id"])
        set_user_language(user_id, chosen_lang)
        lang = chosen_lang  # осы сессияда жаңартамыз
        # Тіл таңдалды — жынысын сұраймыз
        welcome_text = t('welcome_new', lang, name=cb["from"].get("first_name", ""))
        gender_markup = {"inline_keyboard": [[
            {"text": t('ask_gender_male', lang), "callback_data": "gender:male", "style": "primary"},
            {"text": t('ask_gender_female', lang), "callback_data": "gender:female", "style": "primary"}
        ]]}
        edit_message(chat_id, message_id, welcome_text, gender_markup)

    # --- БАПТАУЛАРДАН ТІЛ ӨЗГЕРТУ ---
    elif data == "settings:language":
        answer_callback(cb["id"])
        lang_markup = {"inline_keyboard": [[
            {"text": "🇰🇿 Қазақша", "callback_data": "lang_change:kz", "style": "primary"},
            {"text": "🇷🇺 Русский", "callback_data": "lang_change:ru", "style": "primary"}
        ]]}
        edit_message(chat_id, message_id, "🌐 <b>Тілді таңдаңыз / Выберите язык:</b>", lang_markup)

    elif data.startswith("lang_change:"):
        chosen_lang = data.split(":")[1]
        answer_callback(cb["id"])
        set_user_language(user_id, chosen_lang)
        lang = chosen_lang
        # Сәтті өзгерді
        ok_text = "✅ Тіл өзгертілді: Қазақша 🇰🇿" if chosen_lang == 'kz' else "✅ Язык изменён: Русский 🇷🇺"
        edit_message(chat_id, message_id, ok_text)
        # Мәзір батырмаларын жаңа тілде жаңартамыз
        from handlers_message import _main_keyboard
        from bot_sender import send_message as _send_msg
        _send_msg(chat_id, "👇", reply_markup=_main_keyboard(chosen_lang))

    # --- ТАРИФ ТАҢДАУ (өзіне алу) ---
    elif data.startswith("buy_tariff:"):
        tariff_id = data.split(":", 1)[1]
        answer_callback(cb["id"])
        from tariffs import get_tariff_description
        from bot_sender import send_tariff_invoice
        confirm_text = t("buy_tariff_confirm", lang, tariff=get_tariff_description(tariff_id, lang=lang))
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
        _ask_anon(chat_id, message_id, gift_type, tariff_id, recipient_username=recipient if recipient else None, lang=lang)

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
            confirm_text = t("gift_confirm_username", lang, tariff=get_tariff_description(tariff_id, lang=lang), recipient=recipient, buyer=buyer_name_display)
            edit_message(chat_id, message_id, confirm_text)
            send_gift_tariff_invoice(chat_id, tariff_id, "username", recipient_username=recipient, buyer_name=buyer_name_display)
        else:
            confirm_text = t("gift_confirm_other", lang, tariff=get_tariff_description(tariff_id, lang=lang), buyer=buyer_name_display)
            edit_message(chat_id, message_id, confirm_text)
            send_gift_tariff_invoice(chat_id, tariff_id, gift_type, buyer_name=buyer_name_display)

    # --- USERNAME АРҚЫЛЫ СЫЙЛЫҚ: РАСТАУ ---
    elif data.startswith("gift_username_confirm:"):
        username_to_gift = data.split(":", 1)[1]
        answer_callback(cb["id"])
        clear_state(user_id)
        # Username расталды — алдымен тариф таңдатамыз
        _ask_tariff_for_gift(chat_id, message_id, "username", recipient_username=username_to_gift, lang=lang)

    # --- USERNAME АРҚЫЛЫ СЫЙЛЫҚ: БАС ТАРТУ ---
    elif data == "gift_username_cancel":
        answer_callback(cb["id"])
        clear_state(user_id)
        gift_text = t("gift_menu_text", lang)
        gift_markup = {
            "inline_keyboard": [
                [{"text": t("gift_btn_link", lang), "callback_data": "gift_type:link", "style": "success"}],
                [{"text": t("gift_btn_inline", lang), "callback_data": "gift_type:inline", "style": "success"}],
                [{"text": t("gift_btn_username", lang), "callback_data": "gift_type:username", "style": "success"}]
            ]
        }
        edit_message(chat_id, message_id, gift_text, gift_markup)

    # --- USERNAME ӨЗГЕРТУ (растаудан кейін «Жоқ, өзгертемін») ---
    elif data == "gift_username_retry":
        answer_callback(cb["id"])
        clear_state(user_id)
        set_awaiting_username(user_id)
        retry_text = t("username_retry_text", lang)
        cancel_markup = {
            "inline_keyboard": [[
                {"text": t("btn_cancel", lang), "callback_data": "gift_username_cancel", "style": "danger"}
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
            prompt_text = t("username_prompt", lang)
            cancel_markup = {
                "inline_keyboard": [[
                    {"text": t("btn_cancel", lang), "callback_data": "gift_username_cancel", "style": "danger"}
                ]]
            }
            edit_message(chat_id, message_id, prompt_text, cancel_markup)
        else:
            # Алдымен тариф таңдатамыз
            _ask_tariff_for_gift(chat_id, message_id, gift_type, lang=lang)

    elif data.startswith("settings:"):
        action = data.split(":")[1]
        answer_callback(cb["id"])
        if action == "gender":
            gender_text = (
                "🔄 <b>Жынысты өзгерту</b>\n\n"
                "Жынысыңызды таңдаңыз:"
            )
            gender_markup = {"inline_keyboard": [[
                {"text": "🙎‍♂️ Ер азамат", "callback_data": "gender:male", "style": "primary"},
                {"text": "🙎‍♀️ Нәзік жанды", "callback_data": "gender:female", "style": "primary"}
            ]]}
            edit_message(chat_id, message_id, gender_text, gender_markup)

    elif data.startswith("gender:"):
        gender_val = data.split(":")[1]
        gender_kz = "Ер" if gender_val == "male" else "Әйел"
        answer_callback(cb["id"])
        from handlers_message import _main_keyboard
        if lang == 'kz':
            success_text = "Рақмет, сақталды! 👍\n\nЕнді бастайық 🚀\nМаған кез келген өнімнің атын жазыңыз, суретін жіберіңіз немесе жақын маңдағы халал дәмханаларды іздеп көріңіз!"
            menu_text = "Мәзірдегі батырмаларды қолдана аласыз 👇"
        else:
            success_text = "Спасибо, сохранено! 👍\n\nНачнём 🚀\nНапишите название продукта, пришлите фото или найдите ближайшие халяльные заведения!"
            menu_text = "Используйте кнопки меню ниже 👇"
        edit_message(chat_id, message_id, success_text)
        send_message(chat_id, menu_text, reply_markup=_main_keyboard(lang))
        set_user_gender(user_id, gender_kz)
        log_to_bigquery(user_id, "set_gender", gender_kz, "Профиль жаңартылды", gender=gender_kz)

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
                status_text = item.get('status', '')
                if confidence == 'fuzzy':
                    btn_style = "primary"
                elif "Белсенді" in status_text or "Рұқсат" in status_text:
                    btn_style = "success"
                elif "Мерзімі" in status_text or "Қайтарып" in status_text or "🚫" in status_text:
                    btn_style = "danger"
                else:
                    btn_style = "primary"
                keyboard.append([{"text": f"{idx}. {prefix}«{item['title']}»", "callback_data": f"itm:{t_code}:{item['id']}", "style": btn_style}])

            nav = []
            if page > 1:
                nav.append({"text": t("btn_back", lang), "callback_data": f"srch:{page-1}:{session_id}", "style": "primary"})
            if page < total_pages:
                nav.append({"text": t("btn_next", lang), "callback_data": f"srch:{page+1}:{session_id}", "style": "primary"})
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
            text, markup = get_nearby_companies(float(lat_str), float(lon_str), int(page_str), lang=lang)
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
            text, markup = format_detail_message(item, confidence='exact', lang=lang)
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
        answer_callback(cb["id"], text=t("feedback_thanks", lang))
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": []}, inline_msg_id)
        log_to_bigquery(user_id, "feedback", "👍 AI жауабы пайдалы", "Кері байланыс")

    elif data == "fb:bad:ai":
        answer_callback(cb["id"])
        new_kb = [
            [{"text": t("btn_bad_info", lang), "callback_data": "fb:reason:info:ai", "style": "danger"}],
            [{"text": t("btn_bad_ai", lang), "callback_data": "fb:reason:ai:ai", "style": "danger"}],
            [{"text": t("btn_bad_other", lang), "callback_data": "fb:reason:other:ai", "style": "danger"}]
        ]
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": new_kb}, inline_msg_id)

    # --- ӨНІМ FEEDBACK ---
    elif data.startswith("fb:good"):
        answer_callback(cb["id"], text=t("feedback_thanks", lang))
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
        new_kb.append([{"text": t("btn_bad_info", lang), "callback_data": f"fb:reason:info:{suffix}", "style": "danger"}])
        new_kb.append([{"text": t("btn_bad_ai", lang), "callback_data": f"fb:reason:ai:{suffix}", "style": "danger"}])
        new_kb.append([{"text": t("btn_bad_other", lang), "callback_data": f"fb:reason:other:{suffix}", "style": "danger"}])
        edit_reply_markup(chat_id, message_id, {"inline_keyboard": new_kb}, inline_msg_id)

    elif data.startswith("fb:reason:"):
        parts = data.split(":")
        reason_code = parts[2]
        reason_text = "Қате ақпарат" if reason_code == "info" else "ЖИ қатесі" if reason_code == "ai" else "Басқа"
        answer_callback(cb["id"], text=t("feedback_fixed", lang), show_alert=True)
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
