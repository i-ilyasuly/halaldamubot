# ════════════════════════════════════════════════════════════════════════════
# vision_collector.py — Halal Damu Bot | Visual Training Data Pipeline
# ════════════════════════════════════════════════════════════════════════════
#
# АРХИТЕКТУРА v2 — 5 қабатты matching
#   1. Extraction  — Gemini (тек 1 рет)
#   2. Normalization — код, детерминистік
#   3. Exact match — Firestore product_key
#   4. Fuzzy match — thefuzz (Gemini жоқ)
#   5. LLM Router  — Gemini (тек жаңа өнімде)
#
# Соңғы жаңарту: 2026-03-29
# ════════════════════════════════════════════════════════════════════════════

import uuid
import json
import re
import hashlib
import time
from datetime import datetime, timezone

import google.generativeai as genai
from google.cloud import storage, firestore, vision
from thefuzz import fuzz

from config import GEMINI_API_KEY, BUCKET_NAME, ADMIN_TELEGRAM_ID
from bot_sender import send_message, send_photo_bytes
from db_core import log_to_bigquery

genai.configure(api_key=GEMINI_API_KEY)

storage_client = storage.Client()
db = firestore.Client()

ADMIN_IDS = [ADMIN_TELEGRAM_ID]

# ════════════════════════════════════════════════════════════════════════════
# NORMALIZATION — детерминистік, AI жоқ
# ════════════════════════════════════════════════════════════════════════════

# Brand нормализациясы: 'й' → 'i' (АЙС = AIS)
_CYR_TO_LAT_BRAND = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo',
    'ж':'zh','з':'z','и':'i','й':'i',  # 'й' → 'i' (АЙС → ais = AIS)
    'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch',
    'ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    'ә':'a','і':'i','ң':'ng','ғ':'g','ү':'u','ұ':'u','қ':'k','ө':'o','һ':'h',
}

# Жалпы транслитерация (flavor, product_type үшін): 'й' → 'y'
_CYR_TO_LAT = {**_CYR_TO_LAT_BRAND, 'й': 'y'}


def _cyrillic_to_latin(s, brand_mode=False):
    """Кирилл символдарды латынға аударады."""
    table = _CYR_TO_LAT_BRAND if brand_mode else _CYR_TO_LAT
    result = []
    for ch in s:
        lo = ch.lower()
        if lo in table:
            lat = table[lo]
            result.append(lat.upper() if ch.isupper() and lat else lat)
        else:
            result.append(ch)
    return ''.join(result)


def _norm_field(s, brand_mode=False):
    """
    Өрісті нормализациялайды — детерминистік, AI жоқ.

    Өңдеу реті:
    1. None/бос → "" (crash жоқ)
    2. Дроб символдар: ½ → 0.5
    3. Мыңдық үтір: 1,200 → 1200
    4. Ондық үтір: 1,2 → 1.2
    5. Бірліктер: мл→ml, кг→kg, г→g, л→l
    6. Артық символдар: x1.2 → 1.2
    7. Кирилл → латын
    8. Тек a-z0-9.% қалдырады
    """
    if not s or str(s).lower().strip() in ('none', 'null', ''):
        return ""
    s = str(s).strip()

    # 1. Дроб символдар
    s = s.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')

    s = s.lower()

    # 2. Мыңдық үтір алдымен: "1,200г" → "1200г"
    s = re.sub(r'(\d)[,،](\d{3})(?=\D|$)', r'\1\2', s)

    # 3. Ондық үтір → нүкте: "1,2" → "1.2"
    s = re.sub(r'(\d)[,،](\d)', r'\1.\2', s)

    # 4. Бірліктер (кг алдымен, г соңында — ретті сақта!)
    s = re.sub(r'\s*кг\b', 'kg', s)
    s = re.sub(r'\s*мл\b', 'ml', s)
    s = re.sub(r'\s*гр\b', 'g', s)
    s = re.sub(r'(?<=[0-9])\s*г\b', 'g', s)
    s = re.sub(r'\s*л\b', 'l', s)

    # 5. Артық символдар алдында: "x1.2%" → "1.2%", "№5" → "5"
    s = re.sub(r'^[x×#№\s]+', '', s)

    # 6. Кирилл → латын
    s = _cyrillic_to_latin(s, brand_mode=brand_mode)

    # 7. Тек a-z0-9.%
    s = re.sub(r'[^a-z0-9.%]', '', s)
    return s


