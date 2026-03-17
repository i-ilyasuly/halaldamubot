import uuid
from bot_sender import answer_inline_query
from db_core import check_access, increment_usage, log_to_bigquery, get_user_language
from translations import t
from search_logic import search_data
from formatters import format_detail_message

SYMBAT_ID = 1042456426

def handle_inline(inline_query):
    inline_query_id = inline_query["id"]
    query_text = inline_query["query"].strip()
    
    user_info = inline_query["from"]
    user_id = user_info["id"]
    first_name = user_info.get("first_name", "Досым")
    lang = get_user_language(user_id)
    
    # --- ЖАҢА: СЫЙЛЫҚ ҚОРАБЫН ИНЛАЙН ЖІБЕРУ ---
    if query_text.startswith("giftbox_"):
        gift_code = query_text.replace("giftbox_", "")
        bot_username = "alladalbot"

        # Firestore-дан тариф атауын аламыз
        gift_label_kz = "30 күн"
        gift_label_ru = "30 дней"
        try:
            from db_core import db as _db
            from tariffs import get_tariff_by_id as _get_tariff
            _gdoc = _db.collection("draft_gifts").document(gift_code).get()
            if _gdoc.exists:
                _tariff_id = _gdoc.to_dict().get("tariff_id", "premium_30_days")
                _tariff = _get_tariff(_tariff_id)
                if _tariff:
                    gift_label_kz = _tariff["label"]
                    gift_label_ru = _tariff["label"]
        except Exception:
            pass

        gift_result = [{
            "type": "article",
            "id": str(uuid.uuid4()),
            "title": f"🎁 Premium Сыйлық ({gift_label_kz})",
            "description": "Осыны басып, досыңыздың чатына сыйлықты жіберіңіз!",
            "thumbnail_url": "https://em-content.zobj.net/source/apple/354/wrapped-gift_1f381.png",
            "thumbnail_width": 128,
            "thumbnail_height": 128,
            "input_message_content": {
                "message_text": (
                    f"🎁 <b>{first_name}</b> сізге / вам "
                    f"<b>{gift_label_kz} / {gift_label_ru} Premium</b> сыйлады / подарил!\n\n"
                    f"🇰🇿 Сыйлықты ашу үшін төмендегі батырманы басыңыз 👇\n"
                    f"🇷🇺 Нажмите кнопку ниже, чтобы открыть подарок 👇"
                ),
                "parse_mode": "HTML"
            },
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": t("btn_open_gift", lang), "url": f"https://t.me/{bot_username}?start={gift_code}", "style": "success"}
                ]]
            }
        }]

        answer_inline_query(inline_query_id, gift_result)
        return

    prompt_button = {"text": t("btn_inline_prompt", lang), "start_parameter": "search_help"}
    
    if len(query_text) >= 3:
        has_access, tier = check_access(user_id, user_id == SYMBAT_ID)
        if not has_access:
            answer_inline_query(inline_query_id,[], button={"text": t("btn_inline_limit", lang), "start_parameter": "buy_premium"})
            return
        
        found_items = search_data(query_text)
        tg_results =[]
        for item in found_items:
            text_msg, markup = format_detail_message(item, lang=lang)
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
        log_to_bigquery(user_id, "inline_search", query_text,
                        f"Табылды ({len(tg_results)})", result_count=len(tg_results))
    else:
        answer_inline_query(inline_query_id,[], button=prompt_button)
