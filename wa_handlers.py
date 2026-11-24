# -*- coding: utf-8 -*-
"""
WhatsApp Cloud API webhook өңдеушісі.

Telegram логикасының өзегін (іздеу, сурет тану, ЖИ, Firestore, аудармалар)
сол күйінде қайта қолданады, тек жауаптарды wa_sender арқылы жібереді.

Пайдаланушы ID-сі: "wa_<телефон>" — Telegram ID-лерімен қақтығыспайды.
"""
import hashlib
import hmac
import math
import time

from config import WA_VERIFY_TOKEN, WA_APP_SECRET, WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID
import wa_sender as wa
from db_core import (db, add_user, save_chat_history, log_to_bigquery, check_access,
                     increment_usage, get_user_language, set_user_language,
                     get_item_by_id, get_search_session, save_search_session, _get_user_data,
                     _invalidate_user_cache)
from translations import t
from search_logic import search_data, get_nearby_companies
from formatters import format_detail_message
from quotes import get_quote

PLATFORM = "whatsapp"

# Жауаптағы батырмалардың ішінен WhatsApp-та өңделетіндері
SUPPORTED_PREFIXES = ("itm:", "srch:", "loc:", "fb:", "lang:")

# ── Тек WhatsApp-қа арналған мәтіндер (Telegram мәтіндерінде inline режим, @логин бар) ──
WA_TEXTS = {
    "welcome": {
        "kz": ("Ассаламу алейкум, {name}! 👋\n\n"
               "Мен — ҚМДБ *Halal Damu* ботымын. Міне, не істей аламын:\n\n"
               "🔍 Өнім немесе мекеме атауын жазыңыз — халал екенін тексеремін\n"
               "📸 Өнімнің суретін жіберіңіз — өзім оқып, базадан іздеймін\n"
               "📍 Орныңызды жіберіңіз — жаныңыздағы халал мекемелерді табамын\n"
               "🧪 Е-қоспаларды тексеремін (мысалы: _E471_)\n\n"
               "🌐 Тілді өзгерту үшін: *тіл* деп жазыңыз"),
        "ru": ("Ассаламу алейкум, {name}! 👋\n\n"
               "Я — бот ДУМК *Halal Damu*. Вот что я умею:\n\n"
               "🔍 Напишите название продукта или заведения — проверю халяльность\n"
               "📸 Пришлите фото продукта — сам распознаю и найду в базе\n"
               "📍 Отправьте местоположение — найду халяльные заведения рядом\n"
               "🧪 Проверяю Е-добавки (например: _E471_)\n\n"
               "🌐 Чтобы сменить язык, напишите: *язык*"),
    },
    "location_prompt": {
        "kz": "📍 Жаныңыздағы халал мекемелерді табу үшін орныңызды жіберіңіз:",
        "ru": "📍 Отправьте местоположение, чтобы найти халяльные заведения рядом:",
    },
    "choose_language": {
        "kz": "🌐 Тілді таңдаңыз / Выберите язык:",
        "ru": "🌐 Тілді таңдаңыз / Выберите язык:",
    },
    "lang_changed": {
        "kz": "✅ Тіл өзгертілді: Қазақша 🇰🇿",
        "ru": "✅ Язык изменён: Русский 🇷🇺",
    },
    "choose": {"kz": "Таңдау", "ru": "Выбрать"},
    "choose_prompt": {"kz": "👇 Таңдаңыз:", "ru": "👇 Выберите:"},
    "unsupported": {
        "kz": "🙏 Кешіріңіз, мұндай хабарды оқи алмаймын. Өнім атауын жазыңыз, суретін немесе орныңызды жіберіңіз.",
        "ru": "🙏 Извините, такой тип сообщения я не понимаю. Напишите название, пришлите фото или местоположение.",
    },
    "expired": {
        "kz": "⌛ Бұл тізімнің мерзімі өтіп кетті. Іздеуді қайталаңыз.",
        "ru": "⌛ Этот список устарел. Повторите поиск.",
    },
}