def build_product_key(brand, product_type, flavor, volume):
    """
    Детерминистік product_key жасайды.
    Бір өнімнің кез-келген суреті бірдей key береді.

    Мысал: "айс"/"AIS"/"АЙС" → бәрі "ais|..."
    brand_mode=True: 'й' → 'i' (АЙС = AIS)
    """
    parts = [
        _norm_field(brand, brand_mode=True),   # АЙС = AIS = ais
        _norm_field(product_type),
        _norm_field(flavor),
        _norm_field(volume),
    ]
    return "|".join(p for p in parts if p)


def _make_folder_id(product_key):
    """
    product_key-ден папка ID жасайды.
    [:20] қысқарту жоқ — collision болмайды.
    Ұзын болса md5 hash қосамыз.
    """
    fid = product_key.replace("|", "__").replace(" ", "-").replace("/", "_")
    if len(fid) > 80:
        suffix = hashlib.md5(product_key.encode()).hexdigest()[:8]
        fid = fid[:70] + "__" + suffix
    return fid


# ════════════════════════════════════════════════════════════════════════════
# FIRESTORE LOOKUP
# ════════════════════════════════════════════════════════════════════════════

def get_folder_by_exact_key(product_key):
    """
    3-қабат: product_key бойынша дәлме-дәл іздеу.
    Табылса — descriptor dict қайтарады, болмаса None.
    """
    try:
        docs = db.collection("folder_descriptors") \
            .where("product_key", "==", product_key) \
            .limit(1) \
            .stream()
        results = list(docs)
        return results[0].to_dict() if results else None
    except Exception as e:
        print(f"[vision] get_folder_by_exact_key қате: {e}")
        return None


def get_folder_descriptors(brand_lower):
    """
    4-қабат үшін: бренд бойынша барлық папкаларды алу.
    brand_lower — нормализацияланған бренд атауы.
    """
    try:
        docs = db.collection("folder_descriptors") \
            .where("brand_lower", "==", brand_lower) \
            .limit(30) \
            .stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        print(f"[vision] get_folder_descriptors қате: {e}")
        return []


def add_product_key_variant(folder_id, new_variant):
    """
    Fuzzy match табылғанда жаңа variant-ты сақтайды.
    Келесі жолы exact match тауып алады.
    """
    try:
        db.collection("folder_descriptors").document(folder_id).update({
            "product_key_variants": firestore.ArrayUnion([new_variant])
        })
    except Exception as e:
        print(f"[vision] add_product_key_variant қате: {e}")


def fuzzy_find_folder(product_key, descriptors, threshold=85):
    """
    4-қабат: thefuzz арқылы fuzzy match.
    product_key_variants тізімінен ең жақынын іздейді.
    threshold=85 — тым жоғары да, тым төмен да емес.
    """
    best_score = 0
    best_desc = None

    for desc in descriptors:
        # Барлық variant-тарды тексеру
        variants = desc.get("product_key_variants", [])
        main_key = desc.get("product_key", "")
        if main_key:
            variants = [main_key] + variants

        for variant in variants:
            score = fuzz.ratio(product_key, variant)
            if score > best_score:
                best_score = score
                best_desc = desc

    if best_score >= threshold:
        return best_desc, best_score
    return None, 0


# ════════════════════════════════════════════════════════════════════════════
# PROCESS B — EXTRACTION (Gemini, тек 1 рет)
# ════════════════════════════════════════════════════════════════════════════

