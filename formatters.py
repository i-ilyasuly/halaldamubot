import uuid

def format_item_dict(data, type_name):
    if type_name == "Мекеме":
        d_start = data.get("certificate_date_start", "")
        d_end = data.get("certificate_date_end", "")
        cert_status = str(data.get("certificate_status", "active")).strip().lower()
        if cert_status == "active": st = "✅ Белсенді"
        elif cert_status == "expired": st = "❌ Мерзімі аяқталған"
        elif cert_status == "revoked": st = "🚫 Қайтарып алынған"
        else: st = f"⚠️ {cert_status}"

        # Мекеме суреті — featured_image.thumbnail өрісінен
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
        st = "✅ Рұқсат етілген" if data.get("status", {}).get("name") == "Халяль" else "🚫 Күдікті"
        item_title = data.get("title", "") or str(data.get("slug", "")).upper()
        return {
            "id": str(data.get("id", uuid.uuid4().hex[:8])),
            "type": "Қоспа",
            "title": item_title,
            "desc": data.get("name", ""),
            "info": data.get("desc", ""),
            "status": st
        }

def format_detail_message(item, confidence='exact', query_text=''):
    """
    confidence='exact'  → қалыпты хабар
    confidence='fuzzy'  → үстіне ескерту қосылады
    """
    clean_title = str(item['title']).strip('«»"\' ')

    # ── FUZZY ЕСКЕРТУІ ──────────────────────────────────────────────────────
    fuzzy_warning = ""
    if confidence == 'fuzzy':
        fuzzy_warning = (
            f"⚠️ <b>Назар аударыңыз!</b>\n"
            f"Сіз <b>«{query_text}»</b> деп іздедіңіз, бірақ базадан <b>«{clean_title}»</b> табылды — бұл ұқсас, бірақ басқа өнім болуы мүмкін.\n"
            f"Атауын нақтырақ жазып қайта көріңіз немесе суретін жіберіңіз.\n\n"
            f"<i>Төменде табылған ұқсас нәтиже:</i>\n\n"
        )

    if item['type'] == 'Мекеме':
        # Мерзімі өткен мекемеге қатаң ескерту
        if "Белсенді" in item['status']:
            msg = f"{fuzzy_warning}✅ <b>«{clean_title}»</b> — ҚМДБ Халал Даму базасында ресми тіркелген.\n\n"
        elif "аяқталған" in item['status'] or "Мерзімі" in item['status']:
            msg = (
                f"{fuzzy_warning}"
                f"🚫 <b>НАЗАР АУДАРЫҢЫЗ!</b>\n\n"
                f"<b>«{clean_title}»</b> мекемесінің халал сертификаты <b>МЕРЗІМІ ӨТІП КЕТКЕН!</b>\n\n"
                f"Бұл мекеменің қазіргі уақытта жарамды халал сертификаты жоқ. "
                f"Барар алдында мекемеден тікелей сертификаттың жаңартылғанын сұраңыз.\n\n"
            )
        elif "Қайтарып" in item['status'] or "Жойылған" in item['status']:
            msg = (
                f"{fuzzy_warning}"
                f"🚫 <b>НАЗАР АУДАРЫҢЫЗ!</b>\n\n"
                f"<b>«{clean_title}»</b> мекемесінің халал сертификаты <b>ЖОЙЫЛҒАН!</b>\n\n"
                f"Бұл мекеменің халал сертификаты ҚМДБ Халал Даму тарапынан ресми түрде жойылған.\n\n"
            )
        else:
            msg = f"{fuzzy_warning}⚠️ <b>«{clean_title}»</b> — сертификат мәртебесі белгісіз.\n\n"

        if item['desc'] and item['desc'] != "Белгісіз":
            msg += f"🏢 <b>Өндіруші:</b> {item['desc']}\n"
        msg += f"📊 <b>Статус:</b> {item['status']}\n"

        d_start = item.get('date_start')
        d_end = item.get('date_end')
        if d_start and d_end:
            msg += f"📅 <b>Жарамдылығы:</b> {d_start} - {d_end}\n"
        elif d_end:
            msg += f"📅 <b>Жарамдылығы:</b> {d_end} дейін\n"

        # Мерзімі өткенде карта батырмасын жасырамыз — адам бармас үшін
        keys = []
        if item.get('map_link') and "Белсенді" in item['status']:
            keys.append([{"text": "🗺️ Картадан көру", "url": item['map_link']}])

        t_code = "c"
        keys.append([
            {"text": "👍 Пайдалы", "callback_data": f"fb:good:itm:{t_code}:{item['id']}"},
            {"text": "👎 Қате", "callback_data": f"fb:bad:itm:{t_code}:{item['id']}"}
        ])
        return msg, {"inline_keyboard": keys}

    else:
        if "Рұқсат" in item['status']:
            msg = f"{fuzzy_warning}✅ <b>«{clean_title}»</b> — рұқсат етілген (халал) қоспа.\n\n"
        else:
            msg = f"{fuzzy_warning}🚫 <b>Назар аударыңыз:</b> <b>«{clean_title}»</b> қоспасы күдікті!\n\n"

        msg += f"🏷 <b>Ғылыми атауы:</b> {item['desc']}\n"
        msg += f"📊 <b>Статус:</b> {item['status']}"

        if item.get('info'):
            msg += f"\n\n📝 <b>Ақпарат:</b> {item['info']}"

        keys = []
        t_code = "i"
        keys.append([
            {"text": "👍 Пайдалы", "callback_data": f"fb:good:itm:{t_code}:{item['id']}"},
            {"text": "👎 Қате", "callback_data": f"fb:bad:itm:{t_code}:{item['id']}"}
        ])
        return msg, {"inline_keyboard": keys}
