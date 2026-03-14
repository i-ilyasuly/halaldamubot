from bot_sender import send_message, send_invoice, answer_pre_checkout_query
from db_core import grant_premium, record_payment, log_to_bigquery, create_gift_code

def get_premium_keyboard():
    return {
        "inline_keyboard": [[{"text": "⭐️ Premium алу (100 ⭐️)", "callback_data": "buy_premium", "style": "primary"}]]
    }

def handle_buy_premium_callback(chat_id, callback_id):
    send_invoice(chat_id)

def process_pre_checkout(update):
    query_id = update["pre_checkout_query"]["id"]
    answer_pre_checkout_query(query_id, ok=True)

def process_successful_payment(message):
    chat_id = message["chat"]["id"]
    username = message["chat"].get("first_name", "Жақсы адам") 
    payment_info = message["successful_payment"]
    
    amount = payment_info["total_amount"]
    payload = payment_info["invoice_payload"]
    charge_id = payment_info["telegram_payment_charge_id"]
    
    record_payment(chat_id, username, amount, payload, charge_id)
    log_to_bigquery(chat_id, "payment", f"{amount} Stars", "Сәтті төлем")
    
    # 1. ЕГЕР ӨЗІНЕ АЛСА:
    if payload == "premium_30_days":
        grant_premium(chat_id, days=30)
        success_text = (
            "🎉 <b>Төлем сәтті өтті! Құттықтаймыз!</b>\n\n"
            "Сіз енді <b>Premium</b> қолданушысыз 👑\n"
            "Алдағы 30 күн бойы барлық шектеулер алынып тасталды. Жобамызды қолдағаныңыз үшін үлкен рақмет! ❤️"
        )
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")
        
    # 2. ЕГЕР СЫЙЛЫҚҚА АЛСА:
    elif payload == "gift_premium_30_days":
        code = create_gift_code(chat_id, username)
        
        # ЕСКЕРТУ: Төмендегі "momyn_bot" орнына өз ботыңыздың нақты @username-ін жазыңыз (егер тесттік бот болса)
        bot_username = "alladalbot" 
        gift_link = f"https://t.me/{bot_username}?start={code}"
        
        success_text = (
            "🎁 <b>Сыйлық сәтті сатып алынды!</b>\n\n"
            "Төмендегі сілтемені көшіріп, сыйлағыңыз келген адамға (WhatsApp, Telegram арқылы) жіберіңіз:\n\n"
            f"👉 {gift_link}\n\n"
            "<i>Ескерту: Бұл сілтемені тек 1 адам ғана қолдана алады! Ол сілтемемен кірген бойда оған 30 күн Premium автоматты түрде қосылады.</i>"
        )
        send_message(chat_id, success_text, message_effect_id="5046509860389126442")
