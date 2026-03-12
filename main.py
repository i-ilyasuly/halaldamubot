import functions_framework
import uuid
from bot_sender import send_message, edit_message, answer_callback, answer_inline_query, download_photo
from db_core import (add_user, save_chat_history, log_to_bigquery, get_item_by_id, 
                     check_access, increment_usage, revoke_premium, clear_cache, 
                     get_user_gender, set_user_gender)
from search_logic import search_data, get_nearby_companies
from formatters import format_detail_message
from updater import update_database
from ai_core import handle_photo, chat_with_ai
from config import CRON_SECRET
from payments import get_premium_keyboard, handle_buy_premium_callback, process_pre_checkout, process_successful_payment

SYMBAT_ID = 1042456426

@functions_framework.http
def telegram_webhook(request):
    if request.method == "GET":
        if request.args.get("cron_key") == CRON_SECRET: 
            result = update_database()
            clear_cache()
            return result, 200
        return "Қате пароль", 403

    if request.method == "POST":
        update = request.get_json()
        
        if "pre_checkout_query" in update:
            process_pre_checkout(update)
            return "OK", 200

        if "callback_query" in update:
            cb = update["callback_query"]
            
            user_id = cb["from"]["id"] 
            data = cb["data"]
            
            is_inline = "inline_message_id" in cb
            
            if is_inline:
                chat_id = None
                message_id = None
                inline_msg_id = cb["inline_message_id"]
                msg_text = "Инлайн нәтиже" 
            else:
                chat_id = cb["message"]["chat"]["id"]
                message_id = cb["message"]["message_id"]
                inline_msg_id = None
                msg_text = cb["message"].get("text", "Мәтін жоқ")
            
            if data == "buy_premium":
                answer_callback(cb["id"])
                handle_buy_premium_callback(chat_id, cb["id"])

            elif data.startswith("gender:"):
                gender_val = data.split(":")[1]
                gender_kz = "Ер" if gender_val == "male" else "Әйел"
                
                set_user_gender(user_id, gender_kz)
                log_to_bigquery(user_id, "set_gender", gender_kz, "Профиль жаңартылды")
                
                answer_callback(cb["id"])
                
                success_text = f"Рақмет, сақталды! 👍\n\nЕнді бастайық 🚀\nМаған кез келген өнімнің атын жазыңыз, суретін жіберіңіз немесе жақын маңдағы халал дәмханаларды іздеп көріңіз!"
                keyboard = {"keyboard": [[{"text": "📍 Тұрған орнымды жіберу", "request_location": True}]], "resize_keyboard": True}
                
                edit_message(chat_id, message_id, success_text)
                send_message(chat_id, "Төмендегі батырма арқылы локация жібере аласыз 👇", reply_markup=keyboard)
                    
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
                    edit_message(chat_id, message_id, text, markup)
                else:
                    answer_callback(cb["id"], text="Мәлімет табылмады 😔", show_alert=True)

            elif data == "fb:good":
                answer_callback(cb["id"], text="Пікіріңізге рақмет! ❤️")
                log_to_bigquery(user_id, "feedback", "👍 Пайдалы", "Кері байланыс")
                edit_message(chat_id, message_id, f"{msg_text}\n\n<i>(Пікір: 👍 Пайдалы)</i>", inline_message_id=inline_msg_id)

            elif data == "fb:bad":
                answer_callback(cb["id"])
                reasons_markup = {"inline_keyboard": [[{"text": "📝 Қате ақпарат", "callback_data": "fb:reason:Қате_ақпарат"}],[{"text": "🤖 ЖИ қатесі", "callback_data": "fb:reason:ЖИ_қатесі"}],[{"text": "❌ Басқа", "callback_data": "fb:reason:Басқа"}]]}
                edit_message(chat_id, message_id, f"{msg_text}\n\n👇 <b>Нақты қандай қате кетті? Оны тез арада түзетеміз:</b>", reply_markup=reasons_markup, inline_message_id=inline_msg_id)

            elif data.startswith("fb:reason:"):
                parts = data.split(":")
                reason = parts[2]
                answer_callback(cb["id"], text="Рақмет! Түзетеміз 🛠")
                log_to_bigquery(user_id, "feedback", f"👎 Қате ({reason})", "Кері байланыс")
                edit_message(chat_id, message_id, f"{msg_text}\n\n<i>(Пікір: 👎 {reason})</i>", inline_message_id=inline_msg_id)

            return "OK", 200

        elif "inline_query" in update:
            inline_query_id = update["inline_query"]["id"]
            query_text = update["inline_query"]["query"].strip()
            
            user_info = update["inline_query"]["from"]
            user_id = user_info["id"]
            
            prompt_button = {"text": "🔍 Өнім немесе мекеме атауын жазыңыз...", "start_parameter": "search_help"}
            
            if len(query_text) >= 3:
                has_access, reason = check_access(user_id, user_id == SYMBAT_ID)
                if not has_access:
                    answer_inline_query(inline_query_id,[], button={"text": "⚠️ Лимит бітті! Premium алу үшін басыңыз", "start_parameter": "buy_premium"})
                    return "OK", 200
                
                found_items = search_data(query_text)
                tg_results =[]
                for item in found_items:
                    text_msg, markup = format_detail_message(item)
                    status = item.get("status", "")
                    if "Белсенді" in status or "Рұқсат" in status:
                        thumb_url, icon = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/128/emoji_u2705.png", "✅"
                    elif "Мерзімі" in status or "⚠️" in status:
                        thumb_url, icon = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/128/emoji_u26a0.png", "⚠️"
                    else:
                        thumb_url, icon = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/128/emoji_u1f6ab.png", "🚫"

                    clean_title = str(item['title']).strip('«»"\' ')
                    title_text = f"{icon} {clean_title}"
                    desc_text = f"🏢 {item.get('desc', 'Мекеме')} • 📍 {item.get('address', '')}" if item['type'] == "Мекеме" else f"🏷 Қоспа • 📊 {status}"

                    tg_results.append({
                        "type": "article", "id": str(uuid.uuid4()), "title": title_text, "description": desc_text,
                        "thumbnail_url": thumb_url, "thumbnail_width": 128, "thumbnail_height": 128,
                        "input_message_content": {"message_text": text_msg, "parse_mode": "HTML"},
                        "reply_markup": markup
                    })
                answer_inline_query(inline_query_id, tg_results, button=prompt_button)
                increment_usage(user_id)
            else:
                answer_inline_query(inline_query_id,[], button=prompt_button)

        elif "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            first_name = msg["chat"].get("first_name", "Досым")
            username = msg["chat"].get("username", "жоқ")
            is_symbat = (chat_id == SYMBAT_ID)
            
            if "successful_payment" in msg:
                process_successful_payment(msg)
                return "OK", 200
                
            if "refunded_payment" in msg:
                revoke_premium(chat_id)
                send_message(chat_id, "⚠️ Сіз төлемді қайтарып алдыңыз. Premium статусыңыз өшірілді.")
                return "OK", 200
            
            if "photo" in msg:
                has_access, reason = check_access(chat_id, is_symbat)
                if not has_access:
                    send_message(chat_id, reason, reply_markup=get_premium_keyboard())
                    return "OK", 200
                    
                send_message(chat_id, "📷 Суретті талдап жатырмын, сәл күте тұрыңыз...")
                photo_id = msg["photo"][-1]["file_id"]
                image_bytes = download_photo(photo_id)
                if image_bytes:
                    result_msg, markup = handle_photo(image_bytes, chat_id, username)
                    send_message(chat_id, result_msg, reply_markup=markup)
                    save_chat_history(chat_id, "user", "Мен саған бір сурет жібердім")
                    save_chat_history(chat_id, "model", result_msg)
                    log_to_bigquery(chat_id, "photo_search", "Сурет", "Тексерілді")
                    increment_usage(chat_id)

            elif "location" in msg:
                has_access, reason = check_access(chat_id, is_symbat)
                if not has_access:
                    send_message(chat_id, reason, reply_markup=get_premium_keyboard())
                    return "OK", 200
                    
                lat, lon = msg["location"]["latitude"], msg["location"]["longitude"]
                text, markup = get_nearby_companies(lat, lon, page=1)
                send_message(chat_id, text, reply_markup=markup)
                log_to_bigquery(chat_id, "location_search", f"{lat}, {lon}", "Тізім берілді")
                increment_usage(chat_id)

            elif "text" in msg:
                text = msg["text"]
                save_chat_history(chat_id, "user", text)

                if text == "/start":
                    add_user(chat_id, first_name, username)
                    
                    if is_symbat:
                        welcome_text = f"Сәлем, Ботам! ❤️\n\nБұл сенің сүйікті жігітің жасаған ҚМДБ Халал боты ғой. Маған кез келген өнімнің атын жаз немесе суретін жібер, мен сен үшін бәрін тауып беремін! 😘"
                        keyboard = {"keyboard": [[{"text": "📍 Тұрған орнымды жіберу", "request_location": True}]], "resize_keyboard": True}
                        send_message(chat_id, welcome_text, reply_markup=keyboard)
                        save_chat_history(chat_id, "model", welcome_text)
                        log_to_bigquery(chat_id, "start", "/start", "Сымбат кірді")
                    else:
                        current_gender = get_user_gender(chat_id)
                        
                        if not current_gender:
                            welcome_text = f"Сәлем, {first_name}! 👋\n\nМен — кез келген өнімнің немесе дәмхананың халал екенін тез әрі нақты тексеріп беретін көмекшіңізбін.\n\nЖақынырақ танысу үшін, жынысыңызды таңдаңызшы:"
                            gender_markup = {"inline_keyboard": [[{"text": "🙎‍♂️ Ер азамат", "callback_data": "gender:male"},
                                 {"text": "🙎‍♀️ Нәзік жанды", "callback_data": "gender:female"}]
                            ]}
                            send_message(chat_id, welcome_text, reply_markup=gender_markup)
                            log_to_bigquery(chat_id, "start", "/start", "Жаңа қолданушы (Жыныс сұралды)")
                        else:
                            welcome_text = f"Қайта оралуыңызбен, {first_name}! 👋\n\nМен жұмысқа дайынмын. Тексеретін өнім бар ма немесе тамақтанатын орын іздейміз бе?"
                            keyboard = {"keyboard": [[{"text": "📍 Тұрған орнымды жіберу", "request_location": True}]], "resize_keyboard": True}
                            send_message(chat_id, welcome_text, reply_markup=keyboard)
                            save_chat_history(chat_id, "model", welcome_text)
                            log_to_bigquery(chat_id, "start", "/start", "Ескі қолданушы")
                            
                else:
                    found_items = search_data(text)
                    
                    if found_items:
                        has_access, reason = check_access(chat_id, is_symbat)
                        if not has_access:
                            send_message(chat_id, reason, reply_markup=get_premium_keyboard())
                            return "OK", 200
                            
                        if len(found_items) == 1:
                            reply_text, markup = format_detail_message(found_items[0])
                            send_message(chat_id, reply_text, reply_markup=markup)
                            save_chat_history(chat_id, "model", reply_text)
                            log_to_bigquery(chat_id, "text_search", text, "Табылды (1)")
                            increment_usage(chat_id)
                        else:
                            reply_text = f"🔍 <b>Мен бірнеше нұсқа таптым. Сізге нақты қайсысы керек?</b>\n\n"
                            keyboard =[]
                            for idx, item in enumerate(found_items[:5]):
                                if item['type'] == 'Мекеме':
                                    desc_text = f"📍 {item.get('address', '')}"
                                else:
                                    desc_text = f"🏷 {item.get('desc', '')}"
                                    
                                reply_text += f"<b>{idx+1}. «{item['title']}»</b>\n{desc_text}\n\n"
                                t_code = "c" if item['type'] == "Мекеме" else "i"
                                keyboard.append([{"text": f"{idx+1}. «{item['title']}»", "callback_data": f"itm:{t_code}:{item['id']}"}])
                                
                            send_message(chat_id, reply_text, reply_markup={"inline_keyboard": keyboard})
                            save_chat_history(chat_id, "model", reply_text)
                            log_to_bigquery(chat_id, "text_search", text, "Табылды (Көп)")
                            increment_usage(chat_id)
                    else:
                        wait_msg_id = send_message(chat_id, "⏳ <i>Базадан іздеп жатырмын...</i>")
                        
                        if wait_msg_id:
                            ai_reply = chat_with_ai(chat_id, text, is_symbat, chat_id=chat_id, message_id=wait_msg_id)
                            keys = {"inline_keyboard": [[{"text": "👍 Пайдалы", "callback_data": "fb:good"}, {"text": "👎 Қате", "callback_data": "fb:bad"}]]}
                            edit_message(chat_id, wait_msg_id, ai_reply, reply_markup=keys)
                        else:
                            ai_reply = chat_with_ai(chat_id, text, is_symbat)
                            keys = {"inline_keyboard": [[{"text": "👍 Пайдалы", "callback_data": "fb:good"}, {"text": "👎 Қате", "callback_data": "fb:bad"}]]}
                            send_message(chat_id, ai_reply, reply_markup=keys)
                            
                        save_chat_history(chat_id, "model", ai_reply)
                        log_to_bigquery(chat_id, "ai_chat", text, "Табылмады/AI жауап берді")

    return "OK", 200