DEEP_ANALYSIS_PROMPT = """Суреттегі өнімді мұқият талда және ТЕК JSON форматында қайтар.

{
  "brand": "айс",
  "product_line": "Сүт өнімдері",
  "product_type": "Айран",
  "flavor_variant": "Ayran turkish",
  "volume_weight": "1.2%",
  "all_text_on_package": ["айс", "АЙРАН", "Ayran turkish", "1.2%"],
  "visual_features": ["көк-ақ түс", "тұтқасы бар бутылка"],
  "confidence": 0.94
}

═══════════════════════════════════════
БРЕНД АТАУЫ ЖӘНЕ FLAVOR_VARIANT — ӨТЕ МАҢЫЗДЫ ЕРЕЖЕ
═══════════════════════════════════════
Бренд атауы мен flavor_variant-ті қаптамадан ДӘЛМЕ-ДӘЛ КӨШІр.

ӘРІП РЕГИСТРІ (өлшем мен ФОРМА — екі бөлек нәрсе!):
- Қаптамадағы ФИЗИКАлық ШРИФТ ӨЛШЕМІ емес, ЖАЗЫЛУ ФОРМАСЫН қара
- "айс" деп кіші әріппен жазылса → "айс" жаз (үлкен болып көрінсе де)
- "АЙС" деп бас әріппен жазылса → "АЙС" жаз (кішкентай болып көрінсе де)
- Яғни: ӨЛШЕМГЕ қарама, ФОРМА ҒА қара

ЖАЗУ ЖҮЙЕСІ:
- Кириллмен жазылса → кириллмен жаз: "айс", "АЙС", "Простоквашино"
- Латынмен жазылса → латынмен жаз: "AIS", "Snickers", "Lays"
- АУДАРМАСЫН ЖАЗБА: қаптамада "айс" тұрса "AIS" деп жазба!
- Екі тілде жазылса → ірірек немесе алдыңғы планда тұрғанын ал

FLAVOR_VARIANT ЕРЕЖЕСІ:
- қаптамадан ДӘЛМЕ-ДӘЛ КӨШІр
- "Ayran turkish" деп жазылса → "Ayran turkish" жаз
- "Түрікше тұзды" деп жазылса → "Түрікше тұзды" жаз
- АУДАРМАСЫН ЖАЗБА: "turkish" → "Түрікше" деп өзгертпе!

═══════════════════════════════════════
ЖАЛПЫ ЕРЕЖЕЛЕР
═══════════════════════════════════════
- Анықтай алмасаң — null жаз
- Болжама жасама
- ТЕК JSON, басқа ештеңе жазба"""


def analyze_image_deeply(image_bytes):
    """Суреттен барлық ақпаратты алады. Gemini тек осы жерде шақырылады."""
    model = genai.GenerativeModel('gemini-2.5-flash')
    image_parts = [{"mime_type": "image/jpeg", "data": image_bytes}]
    try:
        response = model.generate_content(
            [DEEP_ANALYSIS_PROMPT, image_parts[0]],
            request_options={"timeout": 40}
        )
        raw = re.sub(r'```json\s*', '', response.text.strip())
        raw = re.sub(r'```\s*', '', raw).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[vision] analyze_image_deeply қате: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════
# FOLDER MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════

def create_folder_descriptor(analysis, product_key):
    """
    Жаңа папка + descriptor жасайды.
    product_key міндетті түрде беріледі — [:20] collision жоқ.
    """
    try:
        brand = analysis.get("brand") or "Unknown"
        product_type = analysis.get("product_type") or "Unknown"
        flavor = analysis.get("flavor_variant") or ""
        volume = analysis.get("volume_weight") or ""

        folder_id = _make_folder_id(product_key)
        brand_lower = _norm_field(brand)

        descriptor = {
            "folder_id": folder_id,
            "product_key": product_key,
            "product_key_variants": [product_key],

            "brand": brand,
            "brand_lower": brand_lower,
            "product_line": analysis.get("product_line") or "",
            "product_type": product_type,
            "flavor_variant": flavor,
            "volume_weight": volume,

            "visual_keywords": analysis.get("visual_features") or [],
            "text_keywords": analysis.get("all_text_on_package") or [],
            "negative_keywords": [],
            "enrichment_log": [],

            "company_id": None,
            "auto_created": True,
            "image_count": 0,
            "verified_count": 0,
            "best_image_url": None,
            "best_image_score": 0,
            "search_count": 0,
            "created_at": datetime.now(timezone.utc)
        }

        db.collection("folder_descriptors").document(folder_id).set(descriptor)

        try:
            log_to_bigquery(
                user_id="system",
                action="vision_folder_created",
                query_text=folder_id,
                status="created",
                platform=brand
            )
        except Exception:
            pass

        print(f"[vision] Жаңа папка: {folder_id}")
        return folder_id

    except Exception as e:
        print(f"[vision] create_folder_descriptor қате: {e}")
        return "unknown"


