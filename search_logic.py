import re
import math
from thefuzz import fuzz
from db_core import CACHE, load_cache
from formatters import format_item_dict

def clean_text(text):
    text = str(text).lower()
    replacements = {'ü': 'u', 'ö': 'o', 'ş': 'sh', 'ç': 'ch', 'ğ': 'g', 'ı': 'i', 'ә': 'a', 'і': 'i', 'ң': 'n', 'ғ': 'g', 'ү': 'u', 'ұ': 'u', 'қ': 'q', 'ө': 'o', 'һ': 'h'}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return re.sub(r'[\W_]+', '', text)

def get_variants(text):
    text = text.lower()
    cyr2lat = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'c','ч':'ch','ш':'sh','щ':'sh','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya','қ':'q'}
    latin_variant = "".join([cyr2lat.get(c, c) for c in text])
    return [text, latin_variant]

def extract_coords(link):
    if not isinstance(link, str): return None
    nums = re.findall(r'-?\d{2,}\.\d+', link)
    if len(nums) >= 2:
        n1, n2 = float(nums[0]), float(nums[1])
        if 40 <= n1 <= 55 and 46 <= n2 <= 88: return n1, n2
        if 40 <= n2 <= 55 and 46 <= n1 <= 88: return n2, n1
    return None

def get_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_nearby_companies(user_lat, user_lon, page=1):
    load_cache()
    nearby = []
    for c in CACHE["companies"]:
        link = c.get("map_link", "")
        coords = extract_coords(link)
        if coords:
            c_lat, c_lon = coords
            dist = get_distance(user_lat, user_lon, c_lat, c_lon)
            if dist <= 50:
                cat = c.get("category", "")
                if isinstance(cat, dict): cat = cat.get("name", "Санат көрсетілмеген")
                if not cat: cat = "Тамақтану орындары / Мекеме"
                address = c.get("address", "")
                if not address: address = c.get("legal_address", "Мекенжай көрсетілмеген")
                
                d_start = c.get("certificate_date_start", "")
                d_end = c.get("certificate_date_end", "")
                c_status = c.get("certificate_status", "active")
                
                nearby.append({
                    "title": c.get("title") or c.get("legal_name", "Белгісіз"),
                    "category": cat, 
                    "address": address, 
                    "link": link, 
                    "dist": dist,
                    "date_start": d_start,
                    "date_end": d_end,
                    "status": c_status
                })
                
    nearby.sort(key=lambda x: x["dist"])
    total_items = len(nearby)
    if total_items == 0:
        return "😔 Өкінішке орай, 50 км радиуста сертификаты бар халал орындар табылмады. Басқа аумақты тексеріп көресіз бе?", None
        
    per_page = 3
    total_pages = math.ceil(total_items / per_page)
    if page > total_pages: page = 1
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    items_to_show = nearby[start_idx:end_idx]
    
    text = f"📍 <b>Сенің жаныңдағы халал мекемелер:</b>\n📄 {page}/{total_pages} бет ({total_items} мекеме)\n\n"
    inline_keyboard =[]
    
    for idx, item in enumerate(items_to_show, start=start_idx + 1):
        dist_str = f"{item['dist']:.2f} км" if item['dist'] >= 1 else f"{int(item['dist']*1000)} м"
        clean_title = str(item['title']).strip('«»"\' ')
        
        cert_status = str(item['status']).strip().lower()
        if cert_status == "active":
            st = "✅ Белсенді"
        elif cert_status == "expired":
            st = "❌ Мерзімі аяқталған"
        elif cert_status == "revoked":
            st = "🚫 Қайтарып алынған"
        else:
            st = f"⚠️ {cert_status}"
            
        d_start = item['date_start']
        d_end = item['date_end']
        date_str = ""
        if d_start and d_end:
            date_str = f"\n   📅 {d_start} - {d_end}"
        elif d_end:
            date_str = f"\n   📅 {d_end} дейін"

        icon = "✅" if "Белсенді" in st else "⚠️"
        
        text += f"{icon} <b>{idx}. «{clean_title}»</b>\n   🏷 {item['category']}\n   📍 {item['address']}\n   📏 {dist_str}\n   📊 {st}{date_str}\n\n"
        
        inline_keyboard.append([{"text": f"🗺️ {idx}. «{clean_title}»", "url": item['link']}])
        
    nav_buttons =[]
    if page > 1: nav_buttons.append({"text": "⬅️ Артқа", "callback_data": f"loc:{page-1}:{round(user_lat,4)}:{round(user_lon,4)}"})
    if page < total_pages: nav_buttons.append({"text": "Келесі ➡️", "callback_data": f"loc:{page+1}:{round(user_lat,4)}:{round(user_lon,4)}"})
    if nav_buttons: inline_keyboard.append(nav_buttons)
        
    return text, {"inline_keyboard": inline_keyboard}