def wt(key, lang="kz", **kwargs):
    entry = WA_TEXTS.get(key, {})
    text = entry.get(lang) or entry.get("kz") or key
    return text.format(**kwargs) if kwargs else text


GREETINGS = {
    "start", "/start", "сәлем", "салем", "салам", "сәлеметсіз бе", "салеметсиз бе",
    "ассаламу алейкум", "ассалаумағалейкум", "ассалаумагалейкум", "assalamu alaikum",
    "привет", "здравствуйте", "hi", "hello", "меню", "menu", "көмек", "помощь", "help",
}
LANG_WORDS = {"тіл", "тил", "язык", "language", "lang", "тілді өзгерту", "сменить язык"}
LOCATION_WORDS = {"локация", "орным", "орын", "геолокация", "рядом", "жанымда", "location"}


# ════════════════════════════════════════════════════════════════
# HTTP КІРУ НҮКТЕСІ
# ════════════════════════════════════════════════════════════════

def is_whatsapp_request(request):
    """Сұраныс Meta-дан келгенін анықтайды (бір URL-да Telegram-мен бірге жұмыс істеу үшін)."""
    if request.method == "GET":
        return request.args.get("hub.mode") is not None
    return bool(request.headers.get("X-Hub-Signature-256"))


def _valid_signature(request):
    if not WA_APP_SECRET:
        print("[wa] WA_APP_SECRET орнатылмаған — сұраныс қабылданбайды")
        return False
    sig = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(WA_APP_SECRET.encode(), request.get_data(),
                                    hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def handle_whatsapp_request(request):
    """Flask request → (body, status)."""
    if request.method == "GET":
        # Meta webhook-ты тіркеген кездегі растау
        if (request.args.get("hub.mode") == "subscribe"
                and WA_VERIFY_TOKEN
                and request.args.get("hub.verify_token") == WA_VERIFY_TOKEN):
            return request.args.get("hub.challenge", ""), 200
        return "Forbidden", 403

    if request.method != "POST":
        return "OK", 200

    if not _valid_signature(request):
        return "Invalid signature", 403

    if not (WA_ACCESS_TOKEN and WA_PHONE_NUMBER_ID):
        print("[wa] WA_ACCESS_TOKEN / WA_PHONE_NUMBER_ID орнатылмаған")
        return "OK", 200

    payload = request.get_json(silent=True) or {}
    try:
        process_payload(payload)
    except Exception as e:
        import traceback
        print(f"[wa] payload өңдеу қатесі: {e}")
        traceback.print_exc()
    # Meta 200 алмаса қайта-қайта жібереді — әрқашан 200 қайтарамыз
    return "OK", 200


# ════════════════════════════════════════════════════════════════
# ДУБЛИКАТТАН ҚОРҒАУ
# ════════════════════════════════════════════════════════════════

_PROCESSED = {}
_PROCESSED_MAX = 500


def _already_processed(msg_id):
    """Meta баяу жауапта хабарды қайта жібереді. Instance жадында + Firestore-да тексереміз."""
    if not msg_id:
        return False
    if msg_id in _PROCESSED:
        return True
    _PROCESSED[msg_id] = time.time()
    if len(_PROCESSED) > _PROCESSED_MAX:
        for k in sorted(_PROCESSED, key=_PROCESSED.get)[:100]:
            del _PROCESSED[k]
    try:
        # create() құжат бар болса қате лақтырады — instance-тар арасында атомарлы
        db.collection("wa_processed").document(msg_id).create({"at": time.time()})
    except Exception as e:
        if "exist" in str(e).lower() or type(e).__name__ in ("AlreadyExists", "Conflict"):
            print(f"[wa] Дубликат хабар елемеледі: {msg_id}")
            return True
        print(f"[wa] dedupe Firestore қатесі (өңдеуді жалғастырамыз): {e}")
    return False


# ════════════════════════════════════════════════════════════════
# PAYLOAD ӨҢДЕУ
# ════════════════════════════════════════════════════════════════

def process_payload(payload):
    if payload.get("object") != "whatsapp_business_account":
        return
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "")
                     for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                if _already_processed(msg.get("id")):
                    continue
                t0 = time.perf_counter()
                try:
                    handle_message(msg, names.get(msg.get("from"), ""))
                except Exception as e:
                    import traceback
                    print(f"[wa] handle_message қате: {e}")
                    traceback.print_exc()
                print(f"[wa] {msg.get('type')} өңделді: {time.perf_counter() - t0:.3f}с")
            # value["statuses"] (sent/delivered/read) — елемейміз