# ════════════════════════════════════════════════════════════════════════════
# LLM ROUTER — тек жаңа өнімде (5-қабат)
# ════════════════════════════════════════════════════════════════════════════

def _firestore_safe(obj):
    """DatetimeWithNanoseconds → ISO string."""
    if isinstance(obj, dict):
        return {k: _firestore_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_firestore_safe(i) for i in obj]
    try:
        return obj.isoformat()
    except AttributeError:
        return obj


def route_to_folder(analysis, descriptors):
    """
    5-қабат: LLM Router.
    Тек exact/fuzzy таппағанда шақырылады.
    """
    if not descriptors:
        return {"folder_id": "new_product", "confidence": 1.0, "reason": "Папка жоқ"}

    model = genai.GenerativeModel('gemini-2.5-flash')
    descriptors_text = json.dumps(_firestore_safe(descriptors), ensure_ascii=False, indent=2)
    analysis_text = json.dumps(_firestore_safe(analysis), ensure_ascii=False, indent=2)

    prompt = f"""Сен суретті дұрыс папкаға бағыттайтын маршрутизаторсың.

СУРЕТ ТАЛДАУЫ:
{analysis_text}

ҚОЛДА БАР ПАПКАЛАР:
{descriptors_text}

СӘЙКЕСТІК ЕРЕЖЕЛЕРІ:
Папкаға жатқызу үшін БАРЛЫҒЫ сәйкес болуы КЕРЕК:
  ✓ brand, product_type, flavor_variant, volume_weight
- 300г ≠ 900мл → БӨЛЕК папка
- 1.2% ≠ 2.5% → БӨЛЕК папка
- Сенімділік < 0.75 → folder_id: "unknown"
- Сәйкес жоқ → folder_id: "new_product"

ТЕК JSON:
{{"folder_id": "...", "confidence": 0.0, "reason": "..."}}"""

    try:
        response = model.generate_content(prompt, request_options={"timeout": 30})
        raw = re.sub(r'```json\s*|```\s*', '', response.text).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[vision] route_to_folder қате: {e}")
        return {"folder_id": "unknown", "confidence": 0.0, "reason": f"Қате: {e}"}


# ════════════════════════════════════════════════════════════════════════════
# GCS UPLOAD
# ════════════════════════════════════════════════════════════════════════════

def _image_md5(image_bytes):
    return hashlib.md5(image_bytes).hexdigest()


def _upload_bytes_to_gcs_verified(image_bytes, gcs_path, retries=3):
    """GCS-ке жазу + verify (3 retry)."""
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(gcs_path)
    last_error = None
    for attempt in range(retries):
        try:
            blob.upload_from_string(image_bytes, content_type="image/jpeg")
            blob.reload()
            return f"gs://{BUCKET_NAME}/{gcs_path}"
        except Exception as e:
            last_error = e
            print(f"[GCS] attempt {attempt+1} failed: {e}")
            time.sleep(1)
    raise last_error


