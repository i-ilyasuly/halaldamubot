import re
import random
import requests as _requests
from bot_sender import send_message, send_photo_message, edit_message, send_chat_action, download_photo, set_message_reaction, send_invoice, send_gift_invoice
from db_core import (add_user, save_chat_history, log_to_bigquery, check_access,
                     increment_usage, revoke_premium, get_user_gender, redeem_gift_code,
                     get_pending_gift_for_username, delete_pending_gift, grant_premium,
                     get_user_language, set_user_language)
from translations import t
from search_logic import search_data, get_nearby_companies
from formatters import format_detail_message
from quotes import get_quote
from ai_core import handle_photo, chat_with_ai, extract_search_term, get_not_found_reply
from classifier import classify_query, should_classify
from payments import process_successful_payment, get_premium_keyboard
from gift_state import (set_awaiting_username, is_awaiting_username,
                        set_confirm_username, get_pending_username, clear_state)

SYMBAT_ID = 1042456426

def _get_city(lat, lon):
    try:
        from config import GEOCODING_API_KEY
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"latlng": f"{lat},{lon}", "key": GEOCODING_API_KEY, "language": "ru"}
        data = _requests.get(url, params=params, timeout=10).json()
        if data.get("status") == "OK":
            for result in data["results"]:
                for component in result["address_components"]:
                    if "locality" in component["types"]:
                        return component["long_name"]
                    if "administrative_area_level_1" in component["types"]:
                        return component["long_name"]
    except Exception as e:
        print(f"[_get_city] Қате: {e}")
    return None

EFFECT_HALAL = "5046509860389126442"
EFFECT_EXPIRED = "5104858069142078462"

def _access_denied_msg(lang, tier):
    from translations import t
    from payments import get_premium_keyboard
    if tier == "SPAM_LIMIT":
        return t("spam_protection", lang), None
    return t("limit_hit", lang), get_premium_keyboard(lang)

USERNAME_RE = re.compile(r'^@[a-zA-Z0-9_]{5,32}$')

def _has_cyrillic(text):
    return bool(re.search(r'[а-яёА-ЯЁәіңғүұқөһӘІҢҒҮҰҚӨҺ]', text))

def _main_keyboard(lang='kz'):
    return {
        "keyboard": [
            [{"text": t('btn_location', lang), "request_location": True}],
            [{"text": t('btn_settings', lang)}]
        ],
        "resize_keyboard": True
    }