class _Ctx:
    """Бір кіріс хабардың контексті."""
    def __init__(self, msg, name):
        self.to = msg["from"]                 # жауап жіберілетін нөмір
        self.uid = f"wa_{msg['from']}"        # Firestore / BigQuery ID
        self.msg_id = msg.get("id")
        self.name = name or "Досым"
        data = _get_user_data(self.uid)
        self.is_new = not data
        self.lang = data.get("language", "kz")


def handle_message(msg, name=""):
    ctx = _Ctx(msg, name)
    mtype = msg.get("type")
    wa.mark_read(ctx.msg_id, typing=True)

    if ctx.is_new:
        db.collection("users").document(ctx.uid).set(
            {"first_name": ctx.name, "username": "жоқ", "platform": PLATFORM,
             "wa_id": ctx.to}, merge=True)
        _invalidate_user_cache(ctx.uid)   # әйтпесе кэште бос {} қалып, келесі хабар да "жаңа" саналады

    if mtype == "text":
        handle_text(ctx, (msg.get("text") or {}).get("body", ""))
    elif mtype == "image":
        handle_image(ctx, (msg.get("image") or {}).get("id"))
    elif mtype == "location":
        loc = msg.get("location") or {}
        handle_location(ctx, loc.get("latitude"), loc.get("longitude"))
    elif mtype == "interactive":
        inter = msg.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        if reply.get("id"):
            handle_reply(ctx, reply["id"])
    elif mtype == "button":   # template quick-reply
        payload = (msg.get("button") or {}).get("payload") or (msg.get("button") or {}).get("text", "")
        if payload.startswith(SUPPORTED_PREFIXES):
            handle_reply(ctx, payload)
        else:
            handle_text(ctx, payload)
    elif mtype in ("reaction", "unsupported", "system", "request_welcome"):
        if mtype == "request_welcome":
            send_welcome(ctx)
        return
    else:
        wa.send_text(ctx.to, wt("unsupported", ctx.lang), reply_to=ctx.msg_id)


# ════════════════════════════════════════════════════════════════
# ҚАРСЫ АЛУ / ТІЛ
# ════════════════════════════════════════════════════════════════

def send_language_choice(ctx):
    wa.send_buttons(ctx.to, wt("choose_language", ctx.lang),
                    [("lang:kz", "🇰🇿 Қазақша"), ("lang:ru", "🇷🇺 Русский")],
                    reply_to=ctx.msg_id)


def send_welcome(ctx):
    wa.send_text(ctx.to, wt("welcome", ctx.lang, name=ctx.name))
    wa.send_location_request(ctx.to, wt("location_prompt", ctx.lang))


def _deny(ctx, tier, action):
    from handlers_message import _access_denied_msg
    text, _ = _access_denied_msg(ctx.lang, tier)
    log_to_bigquery(ctx.uid, "limit_hit", action, "Лимит бітті", platform=PLATFORM)
    wa.send_text(ctx.to, wa.html_to_wa(text), reply_to=ctx.msg_id)


def _feedback_markup(lang):
    return {"inline_keyboard": [[
        {"text": t("btn_good", lang), "callback_data": "fb:good:ai"},
        {"text": t("btn_bad", lang), "callback_data": "fb:bad:ai"},
    ]]}