def save_to_folder(image_bytes, user_id, analysis, routing):
    """
    GCS path: products/{folder_id}/raw/{image_id}.jpg
    folder_id-пен бірыңғай — inconsistency жоқ.
    """
    try:
        image_id = uuid.uuid4().hex
        md5 = _image_md5(image_bytes)

        existing = db.collection("product_images") \
            .where("md5_hash", "==", md5).limit(1).stream()
        is_duplicate = bool(list(existing))

        folder_id = routing["folder_id"]

        # GCS path — folder_id арқылы (brand/product_type емес)
        gcs_path = f"products/{folder_id}/raw/{image_id}.jpg"
        gcs_uri = _upload_bytes_to_gcs_verified(image_bytes, gcs_path)

        db.collection("product_images").document(image_id).set({
            "image_id": image_id,
            "gcs_path": gcs_uri,
            "md5_hash": md5,
            "is_duplicate": is_duplicate,

            "brand": analysis.get("brand"),
            "product_line": analysis.get("product_line"),
            "product_type": analysis.get("product_type"),
            "flavor_variant": analysis.get("flavor_variant"),
            "volume_weight": analysis.get("volume_weight"),
            "all_text": analysis.get("all_text_on_package") or [],
            "visual_features": analysis.get("visual_features") or [],
            "folder_id": folder_id,

            "router_confidence": routing.get("confidence", 0),
            "router_reason": routing.get("reason", ""),
            "match_type": routing.get("match_type", "llm"),

            "status": "raw",
            "image_score": None,
            "submitted_by": str(user_id),
            "submitted_at": datetime.now(timezone.utc),
            "verified_by": None
        })

        db.collection("folder_descriptors").document(folder_id).update({
            "image_count": firestore.Increment(1)
        })

        try:
            log_to_bigquery(
                user_id=str(user_id),
                action="vision_image_saved",
                query_text=folder_id,
                status="saved",
                platform=analysis.get("brand", "unknown")
            )
        except Exception:
            pass

        print(f"[vision] saved → {gcs_uri}")
        return image_id

    except Exception as e:
        print(f"[vision] save_to_folder ERROR: {e}")
        return None


def save_to_unknown(image_bytes, user_id, analysis=None):
    try:
        image_id = uuid.uuid4().hex
        gcs_path = f"products/unknown/raw/{image_id}.jpg"
        gcs_uri = _upload_bytes_to_gcs_verified(image_bytes, gcs_path)

        db.collection("product_images").document(image_id).set({
            "image_id": image_id,
            "gcs_path": gcs_uri,
            "md5_hash": _image_md5(image_bytes),
            "folder_id": "unknown",
            "status": "raw",
            "analysis_raw": analysis,
            "submitted_by": str(user_id),
            "submitted_at": datetime.now(timezone.utc)
        })
        print(f"[vision] unknown → {gcs_uri}")
    except Exception as e:
        print(f"[vision] save_to_unknown ERROR: {e}")


# ════════════════════════════════════════════════════════════════════════════
# MAIN — process_image_for_training (5 қабатты логика)
# ════════════════════════════════════════════════════════════════════════════

def process_image_for_training(image_bytes, user_id):
    """
    ПРОЦЕСС B — 5 қабатты matching архитектурасы.

    1. Extraction  → Gemini (бір рет)
    2. Normalization → код
    3. Exact match → Firestore product_key
    4. Fuzzy match → thefuzz
    5. LLM Router  → Gemini (тек жаңа өнімде)
    """
    try:
        # ── 1. EXTRACTION ────────────────────────────────────────────────
        analysis = analyze_image_deeply(image_bytes)
        if not analysis or not analysis.get("brand"):
            save_to_unknown(image_bytes, user_id, analysis)
            return

        if analysis.get("confidence", 0) < 0.5:
            save_to_unknown(image_bytes, user_id, analysis)
            return

        # ── 2. NORMALIZATION ─────────────────────────────────────────────
        product_key = build_product_key(
            analysis.get("brand"),
            analysis.get("product_type"),
            analysis.get("flavor_variant"),
            analysis.get("volume_weight")
        )
        brand_lower = _norm_field(analysis["brand"])

        # ── 3. EXACT MATCH ───────────────────────────────────────────────
        exact = get_folder_by_exact_key(product_key)
        if exact:
            print(f"[vision] exact match → {exact['folder_id']}")
            routing = {"folder_id": exact["folder_id"], "confidence": 1.0,
                       "reason": "exact match", "match_type": "exact"}
            save_to_folder(image_bytes, user_id, analysis, routing)
            _notify_admin_image_saved(analysis, exact["folder_id"], "exact", user_id, image_bytes)
            return

        # ── 4. FUZZY MATCH ───────────────────────────────────────────────
        candidates = get_folder_descriptors(brand_lower)
        fuzzy_match, score = fuzzy_find_folder(product_key, candidates)
        if fuzzy_match:
            print(f"[vision] fuzzy match ({score}%) → {fuzzy_match['folder_id']}")
            add_product_key_variant(fuzzy_match["folder_id"], product_key)
            routing = {"folder_id": fuzzy_match["folder_id"], "confidence": score / 100,
                       "reason": f"fuzzy match {score}%", "match_type": "fuzzy"}
            save_to_folder(image_bytes, user_id, analysis, routing)
            _notify_admin_image_saved(analysis, fuzzy_match["folder_id"], "fuzzy", user_id, image_bytes)
            return

        # ── 5. LLM ROUTER (тек жаңа өнімде) ─────────────────────────────
        routing = route_to_folder(analysis, candidates) if candidates else \
            {"folder_id": "new_product", "confidence": 1.0, "reason": "Папка жоқ"}

        if routing["confidence"] < 0.75:
            if routing.get("reason", "").startswith("Қате:"):
                print(f"[vision] LLM timeout fallback — жаңа папка")
                new_folder_id = create_folder_descriptor(analysis, product_key)
                routing = {"folder_id": new_folder_id, "confidence": 1.0,
                           "reason": "timeout fallback", "match_type": "new", "_is_new": True}
            else:
                save_to_unknown(image_bytes, user_id, analysis)
                return

        if routing["folder_id"] in ("new_product", "unknown"):
            new_folder_id = create_folder_descriptor(analysis, product_key)
            routing["folder_id"] = new_folder_id
            routing["match_type"] = "new"
            routing["_is_new"] = True

        routing.setdefault("match_type", "llm")
        save_to_folder(image_bytes, user_id, analysis, routing)

        match_type = routing.get("match_type", "llm")
        _notify_admin_image_saved(analysis, routing["folder_id"], match_type, user_id, image_bytes)

        enrich_descriptor(routing["folder_id"], analysis, routing["confidence"])

    except Exception as e:
        print(f"[vision] process_image_for_training ERROR: {e}")