def handle_message(msg):
    chat_id = msg["chat"]["id"]
    user_msg_id = msg["message_id"]
    first_name = msg["chat"].get("first_name", "Досым")
    username = msg["chat"].get("username", "жоқ")
    is_symbat = (chat_id == SYMBAT_ID)
    lang = get_user_language(chat_id) if not is_symbat else 'kz'

    if "successful_payment" in msg:
        process_successful_payment(msg)
        return

    if "refunded_payment" in msg:
        revoke_premium(chat_id)
        send_message(chat_id, t("refund_text", lang), reply_to_message_id=user_msg_id)
        return

    if "photo" in msg:
        has_access, tier = check_access(chat_id, is_symbat)
        if not has_access:
            _msg, _markup = _access_denied_msg(lang, tier)
            log_to_bigquery(chat_id, "limit_hit", "photo_search", "Лимит бітті")
            send_message(chat_id, _msg, reply_markup=_markup, reply_to_message_id=user_msg_id)
            return

        clear_state(chat_id)
        send_chat_action(chat_id, "typing")
        if tier in ["premium", "VIP"]:
            loading_reaction = random.choice(["🤔", "👀", "⚡", "🤓", "👨‍💻"])
            set_message_reaction(chat_id, user_msg_id, loading_reaction)

        photo_id = msg["photo"][-1]["file_id"]
        image_bytes = download_photo(photo_id)
        if image_bytes:
            try:
                result_msg, markup, item_image_url = handle_photo(image_bytes, chat_id, username, lang=lang)
            except Exception as e:
                print(f"[handle_message] handle_photo қате: {e}")
                result_msg = t("photo_error", lang)
                markup = None
                item_image_url = ""

            effect = None
            reaction = None
            if tier in ["premium", "VIP"]:
                if "✅" in result_msg:
                    effect = EFFECT_HALAL
                    reaction = "🎉"
                elif "⚠️" in result_msg or "🚫" in result_msg or "Қайтарып" in result_msg:
                    effect = EFFECT_EXPIRED
                    reaction = "👎"
                else:
                    reaction = "🤔"

            if item_image_url:
                bot_msg_id = send_photo_message(chat_id, item_image_url, result_msg,
                                                reply_markup=markup, message_effect_id=effect,
                                                reply_to_message_id=user_msg_id)
            else:
                bot_msg_id = send_message(chat_id, result_msg, reply_markup=markup,
                                          message_effect_id=effect, reply_to_message_id=user_msg_id)
            if reaction and bot_msg_id:
                set_message_reaction(chat_id, bot_msg_id, reaction)
            save_chat_history(chat_id, "user", "Мен саған бір сурет жібердім")
            save_chat_history(chat_id, "model", result_msg)
            log_to_bigquery(chat_id, "photo_search", "Сурет", "Тексерілді",
                            is_premium=(tier in ["premium", "VIP"]))
            increment_usage(chat_id)

    elif "location" in msg:
        has_access, tier = check_access(chat_id, is_symbat)
        if not has_access:
            _msg, _markup = _access_denied_msg(lang, tier)
            log_to_bigquery(chat_id, "limit_hit", "location_search", "Лимит бітті")
            send_message(chat_id, _msg, reply_markup=_markup, reply_to_message_id=user_msg_id)
            return

        clear_state(chat_id)
        send_chat_action(chat_id, "find_location")
        lat, lon = msg["location"]["latitude"], msg["location"]["longitude"]
        text, markup = get_nearby_companies(lat, lon, page=1, lang=lang)
        effect = EFFECT_HALAL if tier in ["premium", "VIP"] else None
        if tier in ["premium", "VIP"]:
            quote = get_quote("location", lang)
            if quote:
                text += f"\n\n{quote}"
        bot_msg_id = send_message(chat_id, text, reply_markup=markup, message_effect_id=effect)
        if tier in ["premium", "VIP"] and bot_msg_id:
            set_message_reaction(chat_id, bot_msg_id, "⚡")
        city = _get_city(lat, lon)
        log_to_bigquery(chat_id, "location_search", f"{lat}, {lon}", "Тізім берілді",
                        is_premium=(tier in ["premium", "VIP"]), platform=city)
        increment_usage(chat_id)

    elif "text" in msg:
        text = msg["text"]

        # ── USERNAME ЕНГІЗУ РЕЖИМІ ──────────────────────────────────────────
        if is_awaiting_username(chat_id):
            _handle_username_input(chat_id, user_msg_id, text, lang)
            return

        # ── USERNAME РАСТАУ РЕЖИМІ ──────────────────────────────────────────
        if get_pending_username(chat_id) is not None:
            _handle_username_confirm(chat_id, user_msg_id, text, lang)
            return

        # ── БАТЫРМАЛАР ─────────────────────────────────────────────────────
        if text in ("⚙️ Баптаулар", "⚙️ Настройки"):
            send_chat_action(chat_id, "typing")
            prem_text = t("settings_free_for_all", lang)
            settings_text = t('settings_title', lang, name=first_name, premium=prem_text)
            settings_btns = [[{"text": t('btn_change_language', lang),
                                "callback_data": "settings:language", "style": "primary"}]]
            send_message(chat_id, settings_text, reply_markup={"inline_keyboard": settings_btns},
                         reply_to_message_id=user_msg_id)
            return

        elif text in ("🎁 Premium сыйлау", "🎁 Подарить Premium"):
            send_chat_action(chat_id, "typing")
            gift_markup = {
                "inline_keyboard": [
                    [{"text": t("gift_btn_link", lang), "callback_data": "gift_type:link", "style": "success"}],
                    [{"text": t("gift_btn_inline", lang), "callback_data": "gift_type:inline", "style": "success"}],
                    [{"text": t("gift_btn_username", lang), "callback_data": "gift_type:username", "style": "success"}]
                ]
            }
            gift_text = t("gift_menu_text", lang)
            quote = get_quote("gift_received", lang)
            if quote:
                gift_text += f"\n\n{quote}"
            bot_msg_id = send_message(chat_id, gift_text,
                                      reply_markup=gift_markup, reply_to_message_id=user_msg_id)
            if bot_msg_id:
                set_message_reaction(chat_id, bot_msg_id, "🤔")
            return

        elif text in ("⭐️ Premium алу", "⭐️ Купить Premium"):
            send_chat_action(chat_id, "typing")
            from tariffs import get_tariff_keyboard
            buy_text = t("premium_buy_text", lang)
            quote = get_quote("payment", lang)
            if quote:
                buy_text += f"\n\n{quote}"
            send_message(chat_id, buy_text,
                         reply_markup=get_tariff_keyboard("buy", lang=lang),
                         reply_to_message_id=user_msg_id)
            return

        elif text.startswith("/start"):
            send_chat_action(chat_id, "typing")
            parts = text.split(" ")
            if len(parts) > 1 and parts[1].startswith("gift_"):
                gift_code = parts[1]
                success, buyer_name, gift_days = redeem_gift_code(gift_code, chat_id)
                if success:
                    from tariffs import TARIFFS
                    gift_label = next(
                        (tariff["label_ru"] if lang == "ru" else tariff["label"]
                         for tariff in TARIFFS if tariff["days"] == gift_days),
                        f"{gift_days} күн"
                    )
                    gift_msg = t("gift_received", lang, buyer=buyer_name, label=gift_label)
                    quote = get_quote("gift_received", lang)
                    if quote:
                        gift_msg += f"\n\n{quote}"
                    bot_msg_id = send_message(chat_id, gift_msg, reply_markup=_main_keyboard(lang),
                                              reply_to_message_id=user_msg_id,
                                              message_effect_id=EFFECT_HALAL)
                    set_message_reaction(chat_id, user_msg_id, "❤")
                    if bot_msg_id:
                        set_message_reaction(chat_id, bot_msg_id, "🎉")
                    add_user(chat_id, first_name, username)
                    save_chat_history(chat_id, "user", text)
                    save_chat_history(chat_id, "model", gift_msg)
                    log_to_bigquery(chat_id, "redeem_gift", gift_code, "Сыйлықты алды")
                    return
                else:
                    from db_core import db as _db
                    _doc = _db.collection("draft_gifts").document(gift_code).get()
                    if _doc.exists and str(_doc.to_dict().get("buyer_id", "")) == str(chat_id):
                        err_msg = t("gift_self_redeem", lang)
                    else:
                        err_msg = t("gift_invalid", lang)
                    send_message(chat_id, err_msg, reply_to_message_id=user_msg_id)

            if is_symbat:
                welcome_text = ("Сәлем, Ботам! ❤️\n\nБұл сенің сүйікті жігітің жасаған ҚМДБ Халал боты ғой. "
                                "Маған кез келген өнімнің атын жаз немесе суретін жібер, "
                                "мен сен үшін бәрін тауып беремін! 😘")
                bot_msg_id = send_message(chat_id, welcome_text, reply_markup=_main_keyboard(lang),
                                          reply_to_message_id=user_msg_id)
                set_message_reaction(chat_id, user_msg_id, "❤")
                if bot_msg_id:
                    set_message_reaction(chat_id, bot_msg_id, "❤")
                add_user(chat_id, first_name, username)
                save_chat_history(chat_id, "user", text)
                save_chat_history(chat_id, "model", welcome_text)
                log_to_bigquery(chat_id, "start", "/start", "Сымбат кірді")
            else:
                if username and username != "жоқ":
                    gift_code, buyer_name = get_pending_gift_for_username(username)
                    if gift_code:
                        success, _, gift_days = redeem_gift_code(gift_code, chat_id)
                        if success:
                            delete_pending_gift(username)
                            from tariffs import TARIFFS
                            gift_label = next(
                                (tariff["label_ru"] if lang == "ru" else tariff["label"]
                                 for tariff in TARIFFS if tariff["days"] == gift_days),
                                f"{gift_days} күн"
                            )
                            gift_msg = t("gift_pending_received", lang, buyer=buyer_name, label=gift_label)
                            quote = get_quote("gift_received", lang)
                            if quote:
                                gift_msg += f"\n\n{quote}"
                            bot_msg_id = send_message(chat_id, gift_msg, reply_markup=_main_keyboard(lang),
                                                      reply_to_message_id=user_msg_id,
                                                      message_effect_id=EFFECT_HALAL)
                            set_message_reaction(chat_id, user_msg_id, "❤")
                            if bot_msg_id:
                                set_message_reaction(chat_id, bot_msg_id, "🎉")
                            add_user(chat_id, first_name, username)
                            save_chat_history(chat_id, "user", text)
                            save_chat_history(chat_id, "model", gift_msg)
                            log_to_bigquery(chat_id, "redeem_pending_gift", gift_code, "Pending сыйлық алды")
                            return

                current_gender = get_user_gender(chat_id)
                if not current_gender:
                    lang_markup = {"inline_keyboard": [[
                        {"text": "🇰🇿 Қазақша", "callback_data": "lang:kz", "style": "primary"},
                        {"text": "🇷🇺 Русский", "callback_data": "lang:ru", "style": "primary"}
                    ]]}
                    send_message(chat_id, t('choose_language', 'kz'),
                                 reply_markup=lang_markup, reply_to_message_id=user_msg_id)
                    add_user(chat_id, first_name, username)
                    save_chat_history(chat_id, "user", text)
                    log_to_bigquery(chat_id, "start", "/start", "Жаңа қолданушы (Тіл сұралды)")
                else:
                    welcome_text = t('welcome_back', lang, name=first_name)
                    send_message(chat_id, welcome_text, reply_markup=_main_keyboard(lang),
                                 reply_to_message_id=user_msg_id)
                    save_chat_history(chat_id, "user", text)
                    save_chat_history(chat_id, "model", welcome_text)
                    log_to_bigquery(chat_id, "start", "/start", "Ескі қолданушы")

        else:
            # ── КЛАССИФИКАТОР ────────────────────────────────────────────────
            search_query = text
            go_to_chat = False

            if should_classify(text):
                action, extracted_query = classify_query(text)
                if action == "chat":
                    go_to_chat = True
                elif extracted_query:
                    search_query = extracted_query

            if go_to_chat:
                has_access, tier = check_access(chat_id, is_symbat)
                if not has_access:
                    _msg, _markup = _access_denied_msg(lang, tier)
                    log_to_bigquery(chat_id, "limit_hit", "ai_chat", "Лимит бітті")
                    send_message(chat_id, _msg, reply_markup=_markup, reply_to_message_id=user_msg_id)
                    return

                send_chat_action(chat_id, "typing")
                if tier in ["premium", "VIP"]:
                    set_message_reaction(chat_id, user_msg_id, random.choice(["✍", "👨‍💻"]))
                ai_reply = chat_with_ai(chat_id, text, is_symbat, chat_id=chat_id, message_id=user_msg_id)
                keys = {"inline_keyboard": [[
                    {"text": t("btn_good", lang), "callback_data": "fb:good:ai", "style": "success"},
                    {"text": t("btn_bad", lang), "callback_data": "fb:bad:ai", "style": "danger"}
                ]]}
                if ai_reply is not None:
                    bot_msg_id = send_message(chat_id, ai_reply, reply_markup=keys,
                                              reply_to_message_id=user_msg_id)
                    if tier in ["premium", "VIP"] and bot_msg_id:
                        set_message_reaction(chat_id, bot_msg_id, "👨‍💻")
                save_chat_history(chat_id, "user", text)
                save_chat_history(chat_id, "model", ai_reply or "")
                log_to_bigquery(chat_id, "ai_chat", text, "Классификатор: чат",
                                is_premium=(tier in ["premium", "VIP"]), result_count=0)
                increment_usage(chat_id)
                return

            # ── БІРІНШІ ІЗДЕУ ────────────────────────────────────────────────
            found_items = search_data(search_query)

            if found_items:
                # Базадан тікелей табылды ✅
                has_access, tier = check_access(chat_id, is_symbat)
                if not has_access:
                    _msg, _markup = _access_denied_msg(lang, tier)
                    log_to_bigquery(chat_id, "limit_hit", "text_search", "Лимит бітті")
                    send_message(chat_id, _msg, reply_markup=_markup, reply_to_message_id=user_msg_id)
                    return

                send_chat_action(chat_id, "typing")
                _send_search_results(chat_id, user_msg_id, found_items, text, lang, tier,
                                     log_action="text_search")
                increment_usage(chat_id)

            else:
                # ── AI #1: Іздеу терминін нормализациялау ────────────────────
                # Базадан табылмады → AI сұраудан нақты атауды шығарады
                # Мысалы: "Мексиси" → "Mexxi"
                has_access, tier = check_access(chat_id, is_symbat)
                if not has_access:
                    _msg, _markup = _access_denied_msg(lang, tier)
                    send_message(chat_id, _msg, reply_markup=_markup, reply_to_message_id=user_msg_id)
                    return

                send_chat_action(chat_id, "typing")
                normalized_query = extract_search_term(search_query)
                second_found = []

                if normalized_query:
                    print(f"[AI#1] '{search_query}' → '{normalized_query}'")
                    second_found = search_data(normalized_query)

                if second_found:
                    # Нормализациямен табылды ✅
                    if tier in ["premium", "VIP"]:
                        set_message_reaction(chat_id, user_msg_id, "🎉")
                    _send_search_results(chat_id, user_msg_id, second_found, text, lang, tier,
                                         log_action="text_search_normalized",
                                         log_status=f"AI нормализациямен: {normalized_query}")
                    increment_usage(chat_id)

                else:
                    # ── 4D: CLASSIFY → chat па, search па? ───────────────────
                    # Екі рет іздеп те табылмады.
                    # Енді classify_query арқылы тексереміз:
                    #   "сәлем", "қалайсың" → chat → chat_with_ai()
                    #   "тағам" (базада жоқ) → search → AI#2 not_found
                    print(f"[4D] Табылмады, classify_query шақырылады: '{text}'")
                    classify_action, _ = classify_query(text)

                    if classify_action == "chat":
                        # ── ЧАТ РЕЖИМІ ───────────────────────────────────────
                        print(f"[4D] classify=chat → chat_with_ai()")
                        send_chat_action(chat_id, "typing")
                        if tier in ["premium", "VIP"]:
                            set_message_reaction(chat_id, user_msg_id, random.choice(["✍", "👨‍💻"]))
                        ai_reply = chat_with_ai(chat_id, text, is_symbat,
                                                chat_id=chat_id, message_id=user_msg_id)
                        keys = {"inline_keyboard": [[
                            {"text": t("btn_good", lang), "callback_data": "fb:good:ai", "style": "success"},
                            {"text": t("btn_bad", lang), "callback_data": "fb:bad:ai", "style": "danger"}
                        ]]}
                        if ai_reply is not None:
                            bot_msg_id = send_message(chat_id, ai_reply, reply_markup=keys,
                                                      reply_to_message_id=user_msg_id)
                            if tier in ["premium", "VIP"] and bot_msg_id:
                                set_message_reaction(chat_id, bot_msg_id, "👨‍💻")
                        save_chat_history(chat_id, "user", text)
                        save_chat_history(chat_id, "model", ai_reply or "")
                        log_to_bigquery(chat_id, "ai_chat", text, "4D: classify→chat",
                                        is_premium=(tier in ["premium", "VIP"]), result_count=0)
                        increment_usage(chat_id)

                    else:
                        # ── AI #2: Қатаң "табылмады" жауабы ─────────────────
                        # classify=search, бірақ базада жоқ → "базадан табылмады"
                        print(f"[4D] classify=search → get_not_found_reply()")
                        if tier in ["premium", "VIP"]:
                            set_message_reaction(chat_id, user_msg_id, "😔")

                        not_found_reply = get_not_found_reply(search_query, normalized_query, lang=lang)
                        if tier in ["premium", "VIP"]:
                            quote = get_quote("not_found", lang)
                            if quote:
                                not_found_reply += f"\n\n{quote}"
                        keys = {"inline_keyboard": [[
                            {"text": t("btn_good", lang), "callback_data": "fb:good:ai", "style": "success"},
                            {"text": t("btn_bad", lang), "callback_data": "fb:bad:ai", "style": "danger"}
                        ]]}
                        send_message(chat_id, not_found_reply, reply_markup=keys,
                                     reply_to_message_id=user_msg_id)
                        save_chat_history(chat_id, "user", text)
                        save_chat_history(chat_id, "model", not_found_reply)
                        log_to_bigquery(chat_id, "not_found", text,
                                        f"4D: classify→search, табылмады (normalized: {normalized_query})",
                                        is_premium=(tier in ["premium", "VIP"]), result_count=0)
                        increment_usage(chat_id)


