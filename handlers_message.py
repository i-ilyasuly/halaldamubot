import random
from bot_sender import send_message, edit_message, send_chat_action, delete_message, download_photo, set_message_reaction, send_invoice, send_gift_invoice
from db_core import (add_user, save_chat_history, log_to_bigquery, check_access, 
                     increment_usage, revoke_premium, get_user_gender, redeem_gift_code)
from search_logic import search_data, get_nearby_companies
from formatters import format_detail_message
from ai_core import handle_photo, chat_with_ai
from payments import process_successful_payment, get_premium_keyboard

SYMBAT_ID = 1042456426
EFFECT_HALAL = "5046509860389126442"    
EFFECT_EXPIRED = "5104858069142078462"  

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
        
        send_chat_action(chat_id, "typing")
        
        if tier in ["premium", "VIP"]:
            loading_reaction = random.choice(["🤔", "👀", "⚡", "🤓", "👨‍💻"])
            set_message_reaction(chat_id, user_msg_id, loading_reaction)
            
        photo_id = msg["photo"][-1]["file_id"]
        image_bytes = download_photo(photo_id)
        if image_bytes:
            result_msg, markup = handle_photo(image_bytes, chat_id, username)
            
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
            
            bot_msg_id = send_message(chat_id, result_msg, reply_markup=markup, message_effect_id=effect, reply_to_message_id=user_msg_id)
            
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
        
        send_chat_action(chat_id, "find_location")
            
        lat, lon = msg["location"]["latitude"], msg["location"]["longitude"]
        text, markup = get_nearby_companies(lat, lon, page=1)
        
        bot_msg_id = send_message(chat_id, text, reply_markup=markup, reply_to_message_id=user_msg_id)
        
        if tier in ["premium", "VIP"] and bot_msg_id:
            set_message_reaction(chat_id, bot_msg_id, "⚡")
            
        log_to_bigquery(chat_id, "location_search", f"{lat}, {lon}", "Тізім берілді")
        increment_usage(chat_id)

    elif "text" in msg:
        text = msg["text"]
        
        main_keyboard = {
            "keyboard": [[{"text": "📍 Тұрған орнымды жіберу", "request_location": True}],[{"text": "⭐️ Premium алу"}, {"text": "🎁 Premium сыйлау"}]
            ],
            "resize_keyboard": True
        }

        # ЖАҢА: Таңдау жасау мүмкіндігі (Invoice алдында)
        if text == "🎁 Premium сыйлау":
            choice_text = "🎁 <b>Сыйлықты қалай жеткізгіңіз келеді?</b>\n\nТөлем жасамас бұрын ыңғайлы әдісті таңдаңыз:"
            choice_markup = {"inline_keyboard": [[{"text": "🔗 Сілтеме арқылы", "callback_data": "gift_choice:link", "style": "primary"}],[{"text": "📤 Тікелей чатқа жіберу (Инлайн)", "callback_data": "gift_choice:inline", "style": "primary"}]
            ]}
            send_message(chat_id, choice_text, reply_markup=choice_markup, reply_to_message_id=user_msg_id)
            return

        elif text == "⭐️ Premium алу":
            send_invoice(chat_id)
            return

        elif text.startswith("/start"):
            send_chat_action(chat_id, "typing")
            
            parts = text.split(" ")
            if len(parts) > 1 and parts[1].startswith("gift_"):
                gift_code = parts[1]
                success, buyer_name = redeem_gift_code(gift_code, chat_id)
                
                if success:
                    gift_msg = f"🎉 <b>Құттықтаймыз!</b>\n\n<b>{buyer_name}</b> сізге <b>30 күн Premium</b> сыйлады! 🎁\nЕнді сіз ботты шектеусіз қолдана аласыз. Іздеуді бастай беріңіз!"
                    bot_msg_id = send_message(chat_id, gift_msg, reply_markup=main_keyboard, reply_to_message_id=user_msg_id, message_effect_id=EFFECT_HALAL)
                    
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
                bot_msg_id = send_message(chat_id, welcome_text, reply_markup=main_keyboard, reply_to_message_id=user_msg_id)
                
                set_message_reaction(chat_id, user_msg_id, "❤")
                if bot_msg_id: set_message_reaction(chat_id, bot_msg_id, "❤")
                
                add_user(chat_id, first_name, username)
                save_chat_history(chat_id, "user", text)
                save_chat_history(chat_id, "model", welcome_text)
                log_to_bigquery(chat_id, "start", "/start", "Сымбат кірді")
            else:
                current_gender = get_user_gender(chat_id)
                
                if not current_gender:
                    welcome_text = f"Сәлем, {first_name}! 👋\n\nМен — кез келген өнімнің немесе дәмхананың халал екенін тез әрі нақты тексеріп беретін көмекшіңізбін.\n\nЖақынырақ танысу үшін, жынысыңызды таңдаңызшы:"
                    gender_markup = {"inline_keyboard": [[
                         {"text": "🙎‍♂️ Ер азамат", "callback_data": "gender:male", "style": "primary"},
                         {"text": "🙎‍♀️ Нәзік жанды", "callback_data": "gender:female", "style": "primary"}]]}
                    send_message(chat_id, welcome_text, reply_markup=gender_markup, reply_to_message_id=user_msg_id)
                    
                    add_user(chat_id, first_name, username)
                    save_chat_history(chat_id, "user", text)
                    log_to_bigquery(chat_id, "start", "/start", "Жаңа қолданушы (Жыныс сұралды)")
                else:
                    welcome_text = f"Қайта оралуыңызбен, {first_name}! 👋\n\nМен жұмысқа дайынмын. Тексеретін өнім бар ма немесе тамақтанатын орын іздейміз бе?"
                    send_message(chat_id, welcome_text, reply_markup=main_keyboard, reply_to_message_id=user_msg_id)
                    
                    save_chat_history(chat_id, "user", text)
                    save_chat_history(chat_id, "model", welcome_text)
                    log_to_bigquery(chat_id, "start", "/start", "Ескі қолданушы")
                    
        else:
            found_items = search_data(text)
            
            if found_items:
                has_access, tier = check_access(chat_id, is_symbat)
                if not has_access:
                    send_message(chat_id, tier, reply_markup=get_premium_keyboard(), reply_to_message_id=user_msg_id)
                    return
                    
                send_chat_action(chat_id, "typing")
                
                if len(found_items) == 1:
                    reply_text, markup = format_detail_message(found_items[0])
                    
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
                            
                    bot_msg_id = send_message(chat_id, reply_text, reply_markup=markup, message_effect_id=effect, reply_to_message_id=user_msg_id)
                    
                    if reaction and bot_msg_id:
                        set_message_reaction(chat_id, bot_msg_id, reaction)
                    
                    save_chat_history(chat_id, "user", text)
                    save_chat_history(chat_id, "model", reply_text)
                    log_to_bigquery(chat_id, "text_search", text, "Табылды (1)")
                    increment_usage(chat_id)
                else:
                    reply_text = f"🔍 <b>Мен бірнеше нұсқа таптым. Сізге нақты қайсысы керек?</b>\n\n"
                    keyboard = []
                    for idx, item in enumerate(found_items[:5]):
                        if item['type'] == 'Мекеме':
                            desc_text = f"📍 {item.get('address', '')}"
                        else:
                            desc_text = f"🏷 {item.get('desc', '')}"
                            
                        reply_text += f"<b>{idx+1}. «{item['title']}»</b>\n{desc_text}\n\n"
                        t_code = "c" if item['type'] == "Мекеме" else "i"
                        keyboard.append([{"text": f"{idx+1}. «{item['title']}»", "callback_data": f"itm:{t_code}:{item['id']}", "style": "primary"}])
                        
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
                
                ai_reply = chat_with_ai(chat_id, text, is_symbat)
                
                keys = {"inline_keyboard": [[
                    {"text": "👍 Пайдалы", "callback_data": "fb:good:ai", "style": "success"}, 
                    {"text": "👎 Қате", "callback_data": "fb:bad:ai", "style": "danger"}
                ]]}
                
                bot_msg_id = send_message(chat_id, ai_reply, reply_markup=keys, reply_to_message_id=user_msg_id)
                
                if tier in ["premium", "VIP"] and bot_msg_id:
                    set_message_reaction(chat_id, bot_msg_id, "👨‍💻")
                    
                save_chat_history(chat_id, "user", text)    
                save_chat_history(chat_id, "model", ai_reply)
                log_to_bigquery(chat_id, "ai_chat", text, "Табылмады/AI жауап берді")
