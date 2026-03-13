import uuid
from bot_sender import answer_inline_query
from db_core import check_access, increment_usage
from search_logic import search_data
from formatters import format_detail_message

SYMBAT_ID = 1042456426

def handle_inline(inline_query):
    inline_query_id = inline_query["id"]
    query_text = inline_query["query"].strip()
    
    user_info = inline_query["from"]
    user_id = user_info["id"]
    
    prompt_button = {"text": "🔍 Өнім немесе мекеме атауын жазыңыз...", "start_parameter": "search_help"}
    
    if len(query_text) >= 3:
        has_access, tier = check_access(user_id, user_id == SYMBAT_ID)
        if not has_access:
            answer_inline_query(inline_query_id,[], button={"text": "⚠️ Лимит бітті! Premium алу үшін басыңыз", "start_parameter": "buy_premium"})
            return
        
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
