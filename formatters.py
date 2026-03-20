import uuid
import re
from translations import t

def strip_html(text):
    """HTML тегтерді жойып, таза мәтін қайтарады"""
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<p[^>]*>', '', text)
    text = re.sub(r'</p>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

def _localize_status(status, lang):
    """Статус жолын берілген тілге аударады (display үшін ғана)."""
    if lang != 'ru':
        return status
    return (status
        .replace("✅ Рұқсат етілген", "✅ Разрешено (халяль)")
        .replace("🚫 Харам",          "🚫 Харам")
        .replace("⚠️ Күдікті",        "⚠️ Сомнительно")
        .replace("✅ Белсенді",        "✅ Активен")
        .replace("❌ Мерзімі аяқталған", "❌ Срок истёк")
        .replace("🚫 Қайтарып алынған", "🚫 Отозван"))

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
        # Халяль → ✅, Харам → 🚫, Күдікті/басқа → ⚠️
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

def format_detail_message(item, confidence='exact', query_text='', lang='kz'):
    """
    confidence='exact' → қалыпты хабар
    confidence='fuzzy' → үстіне ескерту қосылады
    lang='kz' | 'ru' → хабар тілі
    """
    clean_title = str(item['title']).strip('«»"\' ')

    # FUZZY ЕСКЕРТУІ
    fuzzy_warning = ""
    if confidence == 'fuzzy':
        fuzzy_warning = t('fuzzy_warning', lang, query=query_text, title=clean_title)

    if item['type'] == 'Мекеме':
        if "Белсенді" in item['status']:
            msg = fuzzy_warning + t('result_active', lang, title=clean_title)
        elif "аяқталған" in item['status'] or "Мерзімі" in item['status']:
            msg = fuzzy_warning + t('result_expired', lang, title=clean_title)
        elif "Қайтарып" in item['status'] or "Жойылған" in item['status']:
            msg = fuzzy_warning + t('result_revoked', lang, title=clean_title)
        else:
            msg = fuzzy_warning + t('result_unknown', lang, title=clean_title)

        if item['desc'] and item['desc'] != "Белгісіз":
            msg += t('result_manufacturer', lang, desc=item['desc'])
        msg += t('result_status', lang, status=_localize_status(item['status'], lang))

        d_start = item.get('date_start')
        d_end = item.get('date_end')
        if d_start and d_end:
            msg += t('result_validity', lang, dates=f"{d_start} - {d_end}")
        elif d_end:
            suffix = "дейін" if lang == 'kz' else f"до {d_end}"
            msg += t('result_validity', lang, dates=f"{d_end} {suffix}" if lang == 'kz' else d_end)

        keys = []
        if item.get('map_link') and "Белсенді" in item['status']:
            keys.append([{"text": t('btn_map', lang), "url": item['map_link'], "style": "primary"}])

        t_code = "c"
        keys.append([
            {"text": t('btn_good', lang), "callback_data": f"fb:good:itm:{t_code}:{item['id']}", "style": "success"},
            {"text": t('btn_bad', lang), "callback_data": f"fb:bad:itm:{t_code}:{item['id']}", "style": "danger"}
        ])
        return msg, {"inline_keyboard": keys}

    else:
        if "Рұқсат" in item['status']:
            msg = fuzzy_warning + t('result_ingredient_halal', lang, title=clean_title)
        elif "Харам" in item['status']:
            msg = fuzzy_warning + t('result_ingredient_haram', lang, title=clean_title)
        else:
            msg = fuzzy_warning + t('result_ingredient_suspicious', lang, title=clean_title)

        msg += t('result_scientific_name', lang, desc=item['desc'])
        msg += t('result_status', lang, status=_localize_status(item['status'], lang))
        if item.get('info'):
            msg += t('result_info', lang, info=strip_html(item['info']))

        keys = []
        t_code = "i"
        keys.append([
            {"text": t('btn_good', lang), "callback_data": f"fb:good:itm:{t_code}:{item['id']}", "style": "success"},
            {"text": t('btn_bad', lang), "callback_data": f"fb:bad:itm:{t_code}:{item['id']}", "style": "danger"}
        ])
        return msg, {"inline_keyboard": keys}
