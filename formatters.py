import uuid

def format_item_dict(data, type_name):
    if type_name == "Мекеме":
        d_start = data.get("certificate_date_start", "")
        d_end = data.get("certificate_date_end", "")
        cert_status = str(data.get("certificate_status", "active")).strip().lower()
        if cert_status == "active":
            st = "✅ Белсенді"
        elif cert_status == "expired":
            st = "❌ Мерзімі аяқталған"
        elif cert_status == "revoked":
            st = "🚫 Қайтарып алынған"
        else:
            st = f"⚠️ {cert_status}"
            
        return {
            "id": str(data.get("id", uuid.uuid4().hex[:8])),
            "type": "Мекеме",
            "title": data.get("title") or data.get("legal_name", "Белгісіз"),
            "desc": data.get("legal_name", ""),
            "address": data.get("address") or data.get("legal_address", "Мекенжай көрсетілмеген"),
            "map_link": data.get("map_link", ""),
            "date_start": d_start,
            "date_end": d_end,
            "status": st
        }
    else:
        st = "✅ Рұқсат етілген" if data.get("status", {}).get("name") == "Халяль" else "🚫 Күдікті"
        
        item_title = data.get("title", "")
        if not item_title:
            item_title = str(data.get("slug", "")).upper()
            
        return {
            "id": str(data.get("id", uuid.uuid4().hex[:8])),
            "type": "Қоспа",
            "title": item_title,
            "desc": data.get("name", ""),
            "info": data.get("desc", ""),
            "status": st
        }

def format_detail_message(item):
    clean_title = str(item['title']).strip('«»"\' ')
    
    if item['type'] == 'Мекеме':
        if "Белсенді" in item['status']:
            msg = f"✅ <b>«{clean_title}»</b> — ҚМДБ базасында ресми тіркелген.\n\n"
        else:
            msg = f"⚠️ <b>Назар аударыңыз:</b> <b>«{clean_title}»</b> сертификаты қазір ЖАРАМСЫЗ немесе мерзімі біткен!\n\n"
            
        if item['desc'] and item['desc'] != "Белгісіз":
            msg += f"🏢 <b>Өндіруші:</b> {item['desc']}\n"
        msg += f"📊 <b>Статус:</b> {item['status']}\n"
        
        d_start = item.get('date_start')
        d_end = item.get('date_end')
        if d_start and d_end:
            msg += f"📅 <b>Жарамдылығы:</b> {d_start} - {d_end}\n"
        elif d_end:
            msg += f"📅 <b>Жарамдылығы:</b> {d_end} дейін\n"
        
        keys = []
        if item.get('map_link'):
            keys.append([{"text": "🗺️ Картадан көру", "url": item['map_link'], "style": "primary"}])
            
        # ЖАҢА: Батырмаларға ID жалғанады!
        t_code = "c"
        keys.append([
            {"text": "👍 Пайдалы", "callback_data": f"fb:good:itm:{t_code}:{item['id']}", "style": "success"}, 
            {"text": "👎 Қате", "callback_data": f"fb:bad:itm:{t_code}:{item['id']}", "style": "danger"}
        ])
        return msg, {"inline_keyboard": keys}
        
    else:
        if "Рұқсат" in item['status']:
            msg = f"✅ <b>«{clean_title}»</b> — рұқсат етілген (халал) қоспа.\n\n"
        else:
            msg = f"🚫 <b>Назар аударыңыз:</b> <b>«{clean_title}»</b> қоспасы күдікті (рұқсат етілмеген болуы мүмкін)!\n\n"
            
        msg += f"🏷 <b>Ғылыми атауы:</b> {item['desc']}\n"
        msg += f"📊 <b>Статус:</b> {item['status']}"
        
        if item.get('info'):
            msg += f"\n\n📝 <b>Ақпарат:</b> {item['info']}"
        
        keys =[]
        t_code = "i"
        keys.append([
            {"text": "👍 Пайдалы", "callback_data": f"fb:good:itm:{t_code}:{item['id']}", "style": "success"}, 
            {"text": "👎 Қате", "callback_data": f"fb:bad:itm:{t_code}:{item['id']}", "style": "danger"}
        ])
        return msg, {"inline_keyboard": keys}