def _get_user_info(user_id):
    """Firestore-дан пайдаланушы ақпаратын алады."""
    try:
        doc = db.collection("users").document(str(user_id)).get()
        if doc.exists:
            return doc.to_dict()
    except Exception:
        pass
    return {}


def _format_user_block(user_id, user_info):
    """Пайдаланушы туралы мәтін блогін жасайды."""
    first_name = user_info.get("first_name", "Белгісіз")
    username = user_info.get("username", "")
    gender = user_info.get("gender", "")

    gender_emoji = "👨" if gender == "male" else "👩" if gender == "female" else "👤"
    username_line = f"\n🔗 @{username} | tg://user?id={user_id}" if username and username != "жоқ" else f"\n🔗 tg://user?id={user_id}"

    return (
        f"\n\n──────────────"
        f"\n{gender_emoji} {first_name}"
        f"{username_line}"
        f"\n🆔 ID: {user_id}"
    )


def _send_admin_notification(text, image_bytes=None):
    """Admin-ге хабарлама жіберу (суретпен немесе суретсіз)."""
    for admin_id in ADMIN_IDS:
        try:
            if image_bytes:
                send_photo_bytes(admin_id, image_bytes, text)
            else:
                send_message(admin_id, text)
        except Exception:
            pass


def _notify_admin_image_saved(analysis, folder_id, match_type, user_id, image_bytes=None):
    """
    Әр сурет сақталғанда admin-ге есеп береді.
    match_type: 'exact', 'fuzzy', 'llm', 'new'
    """
    brand = analysis.get("brand", "?")
    product_type = analysis.get("product_type", "")
    flavor = analysis.get("flavor_variant", "")
    volume = analysis.get("volume_weight", "")

    match_labels = {
        "exact":  "🎯 Exact match",
        "fuzzy":  "🔶 Fuzzy match",
        "llm":    "🤖 LLM router",
        "new":    "🆕 Жаңа папка ашылды",
    }
    match_label = match_labels.get(match_type, match_type)

    product_str = product_type
    if flavor: product_str += f", {flavor}"
    if volume: product_str += f", {volume}"

    user_info = _get_user_info(user_id)
    user_block = _format_user_block(user_id, user_info)

    text = (
        f"{match_label}\n\n"
        f"🏷 {brand} — {product_str}\n"
        f"📁 {folder_id}"
        f"{user_block}"
    )
    _send_admin_notification(text, image_bytes)


def _notify_admin_new_product(analysis, folder_id, image_bytes=None):
    """Артық қалды — _notify_admin_image_saved қолданылады."""
    pass