# ── ІЗДЕУ НӘТИЖЕЛЕРІН ЖІБЕРУ (ортақ хелпер) ───────────────────────────────

def _send_search_results(chat_id, user_msg_id, found_items, original_text, lang, tier,
                          log_action="text_search", log_status=None):
    """1 немесе бірнеше нәтижені форматтап жіберетін ортақ функция"""
    if len(found_items) == 1:
        confidence = found_items[0].get('confidence', 'exact')
        reply_text, markup = format_detail_message(found_items[0], confidence=confidence,
                                                   query_text=original_text, lang=lang, tier=tier)
        effect = None
        reaction = None
        if tier in ["premium", "VIP"]:
            status_text = found_items[0].get("status", "")
            if "Белсенді" in status_text or "Рұқсат" in status_text:
                effect = EFFECT_HALAL
                reaction = "🎉"
            elif "Мерзімі" in status_text or "⚠️" in status_text or "Қайтарып" in status_text or "🚫" in status_text:
                effect = EFFECT_EXPIRED
                reaction = "👎"
            elif confidence == 'fuzzy':
                reaction = "🤔"

        image_url = found_items[0].get("image_url", "")
        if image_url:
            bot_msg_id = send_photo_message(chat_id, image_url, reply_text,
                                            reply_markup=markup, message_effect_id=effect,
                                            reply_to_message_id=user_msg_id)
        else:
            bot_msg_id = send_message(chat_id, reply_text, reply_markup=markup,
                                      message_effect_id=effect, reply_to_message_id=user_msg_id)
        if reaction and bot_msg_id:
            set_message_reaction(chat_id, bot_msg_id, reaction)

        save_chat_history(chat_id, "user", original_text)
        save_chat_history(chat_id, "model", reply_text)
        log_to_bigquery(chat_id, log_action, original_text,
                        log_status or f"Табылды (1/{confidence})",
                        is_premium=(tier in ["premium", "VIP"]), result_count=1, confidence=confidence)
    else:
        exact_items = [i for i in found_items if i.get('confidence') == 'exact']
        fuzzy_items = [i for i in found_items if i.get('confidence') == 'fuzzy']
        all_items = exact_items + fuzzy_items
        from db_core import save_search_session
        session_id = save_search_session(chat_id, all_items)
        reply_text, keyboard = _build_search_results_page(all_items, 1, 5,
                                                          session_id=session_id, lang=lang)
        bot_msg_id = send_message(chat_id, reply_text,
                                  reply_markup={"inline_keyboard": keyboard},
                                  reply_to_message_id=user_msg_id)
        if tier in ["premium", "VIP"] and bot_msg_id:
            set_message_reaction(chat_id, bot_msg_id, "🤔")
        save_chat_history(chat_id, "user", original_text)
        save_chat_history(chat_id, "model", reply_text)
        log_to_bigquery(chat_id, log_action, original_text,
                        log_status or f"Табылды (Көп/{len(all_items)})",
                        is_premium=(tier in ["premium", "VIP"]), result_count=len(all_items))