def _send(ctx, text, markup=None, image_url=None, reply=True):
    return wa.send_rich(ctx.to, text, markup, image_url=image_url,
                        reply_to=ctx.msg_id if reply else None,
                        list_label=wt("choose", ctx.lang),
                        allowed_prefixes=SUPPORTED_PREFIXES,
                        prompt=wt("choose_prompt", ctx.lang))


def _react_for_status(ctx, status_text, confidence="exact"):
    if "Белсенді" in status_text or "Рұқсат" in status_text:
        emoji = "✅"
    elif any(s in status_text for s in ("Мерзімі", "⚠️", "Қайтарып", "🚫", "Харам")):
        emoji = "⚠️"
    elif confidence == "fuzzy":
        emoji = "🤔"
    else:
        return
    wa.send_reaction(ctx.to, ctx.msg_id, emoji)


# ════════════════════════════════════════════════════════════════
# МӘТІН
# ════════════════════════════════════════════════════════════════

def handle_text(ctx, text):
    text = (text or "").strip()
    if not text:
        return
    low = text.lower().strip("!.?, ")

    if low in LANG_WORDS:
        send_language_choice(ctx)
        return

    if low in GREETINGS:
        add_user(ctx.uid, ctx.name, "жоқ")
        if ctx.is_new:
            send_language_choice(ctx)
            log_to_bigquery(ctx.uid, "start", text, "Жаңа қолданушы (WA)", platform=PLATFORM)
        else:
            send_welcome(ctx)
            log_to_bigquery(ctx.uid, "start", text, "Ескі қолданушы (WA)", platform=PLATFORM)
        return

    if low in LOCATION_WORDS:
        wa.send_location_request(ctx.to, wt("location_prompt", ctx.lang), reply_to=ctx.msg_id)
        return

    search_flow(ctx, text)

    if ctx.is_new:
        # Бірден өнім атын жазған жаңа қолданушыға — жауаптан кейін тіл таңдауын ұсынамыз
        send_language_choice(ctx)


def search_flow(ctx, text):
    """handlers_message.py-дегі мәтін логикасының WhatsApp нұсқасы."""
    from classifier import classify_query, should_classify
    from ai_core import extract_search_term, get_not_found_reply

    has_access, tier = check_access(ctx.uid, False)
    if not has_access:
        _deny(ctx, tier, "text_search")
        return
    is_prem = tier in ("premium", "VIP")

    search_query = text
    if should_classify(text):
        action, extracted = classify_query(text)
        if action == "chat":
            _ai_chat(ctx, text, is_prem, "Классификатор: чат")
            return
        if extracted:
            search_query = extracted

    found = search_data(search_query)
    if found:
        send_search_results(ctx, found, text, tier, "text_search")
        increment_usage(ctx.uid)
        return

    normalized = extract_search_term(search_query)
    if normalized:
        print(f"[wa AI#1] '{search_query}' → '{normalized}'")
        found = search_data(normalized)
    if found:
        send_search_results(ctx, found, text, tier, "text_search_normalized",
                            f"AI нормализациямен: {normalized}")
        increment_usage(ctx.uid)
        return

    action, _ = classify_query(text)
    if action == "chat":
        _ai_chat(ctx, text, is_prem, "4D: classify→chat")
        return

    reply = get_not_found_reply(search_query, normalized, lang=ctx.lang)
    if is_prem:
        quote = get_quote("not_found", ctx.lang)
        if quote:
            reply += f"\n\n{quote}"
    _send(ctx, reply, _feedback_markup(ctx.lang))
    save_chat_history(ctx.uid, "user", text)
    save_chat_history(ctx.uid, "model", reply)
    log_to_bigquery(ctx.uid, "not_found", text,
                    f"4D: classify→search, табылмады (normalized: {normalized})",
                    is_premium=is_prem, result_count=0, platform=PLATFORM)
    increment_usage(ctx.uid)