def search_e_code(query_text):
    match = re.search(r'[eе]\s*[-_]?\s*\d{2,4}[a-zа-я]?', query_text.lower())
    if match: return clean_text(match.group(0))
    return None

def search_data(query_text):
    load_cache()
    results =[]
    
    e_code = search_e_code(query_text)
    if e_code:
        e_variants = get_variants(e_code)
        for i in CACHE["ingredients"]:
            title = i.get("title", "")
            name = i.get("name", "")
            t_clean, n_clean = clean_text(title), clean_text(name)
            
            for e_var in e_variants:
                e_clean = clean_text(e_var)
                if (e_clean in t_clean and len(e_clean)>2) or (e_clean in n_clean and len(e_clean)>2):
                    results.append(format_item_dict(i, "Қоспа"))
                    break 
        if results: return results

    stop_words =['халал', 'харам', 'рұқсат', 'ма', 'ме', 'ба', 'бе', 'па', 'пе', 'деген', 'қандай', 'осы', 'точно', 'күдікті', 'емес']
    raw_words = query_text.lower().replace('-', ' ').split()
    words =[w for w in raw_words if len(w) > 3 and w not in stop_words]
    
    variants = get_variants(query_text)
    
    for c in CACHE["companies"]:
        title = c.get("title", "")
        legal = c.get("legal_name", "")
        t_clean, l_clean = clean_text(title), clean_text(legal)
        
        is_match = False
        for var in variants:
            v_clean = clean_text(var)
            if (v_clean in t_clean and len(v_clean)>3) or (v_clean in l_clean and len(v_clean)>3): is_match = True; break
            if fuzz.partial_ratio(var, title.lower()) > 80 or fuzz.partial_ratio(var, legal.lower()) > 80: is_match = True; break
        
        if not is_match and words:
            for word in words:
                w_variants = get_variants(word)
                for w_var in w_variants:
                    w_clean = clean_text(w_var)
                    if (w_clean in t_clean and len(w_clean) > 3) or (w_clean in l_clean and len(w_clean) > 3):
                        is_match = True; break
                if is_match: break
                
        if is_match:
            results.append(format_item_dict(c, "Мекеме"))
            if len(results) >= 20: break
            
    for i in CACHE["ingredients"]:
        title = i.get("title", "")
        name = i.get("name", "")
        t_clean, n_clean = clean_text(title), clean_text(name)
        
        is_match = False
        for var in variants:
            v_clean = clean_text(var)
            if (v_clean in t_clean and len(v_clean)>3) or (v_clean in n_clean and len(v_clean)>3): is_match = True; break
            if fuzz.partial_ratio(var, title.lower()) > 80 or fuzz.partial_ratio(var, name.lower()) > 80: is_match = True; break
        
        if not is_match and words:
            for word in words:
                w_variants = get_variants(word)
                for w_var in w_variants:
                    w_clean = clean_text(w_var)
                    if (w_clean in t_clean and len(w_clean) > 3) or (w_clean in n_clean and len(w_clean) > 3):
                        is_match = True; break
                if is_match: break
                
        if is_match:
            if not any(r.get("title") == title for r in results):
                results.append(format_item_dict(i, "Қоспа"))
            if len(results) >= 20: break
            
    return results
