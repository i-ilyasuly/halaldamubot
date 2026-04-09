from google.cloud import firestore, bigquery
from datetime import datetime, timedelta, timezone
from formatters import format_item_dict
import string
import random
import uuid

db = firestore.Client()
bq_client = bigquery.Client()
CACHE = {"companies": [], "ingredients": [], "loaded": False, "loaded_at": None}
CACHE_TTL_SECONDS = 7200  # 2 сағат — reads азайту үшін

# ════════════════════════════════════════════════════════════════
# USER CACHE — Firestore reads азайту үшін (5 минут TTL)
# ════════════════════════════════════════════════════════════════
USER_CACHE = {}       # {user_id: {"data": {...}, "loaded_at": datetime}}
USER_CACHE_TTL = 300  # 5 минут

def _now():
    """Барлық жерде бір timezone: UTC. Бұл функцияны пайдалан."""
    return datetime.now(timezone.utc)

def _get_user_data(user_id):
    """
    Пайдаланушы деректерін кэштен алады.
    Кэш жоқ немесе ескі болса — Firestore-дан оқиды.
    """
    now = _now()
    cached = USER_CACHE.get(str(user_id))
    if cached:
        age = (now - cached["loaded_at"]).total_seconds()
        if age < USER_CACHE_TTL:
            return cached["data"]  # Кэштен ✅

    # Кэш жоқ немесе ескі — Firestore-дан оқимыз
    doc = db.collection("users").document(str(user_id)).get()
    data = doc.to_dict() if doc.exists else {}
    USER_CACHE[str(user_id)] = {"data": data, "loaded_at": now}
    return data

def _invalidate_user_cache(user_id):
    """Кэшті жою — деректер өзгергенде шақырылады."""
    USER_CACHE.pop(str(user_id), None)

def log_to_bigquery(user_id, action, query_text, status,
                    is_premium=None, result_count=None,
                    confidence=None, stars_spent=None, platform=None, gender=None):
    try:
        table_id = f"{bq_client.project}.bot_statistics.usage_logs"
        row = {
            "created_at": _now().isoformat(),
            "user_id": str(user_id),
            "action": action,
            "query": query_text[:200] if query_text else "",
            "status": status,
        }
        if is_premium is not None:
            row["is_premium"] = is_premium
        if result_count is not None:
            row["result_count"] = result_count
        if confidence is not None:
            row["confidence"] = confidence
        if stars_spent is not None:
            row["stars_spent"] = stars_spent
        if platform is not None:
            row["platform"] = platform
        if gender is not None:
            row["gender"] = gender

        errors = bq_client.insert_rows_json(table_id, [row])
        if errors:
            print(f"BigQuery қатесі: {errors}")
    except Exception as e:
        print(f"BigQuery жүйелік қатесі: {e}")

def load_cache():
    """Кэш жүктеу — CACHE_TTL_SECONDS-тан ескі болса автоматты жаңартады"""
    now = _now()
    cache_expired = (
        not CACHE["loaded"] or
        CACHE["loaded_at"] is None or
        (now - CACHE["loaded_at"]).total_seconds() > CACHE_TTL_SECONDS
    )
    if not cache_expired:
        return  # Кэш жаңа ✅

    comps = db.collection("companies").stream()
    CACHE["companies"] = [c.to_dict() for c in comps]
    ings = db.collection("ingredients").stream()
    CACHE["ingredients"] = [i.to_dict() for i in ings]
    CACHE["loaded"] = True
    CACHE["loaded_at"] = now

def clear_cache():
    global CACHE
    CACHE["companies"] = []
    CACHE["ingredients"] = []
    CACHE["loaded"] = False
    CACHE["loaded_at"] = None

def get_chat_history(user_id):
    doc = db.collection("chat_history").document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict().get("history", [])
    return []

def save_chat_history(user_id, role, text):
    history = get_chat_history(user_id)
    history.append({"role": role, "parts": [text]})
    if len(history) > 20:
        history = history[-20:]
    db.collection("chat_history").document(str(user_id)).set({"history": history}, merge=True)

