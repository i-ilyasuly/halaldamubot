import uuid
import re
import calendar
from datetime import datetime
from translations import t
from quotes import get_quote

def strip_html(text):
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<p[^>]*>', '', text)
    text = re.sub(r'</p>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


# ── Кликтік күн ─────────────────────────────────────────────────────────────

def _date_to_unix(date_str: str):
    """'DD.MM.YYYY' → Unix timestamp (UTC 00:00)"""
    try:
        dt = datetime.strptime(date_str.strip(), "%d.%m.%Y")
        return int(calendar.timegm(dt.timetuple()))
    except Exception:
        return None

def _tg_validity(d_start: str, d_end: str, lang: str) -> str:
    """
    ⚠️ ENTITY_DATE_TOO_LONG қатесін болдырмау үшін:
    <tg-time> тегі ішіне тек ҚЫСҚА мәтін — тек күн ғана!
    «Жарамдылығы:» белгісі тег СЫРТЫНДА тұруы керек.

    Формат: 📅 Жарамдылығы: 04.12.2025 – [03.12.2026]
    Мұндағы [03.12.2026] — кликтік, тек аяқталу күні
    """
    unix_end = _date_to_unix(d_end)

    if lang == 'kz':
        prefix = f"📅 Жарамдылығы: {d_start} – "
    else:
        prefix = f"📅 Срок действия: {d_start} – "

    if unix_end:
        return f'{prefix}<tg-time unix="{unix_end}" format="D">{d_end}</tg-time>'
    return f"{prefix}{d_end}"


# ── Аудармашы ────────────────────────────────────────────────────────────────

def _localize_status(status, lang):
    if lang != 'ru':
        return status
    return (status
        .replace("✅ Рұқсат етілген", "✅ Разрешено (халяль)")
        .replace("🚫 Харам",          "🚫 Харам")
        .replace("⚠️ Күдікті",        "⚠️ Сомнительно")
        .replace("✅ Белсенді",        "✅ Активен")
        .replace("❌ Мерзімі аяқталған", "❌ Срок истёк")
        .replace("🚫 Қайтарып алынған", "🚫 Отозван"))


# ── Элемент сөздігін форматтау ───────────────────────────────────────────────

def format_item_dict(data, type_name):
    if type_name == "Мекеме":
        d_start = data.get("certificate_date_start", "")
        d_end = data.get("certificate_date_end", "")
        cert_status = str(data.get("certificate_status", "active")).strip().lower()
        if cert_status == "active": st = "✅ Белсенді"
        elif cert_status == "expired": st = "❌ Мерзімі аяқталған"
        elif cert_status == "revoked": st = "🚫 Қайтарып алынған"
        else: st = f"⚠️ {cert_status}"

        image_url = ""
        fi = data.get("featured_image")
        if isinstance(fi, dict):
            image_url = fi.get("thumbnail", "") or fi.get("full", "") or ""

        return {
            "id": str(data.get("id", uuid.uuid4().hex[:8])),
            "type": "Мекеме",
            "title": data.get("title") or data.get("legal_name", "Белгісіз"),
            "desc": data.get("legal_name", ""),
            "address": data.get("address") or data.get("legal_address", "Мекенжай көрсетілмеген"),
            "map_link": data.get("map_link", ""),
            "date_start": d_start,
            "date_end": d_end,
            "status": st,
            "image_url": image_url
        }
    else:
        raw_status = data.get("status")
        status_name = ""
        if isinstance(raw_status, dict):
            status_name = raw_status.get("name", "")
        elif isinstance(raw_status, str):
            status_name = raw_status

        if status_name == "Халяль":
            st = "✅ Рұқсат етілген"
        elif status_name == "Харам":
            st = "🚫 Харам"
        else:
            st = "⚠️ Күдікті"

        item_title = data.get("title", "") or str(data.get("slug", "")).upper()
        return {
            "id": str(data.get("id", uuid.uuid4().hex[:8])),
            "type": "Қоспа",
            "title": item_title,
            "desc": data.get("name", ""),
            "info": strip_html(data.get("desc", "")),
            "status": st
        }


# ── Дәйексөз санатын анықтау ─────────────────────────────────────────────────

def _get_quote_category(item: dict, confidence: str = 'exact') -> str:
    if confidence == 'fuzzy':
        return 'suspicious'
    status = item.get('status', '')
    if item['type'] == 'Мекеме':
        if "Белсенді" in status:    return 'halal'
        elif "аяқталған" in status: return 'expired'
        elif "Мерзімі" in status:   return 'expired'
        elif "Қайтарып" in status:  return 'haram'
        elif "Жойылған" in status:  return 'haram'
        else:                       return 'suspicious'
    else:
        if "Рұқсат" in status:      return 'halal'
        elif "Харам" in status:     return 'haram'
        else:                       return 'suspicious'


# ── Негізгі форматтаушы ──────────────────────────────────────────────────────

def format_detail_message(item, confidence='exact', query_text='', lang='kz', tier='free'):
    """
    Хабарлама форматы:
      1. Статус мәтіні  — қалың мәтін (жай жол)
      2. Cert ақпараты  — <blockquote> ашық
      3. Аят / мақал   — <blockquote expandable> (тек premium/VIP)
    """
    clean_title = str(item['title']).strip('«»"\' ')

    fuzzy_warning = ""
    if confidence == 'fuzzy':
        fuzzy_warning = t('fuzzy_warning', lang, query=query_text, title=clean_title)

    quote_category = _get_quote_category(item, confidence)

    # ════════════════════════════════════════════════════════════════════════
    # МЕКЕМЕ
    # ════════════════════════════════════════════════════════════════════════
    if item['type'] == 'Мекеме':

        # 1. Статус мәтіні ───────────────────────────────────────────────────
        if "Белсенді" in item['status']:
            msg = fuzzy_warning + t('result_active', lang, title=clean_title)
        elif "аяқталған" in item['status'] or "Мерзімі" in item['status']:
            msg = fuzzy_warning + t('result_expired', lang, title=clean_title)
        elif "Қайтарып" in item['status'] or "Жойылған" in item['status']:
            msg = fuzzy_warning + t('result_revoked', lang, title=clean_title)
        else:
            msg = fuzzy_warning + t('result_unknown', lang, title=clean_title)

        # 2. Cert ақпараты — ашық <blockquote> ──────────────────────────────
        cert_lines = []

        if item['desc'] and item['desc'] != "Белгісіз":
            cert_lines.append(t('result_manufacturer', lang, desc=item['desc']).strip())

        cert_lines.append(
            t('result_status', lang, status=_localize_status(item['status'], lang)).strip()
        )

        d_start = item.get('date_start')
        d_end   = item.get('date_end')
        if d_start and d_end:
            cert_lines.append(_tg_validity(d_start, d_end, lang))
        elif d_end:
            # Тек аяқталу күні бар болса — tg-time ішіне тек күн!
            unix_end = _date_to_unix(d_end)
            if lang == 'kz':
                prefix = "📅 Жарамдылығы: "
            else:
                prefix = "📅 Действителен до: "
            if unix_end:
                cert_lines.append(f'{prefix}<tg-time unix="{unix_end}" format="D">{d_end}</tg-time>')
            else:
                cert_lines.append(f"{prefix}{d_end}")

        cert_block = "\n".join(cert_lines)
        # \n арқылы жақын орналасу (тым алшақ болмасын)
        msg += f"\n<blockquote>{cert_block}</blockquote>"

        # 3. Дәйексөз — <blockquote expandable> (тек premium/VIP) ───────────
        if tier in ("premium", "VIP"):
            quote = get_quote(quote_category, lang)
            if quote:
                msg += f"\n{quote}"

        # Батырмалар ─────────────────────────────────────────────────────────
        keys = []
        if item.get('map_link') and "Белсенді" in item['status']:
            keys.append([{"text": t('btn_map', lang),
                          "url": item['map_link'], "style": "primary"}])
        t_code = "c"
        keys.append([
            {"text": t('btn_good', lang),
             "callback_data": f"fb:good:itm:{t_code}:{item['id']}", "style": "success"},
            {"text": t('btn_bad', lang),
             "callback_data": f"fb:bad:itm:{t_code}:{item['id']}", "style": "danger"}
        ])
        return msg, {"inline_keyboard": keys}

    # ════════════════════════════════════════════════════════════════════════
    # ҚОСПА
    # ════════════════════════════════════════════════════════════════════════
    else:

        # 1. Статус мәтіні ───────────────────────────────────────────────────
        if "Рұқсат" in item['status']:
            msg = fuzzy_warning + t('result_ingredient_halal', lang, title=clean_title)
        elif "Харам" in item['status']:
            msg = fuzzy_warning + t('result_ingredient_haram', lang, title=clean_title)
        else:
            msg = fuzzy_warning + t('result_ingredient_suspicious', lang, title=clean_title)

        # 2. Қоспа ақпараты — ашық <blockquote> ─────────────────────────────
        ingr_lines = []
        ingr_lines.append(t('result_scientific_name', lang, desc=item['desc']).strip())
        ingr_lines.append(
            t('result_status', lang, status=_localize_status(item['status'], lang)).strip()
        )
        if item.get('info'):
            ingr_lines.append(t('result_info', lang, info=strip_html(item['info'])).strip())

        ingr_block = "\n".join(ingr_lines)
        msg += f"\n<blockquote>{ingr_block}</blockquote>"

        # 3. Дәйексөз — <blockquote expandable> (тек premium/VIP) ───────────
        if tier in ("premium", "VIP"):
            quote = get_quote(quote_category, lang)
            if quote:
                msg += f"\n{quote}"

        # Батырмалар ─────────────────────────────────────────────────────────
        keys = []
        t_code = "i"
        keys.append([
            {"text": t('btn_good', lang),
             "callback_data": f"fb:good:itm:{t_code}:{item['id']}", "style": "success"},
            {"text": t('btn_bad', lang),
             "callback_data": f"fb:bad:itm:{t_code}:{item['id']}", "style": "danger"}
        ])
        return msg, {"inline_keyboard": keys}
