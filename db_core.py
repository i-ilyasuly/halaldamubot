from google.cloud import firestore, bigquery
from datetime import datetime, timedelta, timezone
from formatters import format_item_dict

db = firestore.Client()
bq_client = bigquery.Client()
CACHE = {"companies": [], "ingredients":[], "loaded": False}

def log_to_bigquery(user_id, action, query_text, status):
    try:
        table_id = f"{bq_client.project}.bot_statistics.usage_logs"
        rows_to_insert =[{
            "created_at": datetime.utcnow().isoformat(),
            "user_id": str(user_id),
            "action": action,
            "query": query_text[:200],
            "status": status
        }]
        errors = bq_client.insert_rows_json(table_id, rows_to_insert)
        if errors: print(f"BigQuery қатесі: {errors}")
    except Exception as e:
        print(f"BigQuery жүйелік қатесі: {e}")

def load_cache():
    """Базаны бір-ақ рет оқып, жадыға сақтайды"""
    if not CACHE["loaded"]:
        comps = db.collection("companies").stream()
        CACHE["companies"] = [c.to_dict() for c in comps]
        ings = db.collection("ingredients").stream()
        CACHE["ingredients"] =[i.to_dict() for i in ings]
        CACHE["loaded"] = True

# ================= ЖАҢА ФУНКЦИЯ: ЖАДЫНЫ ТАЗАЛАУ =================
def clear_cache():
    """Түнгі жаңартудан кейін ескі мәліметтерді өшіреді"""
    global CACHE
    CACHE["companies"] = []
    CACHE["ingredients"] = []
    CACHE["loaded"] = False
# ================================================================

def get_chat_history(user_id):
    doc = db.collection("chat_history").document(str(user_id)).get()
    if doc.exists: return doc.to_dict().get("history", [])
    return[]

def save_chat_history(user_id, role, text):
    history = get_chat_history(user_id)
    history.append({"role": role, "parts": [text]})
    if len(history) > 20: history = history[-20:]
    db.collection("chat_history").document(str(user_id)).set({"history": history}, merge=True)

def add_user(user_id, first_name, username):
    db.collection("users").document(str(user_id)).set({"first_name": first_name, "username": username}, merge=True)

def get_item_by_id(item_type_code, item_id):
    load_cache()
    if item_type_code == 'c':
        for c in CACHE["companies"]:
            if str(c.get("id")) == item_id: return format_item_dict(c, "Мекеме")
    elif item_type_code == 'i':
        for i in CACHE["ingredients"]:
            if str(i.get("id")) == item_id: return format_item_dict(i, "Қоспа")
    return None

def check_access(user_id, is_symbat):
    if is_symbat:
        return True, "VIP"
        
    doc_ref = db.collection("users").document(str(user_id))
    doc = doc_ref.get()
    if not doc.exists: return True, "free"
    
    data = doc.to_dict()
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    prem_until = data.get("premium_until")
    if prem_until:
        if isinstance(prem_until, datetime):
            if prem_until > datetime.now(timezone.utc):
                if data.get("last_search_date") == today_str and data.get("daily_searches", 0) >= 150:
                    return False, "Спам қорғанысы: Сіз күндік 150 сұрау шегіне жеттіңіз."
                return True, "premium"
                
    last_date = data.get("last_search_date")
    usage = data.get("daily_searches", 0)
    
    if last_date != today_str:
        usage = 0 
        
    if usage >= 5:
        return False, "Кешіріңіз, сіздің күндік тегін лимитіңіз (5/5) бітті. Шексіз іздеу үшін Premium жазылымын алыңыз!"
        
    return True, "free"

def increment_usage(user_id):
    doc_ref = db.collection("users").document(str(user_id))
    doc = doc_ref.get()
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    if doc.exists:
        data = doc.to_dict()
        if data.get("last_search_date") == today_str:
            new_usage = data.get("daily_searches", 0) + 1
        else:
            new_usage = 1
        doc_ref.set({"daily_searches": new_usage, "last_search_date": today_str}, merge=True)
    else:
        # ЖАҢА ҚОСЫЛҒАН БЛОК: Базада жоқ Инлайн адамдарды автоматты тіркеу
        doc_ref.set({
            "first_name": "Inline User",
            "username": "hidden",
            "daily_searches": 1,
            "last_search_date": today_str
        }, merge=True)

def grant_premium(user_id, days=30):
    doc_ref = db.collection("users").document(str(user_id))
    new_date = datetime.now(timezone.utc) + timedelta(days=days)
    doc_ref.set({"premium_until": new_date}, merge=True)

def revoke_premium(user_id):
    db.collection("users").document(str(user_id)).set({"premium_until": None}, merge=True)

def record_payment(user_id, username, amount, payload, charge_id):
    db.collection("payments_history").add({
        "user_id": str(user_id),
        "username": username,
        "amount_stars": amount,
        "payload": payload,
        "telegram_charge_id": charge_id,
        "timestamp": firestore.SERVER_TIMESTAMP
    })