def add_user(user_id, first_name, username):
    db.collection("users").document(str(user_id)).set({"first_name": first_name, "username": username}, merge=True)

def get_item_by_id(item_type_code, item_id):
    load_cache()
    if item_type_code == 'c':
        for c in CACHE["companies"]:
            if str(c.get("id")) == item_id:
                return format_item_dict(c, "Мекеме")
    elif item_type_code == 'i':
        for i in CACHE["ingredients"]:
            if str(i.get("id")) == item_id:
                return format_item_dict(i, "Қоспа")
    return None

def check_access(user_id, is_symbat):
    if is_symbat:
        return True, "VIP"

    # Бот барлығына тегін — әр пайдаланушы "premium" тиер алады.
    # Жалғыз шектеу: спам қорғаныс үшін күніне 100 сұрау.
    data = _get_user_data(user_id)  # Firestore емес, кэштен! ✅
    today_str = _now().strftime("%Y-%m-%d")
    last_date = data.get("last_search_date")
    usage = data.get("daily_searches", 0)

    if last_date != today_str:
        usage = 0

    if usage >= 100:
        return False, "SPAM_LIMIT"

    return True, "premium"

def increment_usage(user_id):
    doc_ref = db.collection("users").document(str(user_id))
    doc = doc_ref.get()
    today_str = _now().strftime("%Y-%m-%d")

    if doc.exists:
        data = doc.to_dict()
        if data.get("last_search_date") == today_str:
            new_usage = data.get("daily_searches", 0) + 1
        else:
            new_usage = 1
        doc_ref.set({"daily_searches": new_usage, "last_search_date": today_str}, merge=True)
    else:
        doc_ref.set({
            "first_name": "Inline User",
            "username": "hidden",
            "daily_searches": 1,
            "last_search_date": today_str
        }, merge=True)
    _invalidate_user_cache(user_id)  # Деректер өзгерді — кэшті тазала ✅

def grant_premium(user_id, days=30):
    """
    Premium мерзімін қосады.
    Белсенді тариф болса — соның үстіне қосады (жазып тастамайды).
    Мысалы: 20 күн қалған + 30 күн = 50 күн болады.
    """
    doc_ref = db.collection("users").document(str(user_id))
    doc = doc_ref.get()

    base = _now()
    if doc.exists:
        prem_until = doc.to_dict().get("premium_until")
        if prem_until:
            if isinstance(prem_until, datetime) and prem_until.tzinfo is None:
                prem_until = prem_until.replace(tzinfo=timezone.utc)
            # Белсенді тариф болса — соның аяғынан қосамыз
            if isinstance(prem_until, datetime) and prem_until > base:
                base = prem_until

    new_date = base + timedelta(days=days)
    doc_ref.set({"premium_until": new_date}, merge=True)
    _invalidate_user_cache(user_id)  # Деректер өзгерді — кэшті тазала ✅

def revoke_premium(user_id):
    db.collection("users").document(str(user_id)).set({"premium_until": None}, merge=True)

def record_payment(user_id, username, amount, payload, charge_id):
    db.collection("payments_history").document(str(charge_id)).set({
        "user_id": str(user_id),
        "username": username,
        "amount_stars": amount,
        "payload": payload,
        "telegram_charge_id": charge_id,
        "timestamp": firestore.SERVER_TIMESTAMP
    }, merge=True)

def get_user_gender(user_id):
    doc = db.collection("users").document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict().get("gender")
    return None

def set_user_gender(user_id, gender):
    db.collection("users").document(str(user_id)).set({"gender": gender}, merge=True)

def get_user_language(user_id):
    """Қолданушының тілін алу. Әдепкі: 'kz'"""
    data = _get_user_data(user_id)  # Firestore емес, кэштен! ✅
    return data.get("language", "kz")

def set_user_language(user_id, lang):
    """Қолданушының тілін сақтау. lang: 'kz' немесе 'ru'"""
    db.collection("users").document(str(user_id)).set({"language": lang}, merge=True)
    _invalidate_user_cache(user_id)  # Деректер өзгерді — кэшті тазала ✅

