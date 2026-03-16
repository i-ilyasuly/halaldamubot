import re
import random
from bot_sender import send_message, send_photo_message, edit_message, send_chat_action, download_photo, set_message_reaction, send_invoice, send_gift_invoice
from db_core import (add_user, save_chat_history, log_to_bigquery, check_access, 
                     increment_usage, revoke_premium, get_user_gender, redeem_gift_code,
                     get_pending_gift_for_username, delete_pending_gift, grant_premium)
from search_logic import search_data, get_nearby_companies
from formatters import format_detail_message
from ai_core import handle_photo, chat_with_ai
from classifier import classify_query, should_classify
from payments import process_successful_payment, get_premium_keyboard
from gift_state import (set_awaiting_username, is_awaiting_username,
                        set_confirm_username, get_pending_username, clear_state)

SYMBAT_ID = 1042456426
EFFECT_HALAL = "5046509860389126442"
EFFECT_EXPIRED = "5104858069142078462"

# Username валидациясы: @ + тек латын/сан/_  (5-32 символ)
USERNAME_RE = re.compile(r'^@[a-zA-Z0-9_]{5,32}$')

def _has_cyrillic(text):
    return bool(re.search(r'[а-яёА-ЯЁәіңғүұқөһӘІҢҒҮҰҚӨҺ]', text))

def _main_keyboard():
    return {
        "keyboard": [
            [{"text": "📍 Тұрған орнымды жіберу", "request_location": True}],
            [{"text": "⭐️ Premium алу"}, {"text": "🎁 Premium сыйлау"}],
            [{"text": "⚙️ Баптаулар"}]
        ],
        "resize_keyboard": True
    }