# ── USERNAME ӨҢДЕУШІЛЕРІ ────────────────────────────────────────────────────

def _handle_username_input(chat_id, user_msg_id, text, lang='kz'):
    raw = text.strip()
    cancel_markup = {"inline_keyboard": [[
        {"text": "❌ Бас тарту", "callback_data": "gift_username_cancel", "style": "danger"}
    ]]}
    if _has_cyrillic(raw):
        send_message(chat_id, t("username_cyrillic_error", lang),
                     reply_markup=cancel_markup, reply_to_message_id=user_msg_id)
        return
    if not raw.startswith("@"):
        send_message(chat_id, t("username_no_at_error", lang, raw=raw),
                     reply_markup=cancel_markup, reply_to_message_id=user_msg_id)
        return
    if not USERNAME_RE.match(raw):
        send_message(chat_id, t("username_format_error", lang, raw=raw),
                     reply_markup=cancel_markup, reply_to_message_id=user_msg_id)
        return

    clean = raw.lstrip("@")
    set_confirm_username(chat_id, clean)
    confirm_markup = {
        "inline_keyboard": [
            [{"text": t("username_confirm_yes", lang, clean=clean),
              "callback_data": f"gift_username_confirm:{clean}", "style": "success"}],
            [{"text": t("username_confirm_no", lang),
              "callback_data": "gift_username_retry", "style": "primary"}],
            [{"text": t("btn_cancel", lang),
              "callback_data": "gift_username_cancel", "style": "danger"}]
        ]
    }
    send_message(chat_id, t("username_confirm_text", lang, clean=clean),
                 reply_markup=confirm_markup, reply_to_message_id=user_msg_id)