# ════════════════════════════════════════════════════════════════════════════
# DESCRIPTOR БАЙЫТУ (консервативті)
# ════════════════════════════════════════════════════════════════════════════

ENRICH_PROMPT = """Сен өнім ақпаратын қатаң жүйемен толықтыратын дәлсаушысың.

ҚОЛДАҒЫ DESCRIPTOR:
{existing_descriptor}

ЖАҢА СУРЕТ ТАЛДАУЫ:
{new_analysis}

МІНДЕТ: ТЕК JSON қайтар:
{{"new_text_keywords": [], "new_visual_keywords": []}}

ҚАТАҢ ЕРЕЖЕЛЕР:
1. ТЕК жаңа суреттен АНЫҚ ОҚЫЛҒАН ақпаратты қос
2. Descriptor-да БАР ақпаратты ҚАЙТАЛАМА
3. Максимум 3 кілт сөз
4. negative_keywords-ке ЕШҚАШАН тіме
5. Қосуға ештеңе жоқ болса — БОС тізім қайтар
6. ТЕК JSON, түсіндірме жазба"""


def enrich_descriptor(folder_id, new_analysis, routing_confidence):
    if routing_confidence < 0.92:
        return
    try:
        doc = db.collection("folder_descriptors").document(folder_id).get()
        if not doc.exists:
            return
        descriptor = doc.to_dict()

        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = ENRICH_PROMPT.format(
            existing_descriptor=json.dumps(_firestore_safe({
                "text_keywords": descriptor.get("text_keywords", []),
                "visual_keywords": descriptor.get("visual_keywords", []),
                "brand": descriptor.get("brand"),
                "product_type": descriptor.get("product_type"),
                "flavor_variant": descriptor.get("flavor_variant"),
            }), ensure_ascii=False),
            new_analysis=json.dumps(_firestore_safe({
                "all_text_on_package": new_analysis.get("all_text_on_package", []),
                "visual_features": new_analysis.get("visual_features", []),
                "flavor_variant": new_analysis.get("flavor_variant"),
                "volume_weight": new_analysis.get("volume_weight"),
            }), ensure_ascii=False)
        )

        response = model.generate_content(prompt, request_options={"timeout": 15})
        raw = re.sub(r'```json|```', '', response.text).strip()
        result = json.loads(raw)

        new_text = result.get("new_text_keywords", [])[:3]
        new_visual = result.get("new_visual_keywords", [])[:3]
        if not new_text and not new_visual:
            return

        existing_text = set(descriptor.get("text_keywords", []))
        existing_visual = set(descriptor.get("visual_keywords", []))

        safe_text = [w for w in new_text if w and isinstance(w, str) and w not in existing_text]
        safe_visual = [w for w in new_visual if w and isinstance(w, str) and w not in existing_visual]
        if not safe_text and not safe_visual:
            return

        update = {
            "enrichment_log": firestore.ArrayUnion([{
                "added_text": safe_text,
                "added_visual": safe_visual,
                "routing_confidence": routing_confidence,
                "enriched_at": datetime.now(timezone.utc).isoformat()
            }])
        }
        if safe_text:
            update["text_keywords"] = firestore.ArrayUnion(safe_text)
        if safe_visual:
            update["visual_keywords"] = firestore.ArrayUnion(safe_visual)

        db.collection("folder_descriptors").document(folder_id).update(update)
        print(f"[enrich] {folder_id}: +{safe_text} +{safe_visual}")

    except Exception as e:
        print(f"[enrich] қате (descriptor өзгерген жоқ): {e}")


# ════════════════════════════════════════════════════════════════════════════
# PROCESS C — ҚМДБ ХАЛАЛ ЛОГО ДЕТЕКТОР (өшірулі, Vision API қосылғанда)
# ════════════════════════════════════════════════════════════════════════════

HALAL_LOGO_KEYWORDS = [
    "halal", "халал", "қмдб", "думк", "qmdb",
    "halaldamu", "halal damu", "halal daму",
]