def handle_message(msg):
    chat_id = msg["chat"]["id"]
    user_msg_id = msg["message_id"] 
    
    first_name = msg["chat"].get("first_name", "Досым")
    username = msg["chat"].get("username", "жоқ")
    is_symbat = (chat_id == SYMBAT_ID)
    
    if "successful_payment" in msg:
        process_successful_payment(msg)
        return
        
    if "refunded_payment" in msg:
        revoke_premium(chat_id)
        send_message(chat_id, "⚠️ Сіз төлемді қайтарып алдыңыз. Premium статусыңыз өшірілді.", reply_to_message_id=user_msg_id)
        return
    
    if "photo" in msg:
        has_access, tier = check_access(chat_id, is_symbat)
        if not has_access:
            send_message(chat_id, tier, reply_markup=get_premium_keyboard(), reply_to_message_id=user_msg_id)
            return
        
        # Фото жібергенде gift state тазаланады
        clear_state(chat_id)
        send_chat_action(chat_id, "typing")
        
        if tier in ["premium", "VIP"]:
            loading_reaction = random.choice(["🤔", "👀", "⚡", "🤓", "👨‍💻"])
            set_message_reaction(chat_id, user_msg_id, loading_reaction)
            
        photo_id = msg["photo"][-1]["file_id"]
        image_bytes = download_photo(photo_id)
        if image_bytes:
            result_msg, markup, item_image_url = handle_photo(image_bytes, chat_id, username)
            
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
            log_to_bigquery(chat_id, "photo_search", "Сурет", "Тексерілді")
            increment_usage(chat_id)

    elif "location" in msg:
        has_access, tier = check_access(chat_id, is_symbat)
        if not has_access:
            send_message(chat_id, tier, reply_markup=get_premium_keyboard(), reply_to_message_id=user_msg_id)
            return
        
        # Кез келген state болса тазалаймыз — локация кез келген уақытта жіберіледі
        clear_state(chat_id)
        send_chat_action(chat_id, "find_location")
            
        lat, lon = msg["location"]["latitude"], msg["location"]["longitude"]
        text, markup = get_nearby_companies(lat, lon, page=1)

        bot_msg_id = send_message(chat_id, text, reply_markup=markup)

        # Локация хабарын өшіреміз — чат таза болсын, карта превью қалмасын
        from bot_sender import delete_message
        delete_message(chat_id, user_msg_id)
        
        if tier in ["premium", "VIP"] and bot_msg_id:
            set_message_reaction(chat_id, bot_msg_id, "⚡")
            
        log_to_bigquery(chat_id, "location_search", f"{lat}, {lon}", "Тізім берілді")
        increment_usage(chat_id)

    elif "text" in msg:
        text = msg["text"]

        # ── USERNAME ЕНГІЗУ РЕЖИМІ ──────────────────────────────────────────
        if is_awaiting_username(chat_id):
            _handle_username_input(chat_id, user_msg_id, text)
            return

        # ── USERNAME РАСТАУ РЕЖИМІ ──────────────────────────────────────────
        if get_pending_username(chat_id) is not None:
            _handle_username_confirm(chat_id, user_msg_id, text)
            return

        # ── ҚАЛЫПТЫ БАТЫРМАЛАР ─────────────────────────────────────────────

        if text == "⚙️ Баптаулар":
            send_chat_action(chat_id, "typing")
            from db_core import db, _now
            from datetime import timezone
            doc = db.collection("users").document(str(chat_id)).get()
            prem_text = "❌ Premium жоқ"
            if doc.exists:
                prem_until = doc.to_dict().get("premium_until")
                if prem_until:
                    from datetime import datetime
                    if isinstance(prem_until, datetime):
                        if prem_until.tzinfo is None:
                            prem_until = prem_until.replace(tzinfo=timezone.utc)
                        now = _now()
                        if prem_until > now:
                            delta = prem_until - now
                            total_days = delta.days
                            months = total_days // 30
                            days = total_days % 30
                            if months > 0 and days > 0:
                                prem_text = f"✅ Premium белсенді\n📅 {prem_until.strftime('%d.%m.%Y')} дейін\n⏳ {months} ай {days} күн қалды"
                            elif months > 0:
                                prem_text = f"✅ Premium белсенді\n📅 {prem_until.strftime('%d.%m.%Y')} дейін\n⏳ {months} ай қалды"
                            else:
                                prem_text = f"✅ Premium белсенді\n📅 {prem_until.strftime('%d.%m.%Y')} дейін\n⏳ {days} күн қалды"
                        else:
                            prem_text = "❌ Premium мерзімі өткен"

            settings_text = (
                f"⚙️ <b>Баптаулар</b>\n\n"
                f"👤 <b>Есімің:</b> {first_name}\n"
                f"🏆 <b>Тариф:</b> {prem_text}"
            )
            settings_markup = {
                "inline_keyboard": [
                    [{"text": "⭐️ Premium алу", "callback_data": "buy_premium"}]
                ] if "❌" in prem_text else []
            }
            send_message(chat_id, settings_text, reply_markup=settings_markup, reply_to_message_id=user_msg_id)
            return

        elif text == "🎁 Premium сыйлау":
            send_chat_action(chat_id, "typing")
            gift_text = (
                "🎁 <b>Premium сыйлау</b>\n\n"
                "Сыйлықты досыңызға қалай жібергіңіз келеді?\n\n"
                "1️⃣ <b>Сілтеме арқылы</b> — WhatsApp, Инстаграм немесе басқа желілер арқылы жіберуге ыңғайлы.\n"
                "2️⃣ <b>Телеграм арқылы</b> — Досыңыздың Телеграм чатына әдемі сыйлық қорабын жіберу үшін.\n"
                "3️⃣ <b>@username арқылы</b> — Telegram юзернеймін білсеңіз, тікелей соған жіберіледі."
            )
            gift_markup = {
                "inline_keyboard": [
                    [{"text": "🔗 Сілтеме арқылы", "callback_data": "gift_type:link"}],
                    [{"text": "💬 Телеграм арқылы (Әдемі)", "callback_data": "gift_type:inline"}],
                    [{"text": "👤 @username арқылы", "callback_data": "gift_type:username"}]
                ]
            }
            bot_msg_id = send_message(chat_id, gift_text, reply_markup=gift_markup, reply_to_message_id=user_msg_id)
            if bot_msg_id:
                set_message_reaction(chat_id, bot_msg_id, "🤔")
            return

        elif text == "⭐️ Premium алу":
            send_chat_action(chat_id, "typing")
            from tariffs import get_tariff_keyboard
            tariff_text = (
                "⭐️ <b>Premium жазылым</b>\n\n"
                "Шексіз іздеу, суретпен тану және жақын маңдағы халал орындарды шектеусіз пайдаланыңыз!\n\n"
                "Қанша мерзімге алғыңыз келеді?"
            )
            send_message(chat_id, tariff_text, reply_markup=get_tariff_keyboard("buy"), reply_to_message_id=user_msg_id)
            return

        elif text.startswith("/start"):
            send_chat_action(chat_id, "typing")
            
            parts = text.split(" ")
            if len(parts) > 1 and parts[1].startswith("gift_"):
                gift_code = parts[1]
                success, buyer_name, gift_days = redeem_gift_code(gift_code, chat_id)
                
                if success:
                    from tariffs import TARIFFS
                    # Күн санына қарап тариф атауын табамыз
                    gift_label = next((t["label"] for t in TARIFFS if t["days"] == gift_days), f"{gift_days} күн")
                    gift_msg = f"🎉 <b>Құттықтаймыз!</b>\n\n<b>{buyer_name}</b> сізге <b>{gift_label} Premium</b> сыйлады! 🎁\nЕнді сіз ботты шектеусіз қолдана аласыз. Іздеуді бастай беріңіз!"
                    bot_msg_id = send_message(chat_id, gift_msg, reply_markup=_main_keyboard(), reply_to_message_id=user_msg_id, message_effect_id=EFFECT_HALAL)
                    
                    set_message_reaction(chat_id, user_msg_id, "❤")
                    if bot_msg_id: set_message_reaction(chat_id, bot_msg_id, "🎉")
                    
                    add_user(chat_id, first_name, username)
                    save_chat_history(chat_id, "user", text)
                    save_chat_history(chat_id, "model", gift_msg)
                    log_to_bigquery(chat_id, "redeem_gift", gift_code, "Сыйлықты алды")
                    return
                else:
                    err_msg = "❌ <b>Қате:</b> Бұл сыйлық сілтемесі жарамсыз немесе оны басқа адам қолданып қойған."
                    send_message(chat_id, err_msg, reply_to_message_id=user_msg_id)
            
            if is_symbat:
                welcome_text = f"Сәлем, Ботам! ❤️\n\nБұл сенің сүйікті жігітің жасаған ҚМДБ Халал боты ғой. Маған кез келген өнімнің атын жаз немесе суретін жібер, мен сен үшін бәрін тауып беремін! 😘"
                bot_msg_id = send_message(chat_id, welcome_text, reply_markup=_main_keyboard(), reply_to_message_id=user_msg_id)
                set_message_reaction(chat_id, user_msg_id, "❤")
                if bot_msg_id: set_message_reaction(chat_id, bot_msg_id, "❤")
                add_user(chat_id, first_name, username)
                save_chat_history(chat_id, "user", text)
                save_chat_history(chat_id, "model", welcome_text)
                log_to_bigquery(chat_id, "start", "/start", "Сымбат кірді")
            else:
                # Pending gift тексеру — @username арқылы сыйлық күтіп тұр ма?
                if username and username != "жоқ":
                    gift_code, buyer_name = get_pending_gift_for_username(username)
                    if gift_code:
                        success, _, gift_days = redeem_gift_code(gift_code, chat_id)
                        if success:
                            delete_pending_gift(username)
                            from tariffs import TARIFFS
                            gift_label = next((t["label"] for t in TARIFFS if t["days"] == gift_days), f"{gift_days} күн")
                            gift_msg = (
                                f"🎁 <b>Сізге сыйлық бар екен!</b>\n\n"
                                f"<b>{buyer_name}</b> сізге <b>{gift_label} Premium</b> сыйлапты! 🎉\n\n"
                                f"Ботты шектеусіз қолдана бастаңыз 👇"
                            )
                            bot_msg_id = send_message(chat_id, gift_msg, reply_markup=_main_keyboard(), reply_to_message_id=user_msg_id, message_effect_id=EFFECT_HALAL)
                            set_message_reaction(chat_id, user_msg_id, "❤")
                            if bot_msg_id: set_message_reaction(chat_id, bot_msg_id, "🎉")
                            add_user(chat_id, first_name, username)
                            save_chat_history(chat_id, "user", text)
                            save_chat_history(chat_id, "model", gift_msg)
                            log_to_bigquery(chat_id, "redeem_pending_gift", gift_code, "Pending сыйлық алды")
                            return

                current_gender = get_user_gender(chat_id)
                if not current_gender:
                    welcome_text = f"Сәлем, {first_name}! 👋\n\nМен — кез келген өнімнің немесе дәмхананың халал екенін тез әрі нақты тексеріп беретін көмекшіңізбін.\n\nЖақынырақ танысу үшін, жынысыңызды таңдаңызшы:"
                    gender_markup = {"inline_keyboard": [[
                        {"text": "🙎‍♂️ Ер азамат", "callback_data": "gender:male"},
                        {"text": "🙎‍♀️ Нәзік жанды", "callback_data": "gender:female"}
                    ]]}
                    send_message(chat_id, welcome_text, reply_markup=gender_markup, reply_to_message_id=user_msg_id)
                    add_user(chat_id, first_name, username)
                    save_chat_history(chat_id, "user", text)
                    log_to_bigquery(chat_id, "start", "/start", "Жаңа қолданушы (Жыныс сұралды)")
                else:
                    welcome_text = f"Қайта оралуыңызбен, {first_name}! 👋\n\nМен жұмысқа дайынмын. Тексеретін өнім бар ма немесе тамақтанатын орын іздейміз бе?"
                    send_message(chat_id, welcome_text, reply_markup=_main_keyboard(), reply_to_message_id=user_msg_id)
                    save_chat_history(chat_id, "user", text)
                    save_chat_history(chat_id, "model", welcome_text)
                    log_to_bigquery(chat_id, "start", "/start", "Ескі қолданушы")
                    
        else:
            # ── КЛАССИФИКАТОР: 4+ сөз болса AI анықтайды ────────────────────
            search_query = text  # Әдепкі — бүкіл мәтінді іздейміз
            go_to_chat = False   # Тікелей AI чатқа жіберу керек пе

            if should_classify(text):
                action, extracted_query = classify_query(text)
                if action == "chat":
                    go_to_chat = True
                elif extracted_query:
                    search_query = extracted_query  # AI шығарған нақты атауды іздейміз

            # AI чатқа жіберу керек болса — іздеусіз тікелей
            if go_to_chat:
                has_access, tier = check_access(chat_id, is_symbat)
                if not has_access:
                    send_message(chat_id, tier, reply_markup=get_premium_keyboard(), reply_to_message_id=user_msg_id)
                    return
                send_chat_action(chat_id, "typing")
                if tier in ["premium", "VIP"]:
                    set_message_reaction(chat_id, user_msg_id, random.choice(["✍", "👨‍💻"]))
                ai_reply = chat_with_ai(chat_id, text, is_symbat, chat_id=chat_id, message_id=user_msg_id)
                keys = {"inline_keyboard": [[
                    {"text": "👍 Пайдалы", "callback_data": "fb:good:ai"},
                    {"text": "👎 Қате", "callback_data": "fb:bad:ai"}
                ]]}
                if ai_reply is not None:
                    # Streaming болмаса (None емес) — тікелей жіберіледі
                    bot_msg_id = send_message(chat_id, ai_reply, reply_markup=keys, reply_to_message_id=user_msg_id)
                    if tier in ["premium", "VIP"] and bot_msg_id:
                        set_message_reaction(chat_id, bot_msg_id, "👨‍💻")
                save_chat_history(chat_id, "user", text)
                save_chat_history(chat_id, "model", ai_reply or "")
                log_to_bigquery(chat_id, "ai_chat", text, "Классификатор: чат")
                return

            found_items = search_data(search_query)
            
            if found_items:
                has_access, tier = check_access(chat_id, is_symbat)
                if not has_access:
                    send_message(chat_id, tier, reply_markup=get_premium_keyboard(), reply_to_message_id=user_msg_id)
                    return
                    
                send_chat_action(chat_id, "typing")
                
                if len(found_items) == 1:
                    confidence = found_items[0].get('confidence', 'exact')
                    reply_text, markup = format_detail_message(found_items[0], confidence=confidence, query_text=text)
                    effect = None
                    reaction = None
                    # Fuzzy нәтижеде шашу эффектісі болмасын — сенімсіз
                    if confidence == 'exact' and tier in ["premium", "VIP"]:
                        status_text = found_items[0].get("status", "")
                        if "Белсенді" in status_text or "Рұқсат" in status_text:
                            effect = EFFECT_HALAL
                            reaction = "🎉"
                        elif "Мерзімі" in status_text or "⚠️" in status_text or "Қайтарып" in status_text or "🚫" in status_text:
                            effect = EFFECT_EXPIRED
                            reaction = "👎"
                    elif confidence == 'fuzzy' and tier in ["premium", "VIP"]:
                        reaction = "🤔"  # Fuzzy нәтижеде сұрақ белгісі
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
                    save_chat_history(chat_id, "user", text)
                    save_chat_history(chat_id, "model", reply_text)
                    log_to_bigquery(chat_id, "text_search", text, f"Табылды (1/{confidence})")
                    increment_usage(chat_id)
                else:
                    # Exact және fuzzy нәтижелерді бөліп көрсетеміз
                    exact_items = [i for i in found_items[:5] if i.get('confidence') == 'exact']
                    fuzzy_items = [i for i in found_items[:5] if i.get('confidence') == 'fuzzy']

                    reply_text = f"🔍 <b>Мен бірнеше нұсқа таптым. Сізге нақты қайсысы керек?</b>\n\n"
                    keyboard = []
                    display_items = exact_items + fuzzy_items

                    for idx, item in enumerate(display_items):
                        confidence = item.get('confidence', 'exact')
                        prefix = "❓ " if confidence == 'fuzzy' else ""
                        if item['type'] == 'Мекеме':
                            desc_text = f"📍 {item.get('address', '')}"
                        else:
                            desc_text = f"🏷 {item.get('desc', '')}"
                        reply_text += f"<b>{idx+1}. {prefix}«{item['title']}»</b>\n{desc_text}\n"
                        if confidence == 'fuzzy':
                            reply_text += f"<i>⚠️ Іздеген атауыңызға ұқсас, бірақ нақты сәйкес емес</i>\n"
                        reply_text += "\n"
                        t_code = "c" if item['type'] == "Мекеме" else "i"
                        keyboard.append([{"text": f"{idx+1}. {prefix}«{item['title']}»", "callback_data": f"itm:{t_code}:{item['id']}"}])

                    bot_msg_id = send_message(chat_id, reply_text, reply_markup={"inline_keyboard": keyboard}, reply_to_message_id=user_msg_id)
                    if tier in ["premium", "VIP"] and bot_msg_id:
                        set_message_reaction(chat_id, bot_msg_id, "🤔")
                    save_chat_history(chat_id, "user", text)
                    save_chat_history(chat_id, "model", reply_text)
                    log_to_bigquery(chat_id, "text_search", text, "Табылды (Көп)")
                    increment_usage(chat_id)
            else:
                has_access, tier = check_access(chat_id, is_symbat)
                if not has_access:
                    send_message(chat_id, tier, reply_markup=get_premium_keyboard(), reply_to_message_id=user_msg_id)
                    return
                send_chat_action(chat_id, "typing")
                if tier in ["premium", "VIP"]:
                    ai_loading_reaction = random.choice(["✍", "👨‍💻"])
                    set_message_reaction(chat_id, user_msg_id, ai_loading_reaction)
                ai_reply = chat_with_ai(chat_id, text, is_symbat, chat_id=chat_id, message_id=user_msg_id)
                keys = {"inline_keyboard": [[
                    {"text": "👍 Пайдалы", "callback_data": "fb:good:ai"},
                    {"text": "👎 Қате", "callback_data": "fb:bad:ai"}
                ]]}
                if ai_reply is not None:
                    # Streaming болмаса (None емес) — тікелей жіберіледі
                    bot_msg_id = send_message(chat_id, ai_reply, reply_markup=keys, reply_to_message_id=user_msg_id)
                    if tier in ["premium", "VIP"] and bot_msg_id:
                        set_message_reaction(chat_id, bot_msg_id, "👨‍💻")
                save_chat_history(chat_id, "user", text)    
                save_chat_history(chat_id, "model", ai_reply or "")
                log_to_bigquery(chat_id, "ai_chat", text, "Табылмады/AI жауап берді")