def _handle_username_confirm(chat_id, user_msg_id, text, lang='kz'):
    pending = get_pending_username(chat_id)
    if pending:
        send_message(chat_id, t("username_pending", lang, pending=pending),
                     reply_to_message_id=user_msg_id)


# ── ІЗДЕУ НӘТИЖЕЛЕРІ ПАГИНАЦИЯСЫ ───────────────────────────────────────────

def _build_search_results_page(all_items, page, per_page, session_id=None, query_text="", lang="kz"):
    import math
    total = len(all_items)
    total_pages = math.ceil(total / per_page)
    if page > total_pages: page = total_pages
    if page < 1: page = 1
    start = (page - 1) * per_page
    items = all_items[start:start + per_page]

    reply_text = t("search_results_header", lang, total=total, page=page, total_pages=total_pages)
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
            reply_text += t("search_fuzzy_note", lang)
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
        keyboard.append([{"text": f"{idx}. {prefix}«{item['title']}»",
                          "callback_data": f"itm:{t_code}:{item['id']}", "style": btn_style}])

    if session_id:
        nav = []
        if page > 1:
            nav.append({"text": t("btn_back", lang),
                        "callback_data": f"srch:{page-1}:{session_id}", "style": "primary"})
        if page < total_pages:
            nav.append({"text": t("btn_next", lang),
                        "callback_data": f"srch:{page+1}:{session_id}", "style": "primary"})
        if nav:
            keyboard.append(nav)

    return reply_text, keyboard