def create_gift_code(buyer_id, buyer_name, recipient_username=None, tariff_id=None):
    """Сыйлық кодын генерациялап, draft_gifts базасына сақтайды"""
    code = "gift_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    data = {
        "buyer_id": str(buyer_id),
        "buyer_name": buyer_name,
        "status": "active",
        "tariff_id": tariff_id or "premium_30_days",
        "created_at": firestore.SERVER_TIMESTAMP
    }
    if recipient_username:
        clean = recipient_username.lstrip("@").lower()
        data["recipient_username"] = clean
        # pending_gifts колекциясына да жазамыз — алушы /start жазғанда табу үшін
        db.collection("pending_gifts").document(clean).set({
            "gift_code": code,
            "buyer_name": buyer_name,
            "created_at": firestore.SERVER_TIMESTAMP
        })
    db.collection("draft_gifts").document(code).set(data)
    return code

def get_pending_gift_for_username(username):
    """Пайдаланушының күтіп тұрған сыйлығын табу (алғаш /start жазғанда)"""
    clean = username.lstrip("@").lower()
    doc = db.collection("pending_gifts").document(clean).get()
    if doc.exists:
        data = doc.to_dict()
        return data.get("gift_code"), data.get("buyer_name")
    return None, None

def delete_pending_gift(username):
    """Сыйлық қабылданған соң pending_gifts-тен өшіру"""
    clean = username.lstrip("@").lower()
    db.collection("pending_gifts").document(clean).delete()

def redeem_gift_code(code, user_id):
    """Сыйлық кодын қолдану (Premium беру)"""
    doc_ref = db.collection("draft_gifts").document(code)
    doc = doc_ref.get()

    if doc.exists:
        data = doc.to_dict()
        if data.get("status") == "active":
            # Сыйлықты жасаған адам өзі ала алмайды
            if str(data.get("buyer_id", "")) == str(user_id):
                return False, None, 0
            doc_ref.set({
                "status": "used",
                "used_by": str(user_id),
                "used_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            # Тарифке сәйкес күн санын аламыз
            from tariffs import get_tariff_by_id
            tariff_id = data.get("tariff_id", "premium_30_days")
            t = get_tariff_by_id(tariff_id) or {"days": 30}
            grant_premium(user_id, days=t["days"])
            return True, data.get("buyer_name", "Жасырын адам"), t["days"]

    return False, None, 0

def save_search_session(user_id, items):
    """Іздеу нәтижелерін уақытша сақтау (пагинация үшін)"""
    session_id = uuid.uuid4().hex[:12]
    data = [{"t": i.get('type', ''), "id": i['id'], "c": i.get('confidence', 'exact')} for i in items]
    db.collection("search_sessions").document(session_id).set({
        "user_id": str(user_id),
        "items": data,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    return session_id

def get_search_session(session_id):
    """Сақталған іздеу нәтижелерін алу"""
    doc = db.collection("search_sessions").document(session_id).get()
    if doc.exists:
        return doc.to_dict().get("items", [])
    return []

# ════════════════════════════════════════════════════════════════
# USER STATE — Firestore-да сақтау (gift_state үшін)
# ════════════════════════════════════════════════════════════════

def set_user_state(user_id, data: dict):
    """Қолданушы күйін Firestore-ға жазу"""
    db.collection("user_states").document(str(user_id)).set({
        **data,
        "updated_at": firestore.SERVER_TIMESTAMP
    })

def get_user_state(user_id):
    """Қолданушы күйін Firestore-дан оқу"""
    doc = db.collection("user_states").document(str(user_id)).get()
    if doc.exists:
        return doc.to_dict()
    return None

def get_user_state_field(user_id, field: str):
    """Күйдің бір өрісін алу"""
    state = get_user_state(user_id)
    if state:
        return state.get(field)
    return None

def clear_user_state(user_id):
    """Қолданушы күйін Firestore-дан өшіру"""
    db.collection("user_states").document(str(user_id)).delete()