# ── USERNAME ӨҢДЕУШІЛЕРІ ────────────────────────────────────────────────────

def _handle_username_input(chat_id, user_msg_id, text):
    """Пайдаланушы @username жазғанда валидациялау"""
    raw = text.strip()

    # Бас тарту батырмасы — барлық қате хабарларда қайталанады
    cancel_markup = {
        "inline_keyboard": [[
            {"text": "❌ Бас тарту", "callback_data": "gift_username_cancel"}
        ]]
    }

    # Кирилица тексеру
    if _has_cyrillic(raw):
        send_message(
            chat_id,
            "❌ <b>Қате:</b> Юзернеймде кириллица әріптер болмауы керек.\n\n"
            "Telegram юзернеймі тек <b>латын әріптерінен</b> тұрады.\n"
            "Мысал: <code>@aibek_kz</code>\n\n"
            "Қайтадан жазыңыз 👇",
            reply_markup=cancel_markup,
            reply_to_message_id=user_msg_id
        )
        return

    # @ жоқ тексеру
    if not raw.startswith("@"):
        send_message(
            chat_id,
            "❌ <b>Қате:</b> Юзернейм міндетті түрде <b>@</b> белгісінен басталуы керек.\n\n"
            f"Сіз жазғаныңыз: <code>{raw}</code>\n"
            f"Дұрысы: <code>@{raw}</code>\n\n"
            "Қайтадан жазыңыз 👇",
            reply_markup=cancel_markup,
            reply_to_message_id=user_msg_id
        )
        return

    # Формат тексеру (латын + сан + _ ғана, 5-32 символ)
    if not USERNAME_RE.match(raw):
        send_message(
            chat_id,
            "❌ <b>Қате формат.</b>\n\n"
            "Telegram юзернейм ережелері:\n"
            "• @ белгісінен басталуы керек\n"
            "• Тек латын әріптері, сандар және _ қолданылады\n"
            "• Ұзындығы 5–32 символ\n\n"
            f"Сіз жазғаныңыз: <code>{raw}</code>\n\n"
            "Қайтадан жазыңыз 👇",
            reply_markup=cancel_markup,
            reply_to_message_id=user_msg_id
        )
        return

    # Дұрыс — растауға өту (бас тарту батырмасы мұнда да бар)
    clean = raw.lstrip("@")
    set_confirm_username(chat_id, clean)

    confirm_text = (
        f"✅ Юзернейм қабылданды!\n\n"
        f"Сыйлық мына адамға жіберіледі: <b>@{clean}</b>\n\n"
        f"⚠️ <b>Назар аударыңыз:</b> Растағаннан кейін юзернеймді өзгерту мүмкін болмайды.\n\n"
        f"Растайсыз ба?"
    )
    confirm_markup = {
        "inline_keyboard": [
            [{"text": f"✅ Иә, @{clean} — дұрыс", "callback_data": f"gift_username_confirm:{clean}"}],
            [{"text": "✏️ Жоқ, өзгертемін", "callback_data": "gift_username_retry"}],
            [{"text": "❌ Бас тарту", "callback_data": "gift_username_cancel"}]
        ]
    }
    send_message(chat_id, confirm_text, reply_markup=confirm_markup, reply_to_message_id=user_msg_id)


def _handle_username_confirm(chat_id, user_msg_id, text):
    """Rastau күтіп тұрғанда қайта мәтін жазса — ескерту"""
    pending = get_pending_username(chat_id)
    if pending:
        send_message(
            chat_id,
            f"⏳ Жоғарыдағы батырмалар арқылы <b>@{pending}</b> юзернеймін растаңыз немесе өзгертіңіз.",
            reply_to_message_id=user_msg_id
        )