def detect_halal_logo(image_bytes):
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)

        logo_response = client.logo_detection(image=image)
        for logo in logo_response.logo_annotations:
            desc = logo.description.lower()
            for kw in HALAL_LOGO_KEYWORDS:
                if kw in desc and logo.score > 0.6:
                    return {"detected": True, "confidence": logo.score,
                            "method": "logo_detection", "description": logo.description}

        text_response = client.text_detection(image=image)
        full_text = text_response.full_text_annotation.text.lower() \
            if text_response.full_text_annotation else ""
        for kw in HALAL_LOGO_KEYWORDS:
            if kw in full_text:
                return {"detected": True, "confidence": 0.75,
                        "method": "ocr", "description": f"OCR: '{kw}'"}

        return {"detected": False, "confidence": 0.0, "method": "none", "description": ""}
    except Exception as e:
        print(f"[vision] detect_halal_logo қате: {e}")
        return {"detected": False, "confidence": 0.0, "method": "error", "description": str(e)}


def save_to_suspicious(image_bytes, user_id, ai_result, logo_result):
    try:
        image_id = uuid.uuid4().hex
        gcs_path = f"suspicious_logos/{image_id}.jpg"
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(image_bytes, content_type="image/jpeg")

        db.collection("suspicious_logos").document(image_id).set({
            "image_id": image_id,
            "gcs_path": f"gs://{BUCKET_NAME}/{gcs_path}",
            "detected_brand": ai_result.get("product_names", []),
            "ai_confidence": ai_result.get("confidence", 0.0),
            "logo_detected": True,
            "logo_confidence": logo_result["confidence"],
            "logo_method": logo_result.get("method", ""),
            "logo_description": logo_result.get("description", ""),
            "status": "pending_review",
            "reviewer": None, "reviewed_at": None, "action_taken": None, "notes": "",
            "submitted_by": str(user_id),
            "submitted_at": datetime.now(timezone.utc)
        })
        print(f"[vision] күдікті сақталды: {image_id}")
        return image_id
    except Exception as e:
        print(f"[vision] save_to_suspicious қате: {e}")
        return None


def notify_admin_suspicious(ai_result, logo_result, user_id):
    brand = (ai_result.get("product_names") or ["Белгісіз"])[0]
    text = (
        f"⚠️ КҮДІКТІ ЛОГО АНЫҚТАЛДЫ!\n\n"
        f"🏷 Өнім: {brand}\n"
        f"🎯 Сенімділік: {logo_result.get('confidence', 0):.0%} ({logo_result.get('method', '')})\n"
        f"👤 Жіберген: user_{user_id}\n\n"
        f"Тексеру үшін: Firestore → suspicious_logos"
    )
    for admin_id in ADMIN_IDS:
        try:
            send_message(admin_id, text)
        except Exception:
            pass


def check_violators_db(product_name, lang="kz"):
    try:
        results = db.collection("illegal_logo_violators") \
            .where("certified_at", "==", None).stream()
        for doc in results:
            data = doc.to_dict()
            brand = (data.get("brand_name") or "").lower()
            if brand and brand in product_name.lower():
                confirmed_at = data.get("confirmed_at", "")
                if lang == "ru":
                    return (
                        f"🚫 <b>ВНИМАНИЕ!</b>\n\n"
                        f"«{data.get('brand_name')}» — уличён в <b>незаконном использовании</b> "
                        f"логотипа ДУМК Халал Даму.\n\n"
                        f"📅 Дата: {confirmed_at}\n"
                        f"✅ Сертификат ДУМК: <b>ОТСУТСТВУЕТ</b>\n\n"
                        f"Не можем подтвердить халяльность."
                    )
                return (
                    f"🚫 <b>НАЗАР АУДАРЫҢЫЗ!</b>\n\n"
                    f"«{data.get('brand_name')}» — ҚМДБ Халал Даму логотипін "
                    f"<b>ЗАҢСЫЗ пайдаланғаны</b> анықталған.\n\n"
                    f"📅 Анықталған: {confirmed_at}\n"
                    f"✅ Ресми ҚМДБ сертификаты: <b>ЖОҚ</b>\n\n"
                    f"Бұл өнімнің халал екендігіне кепілдік бере алмаймыз."
                )
        return None
    except Exception as e:
        print(f"[vision] check_violators_db қате: {e}")
        return None