def _ai_chat(ctx, text, is_prem, status):
    from ai_core import chat_with_ai
    # chat_id берілмейді → streaming/edit жоқ, дайын мәтін қайтарады
    reply = chat_with_ai(ctx.uid, text, False) or ""
    if reply:
        _send(ctx, reply, _feedback_markup(ctx.lang))
    save_chat_history(ctx.uid, "user", text)
    save_chat_history(ctx.uid, "model", reply)
    log_to_bigquery(ctx.uid, "ai_chat", text, status, is_premium=is_prem,
                    result_count=0, platform=PLATFORM)
    increment_usage(ctx.uid)


def send_search_results(ctx, found, original_text, tier, log_action, log_status=None):
    is_prem = tier in ("premium", "VIP")
    if len(found) == 1:
        item = found[0]
        confidence = item.get("confidence", "exact")
        text, markup = format_detail_message(item, confidence=confidence,
                                             query_text=original_text, lang=ctx.lang, tier=tier)
        _send(ctx, text, markup, image_url=item.get("image_url") or None)
        if is_prem:
            _react_for_status(ctx, item.get("status", ""), confidence)
        result_count, status = 1, log_status or f"Табылды (1/{confidence})"
    else:
        from handlers_message import _build_search_results_page
        exact = [i for i in found if i.get("confidence") == "exact"]
        fuzzy = [i for i in found if i.get("confidence") == "fuzzy"]
        items = exact + fuzzy
        session_id = save_search_session(ctx.uid, items)
        text, keyboard = _build_search_results_page(items, 1, 5, session_id=session_id, lang=ctx.lang)
        _send(ctx, text, {"inline_keyboard": keyboard})
        result_count, status = len(items), log_status or f"Табылды (Көп/{len(items)})"
        confidence = None

    save_chat_history(ctx.uid, "user", original_text)
    save_chat_history(ctx.uid, "model", wa.html_to_wa(text))
    log_to_bigquery(ctx.uid, log_action, original_text, status, is_premium=is_prem,
                    result_count=result_count, confidence=confidence, platform=PLATFORM)


# ════════════════════════════════════════════════════════════════
# СУРЕТ
# ════════════════════════════════════════════════════════════════

def handle_image(ctx, media_id):
    has_access, tier = check_access(ctx.uid, False)
    if not has_access:
        _deny(ctx, tier, "photo_search")
        return

    image_bytes = wa.download_media(media_id) if media_id else None
    if not image_bytes:
        wa.send_text(ctx.to, t("photo_download_error", ctx.lang), reply_to=ctx.msg_id)
        return

    from ai_core import handle_photo
    try:
        result_msg, markup, image_url = handle_photo(image_bytes, ctx.uid, None, lang=ctx.lang)
    except Exception as e:
        print(f"[wa handle_image] handle_photo қате: {e}")
        result_msg, markup, image_url = t("photo_error", ctx.lang), None, ""

    _send(ctx, result_msg, markup, image_url=image_url or None)
    if tier in ("premium", "VIP"):
        if "✅" in result_msg:
            wa.send_reaction(ctx.to, ctx.msg_id, "✅")
        elif "⚠️" in result_msg or "🚫" in result_msg:
            wa.send_reaction(ctx.to, ctx.msg_id, "⚠️")

    save_chat_history(ctx.uid, "user", "Мен саған бір сурет жібердім")
    save_chat_history(ctx.uid, "model", wa.html_to_wa(result_msg))
    log_to_bigquery(ctx.uid, "photo_search", "Сурет", "Тексерілді",
                    is_premium=(tier in ("premium", "VIP")), platform=PLATFORM)
    increment_usage(ctx.uid)


# ════════════════════════════════════════════════════════════════
# ЛОКАЦИЯ
# ════════════════════════════════════════════════════════════════

def handle_location(ctx, lat, lon, page=1, log=True):
    if lat is None or lon is None:
        return
    has_access, tier = check_access(ctx.uid, False)
    if not has_access:
        _deny(ctx, tier, "location_search")
        return

    text, markup = get_nearby_companies(float(lat), float(lon), page=page, lang=ctx.lang)
    if tier in ("premium", "VIP") and page == 1:
        quote = get_quote("location", ctx.lang)
        if quote:
            text += f"\n\n{quote}"
    _send(ctx, text, markup)

    if log:
        from handlers_message import _get_city
        city = _get_city(lat, lon)
        log_to_bigquery(ctx.uid, "location_search", f"{lat}, {lon}", "Тізім берілді",
                        is_premium=(tier in ("premium", "VIP")),
                        platform=f"{PLATFORM}:{city}" if city else PLATFORM)
        increment_usage(ctx.uid)


# ════════════════════════════════════════════════════════════════
# БАТЫРМА / ТІЗІМ ЖАУАПТАРЫ (Telegram callback_data-ның баламасы)
# ════════════════════════════════════════════════════════════════

def handle_reply(ctx, data):
    print(f"[wa reply] {ctx.uid}: {data}")

    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        if lang not in ("kz", "ru"):
            return
        set_user_language(ctx.uid, lang)
        ctx.lang = lang
        wa.send_text(ctx.to, wt("lang_changed", lang))
        send_welcome(ctx)
        return

    if data.startswith("itm:"):
        _, t_code, item_id = data.split(":", 2)
        item = get_item_by_id(t_code, item_id)
        if not item:
            wa.send_text(ctx.to, wt("expired", ctx.lang), reply_to=ctx.msg_id)
            return
        has_access, tier = check_access(ctx.uid, False)
        text, markup = format_detail_message(item, confidence="exact", lang=ctx.lang, tier=tier)
        _send(ctx, text, markup, image_url=item.get("image_url") or None)
        if tier in ("premium", "VIP"):
            _react_for_status(ctx, item.get("status", ""))
        return

    if data.startswith("srch:"):
        from handlers_message import _build_search_results_page
        _, page_str, session_id = data.split(":", 2)
        items = []
        for m in get_search_session(session_id):
            t_code = "c" if m.get("t") == "Мекеме" else "i"
            item = get_item_by_id(t_code, m["id"])
            if item:
                item["confidence"] = m.get("c", "exact")
                items.append(item)
        if not items:
            wa.send_text(ctx.to, wt("expired", ctx.lang), reply_to=ctx.msg_id)
            return
        page = max(1, min(int(page_str), math.ceil(len(items) / 5)))
        text, keyboard = _build_search_results_page(items, page, 5, session_id=session_id, lang=ctx.lang)
        _send(ctx, text, {"inline_keyboard": keyboard})
        return

    if data.startswith("loc:"):
        _, page_str, lat, lon = data.split(":", 3)
        handle_location(ctx, float(lat), float(lon), page=int(page_str), log=False)
        return

    if data.startswith("fb:reason:"):
        parts = data.split(":")
        code = parts[2] if len(parts) > 2 else "other"
        reason = "Қате ақпарат" if code == "info" else "ЖИ қатесі" if code == "ai" else "Басқа"
        wa.send_text(ctx.to, t("feedback_fixed", ctx.lang))
        log_to_bigquery(ctx.uid, "feedback", f"👎 Қате ({reason})", "Кері байланыс", platform=PLATFORM)
        return

    if data.startswith("fb:good"):
        wa.send_reaction(ctx.to, ctx.msg_id, "❤️")
        wa.send_text(ctx.to, t("feedback_thanks", ctx.lang))
        what = "👍 AI жауабы пайдалы" if data == "fb:good:ai" else "👍 Пайдалы"
        log_to_bigquery(ctx.uid, "feedback", what, "Кері байланыс", platform=PLATFORM)
        return

    if data.startswith("fb:bad"):
        suffix = data[7:]
        wa.send_buttons(ctx.to, "🛠 " + ("Қандай қате?" if ctx.lang == "kz" else "Какая ошибка?"), [
            (f"fb:reason:info:{suffix}", t("btn_bad_info", ctx.lang)),
            (f"fb:reason:ai:{suffix}", t("btn_bad_ai", ctx.lang)),
            (f"fb:reason:other:{suffix}", t("btn_bad_other", ctx.lang)),
        ])
        return

    print(f"[wa reply] Белгісіз батырма: {data}")
