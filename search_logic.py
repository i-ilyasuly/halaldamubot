import re
import math
from thefuzz import fuzz
from db_core import CACHE, load_cache
from formatters import format_item_dict

def clean_text(text):
    text = str(text).lower()
    replacements = {'ü': 'u', 'ö': 'o', 'ş': 'sh', 'ç': 'ch', 'ğ': 'g', 'ı': 'i',
                    'ә': 'a', 'і': 'i', 'ң': 'n', 'ғ': 'g', 'ү': 'u', 'ұ': 'u',
                    'қ': 'q', 'ө': 'o', 'һ': 'h'}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return re.sub(r'[\W\_]+', '', text)

def get_variants(text):
    text = text.lower()
    cyr2lat = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
               'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
               'с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'c','ч':'ch','ш':'sh','щ':'sh',
               'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya','қ':'q'}
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
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def get_nearby_companies(user_lat, user_lon, page=1, lang="kz"):
    load_cache()
    nearby = []
    for c in CACHE["companies"]:
        link = c.get("map_link", "")
        coords = extract_coords(link)
        if coords:
            c_lat, c_lon = coords
            dist = get_distance(user_lat, user_lon, c_lat, c_lon)
            if dist <= 10:
                cat = ""
                raw_cat = c.get("categories") or c.get("category", "")
                if isinstance(raw_cat, list) and raw_cat:
                    cat = raw_cat[0].get("name", "") if isinstance(raw_cat[0], dict) else str(raw_cat[0])
                elif isinstance(raw_cat, dict):
                    cat = raw_cat.get("name", "")
                elif isinstance(raw_cat, str):
                    cat = raw_cat
                if not cat: cat = "Тамақтану орындары / Мекеме"
                address = c.get("address", "") or c.get("legal_address", "Мекенжай көрсетілмеген")
                nearby.append({
                    "title": c.get("title") or c.get("legal_name", "Белгісіз"),
                    "category": cat, "address": address, "link": link, "dist": dist,
                    "date_start": c.get("certificate_date_start", ""),
                    "date_end": c.get("certificate_date_end", ""),
                    "status": c.get("certificate_status", "active")
                })

    nearby.sort(key=lambda x: x["dist"])
    total_items = len(nearby)
    if total_items == 0:
        from translations import t
        return t("location_not_found", lang), None

    per_page = 3
    total_pages = math.ceil(total_items / per_page)
    if page > total_pages: page = 1
    start_idx = (page - 1) * per_page
    items_to_show = nearby[start_idx:start_idx + per_page]

    from translations import t
    text = t("location_header", lang, page=page, total_pages=total_pages, total=total_items)
    inline_keyboard = []

    for idx, item in enumerate(items_to_show, start=start_idx + 1):
        dist_str = f"{item['dist']:.2f} км" if item['dist'] >= 1 else f"{int(item['dist']*1000)} м"
        clean_title = str(item['title']).strip('«»"\' ')
        cert_status = str(item['status']).strip().lower()
        if cert_status == "active": st = "✅ Белсенді"
        elif cert_status == "expired": st = "❌ Мерзімі аяқталған"
        elif cert_status == "revoked": st = "🚫 Қайтарып алынған"
        else: st = f"⚠️ {cert_status}"
        d_start, d_end = item['date_start'], item['date_end']
        date_str = f"\n    📅 {d_start} - {d_end}" if d_start and d_end else (f"\n    📅 {d_end} дейін" if d_end else "")
        icon = "✅" if "Белсенді" in st else "⚠️"
        text += f"{icon} <b>{idx}. «{clean_title}»</b>\n    🏷 {item['category']}\n    📍 {item['address']}\n    📏 {dist_str}\n    📊 {st}{date_str}\n\n"
        if cert_status == "active": btn_style = "success"
        elif cert_status in ("expired", "revoked"): btn_style = "danger"
        else: btn_style = "primary"
        inline_keyboard.append([{"text": f"🗺️ {idx}. «{clean_title}»", "url": item['link'], "style": btn_style}])

    nav_buttons = []
    if page > 1: nav_buttons.append({"text": t("btn_back", lang), "callback_data": f"loc:{page-1}:{round(user_lat,4)}:{round(user_lon,4)}", "style": "primary"})
    if page < total_pages: nav_buttons.append({"text": t("btn_next", lang), "callback_data": f"loc:{page+1}:{round(user_lat,4)}:{round(user_lon,4)}", "style": "primary"})
    if nav_buttons: inline_keyboard.append(nav_buttons)
    return text, {"inline_keyboard": inline_keyboard}


# ════════════════════════════════════════════════════════════════
# E-КОД ФУНКЦИЯЛАРЫ — ДИАПАЗОН ҚОЛДАУЫМЕН
# ════════════════════════════════════════════════════════════════

def parse_e_code(query_text):
    normalized = query_text.replace('Е', 'E').replace('е', 'e')
    match = re.search(r'[eE]\s*[-_]?\s*(\d{2,4})\s*\(?([a-zA-Z])?\)?', normalized)
    if match:
        base = 'e' + match.group(1).lower()
        variant = match.group(2).lower() if match.group(2) else None
        return base, variant
    return None, None


def e_variant_in_range(variant, title_raw):
    if not variant:
        return True
    range_match = re.search(r'\(([a-zA-Z])-([a-zA-Z])\)', title_raw)
    if range_match:
        start = range_match.group(1).lower()
        end = range_match.group(2).lower()
        return start <= variant.lower() <= end
    single_match = re.search(r'\d+([a-zA-Z])\s*$', title_raw.strip())
    if single_match:
        return single_match.group(1).lower() == variant.lower()
    return False


def _is_substring_match(query_clean, title_clean):
    """
    Substring сәйкестігін тексереді.

    Мәселе: "emil" in "demilune" → TRUE болады, бірақ бұл жалған сәйкестік.
    Шешім: Substring болса да, екі шарттың біреуі орындалуы керек:
      1. Title query-мен БАСТАЛСА (brand атауы дәл сәйкес)
      2. Query title ұзындығының 60%+ жапса (аты ұқсас)
    Болмаса — fuzzy деп белгілейміз, ескерту шығады.
    """
    if query_clean not in title_clean:
        return 'none'

    # 1. Title query-мен басталса — нақты сәйкестік
    # Мысалы: query="pakmir", title="pakmirstore" → exact ✅
    if title_clean.startswith(query_clean):
        return 'exact'

    # 2. Query title-дің 60%+ жапса — нақты сәйкестік
    # Мысалы: query="snickers" (8), title="snickers" (8) → 100% → exact ✅
    # Мысалы: query="emil" (4), title="demilune" (8) → 50% < 60% → fuzzy ✅
    coverage = len(query_clean) / len(title_clean)
    if coverage >= 0.6:
        return 'exact'

    # Substring бар бірақ аз жапты — күдікті нәтиже
    return 'fuzzy'


def _is_match(query_text, title):
    """
    Confidence деңгейін анықтайды: 'exact' | 'fuzzy' | 'none'
    """
    if not title or not query_text:
        return 'none'

    variants = get_variants(query_text)
    t_clean = clean_text(title)

    # ── 1. ТІКЕЛЕЙ SUBSTRING ТЕКСЕРУ ─────────────────────────────────────
    for var in variants:
        v_clean = clean_text(var)
        if len(v_clean) > 3:
            result = _is_substring_match(v_clean, t_clean)
            if result != 'none':
                return result

        # Partial ratio — аударылған нұсқамен
        if fuzz.partial_ratio(var, title.lower()) > 80:
            return 'exact'

    # ── 2. СӨЗ БОЙЫНША ТЕКСЕРУ ───────────────────────────────────────────
    stop_words = {'халал', 'харам', 'рұқсат', 'ма', 'ме', 'ба', 'бе', 'па', 'пе',
                  'деген', 'қандай', 'осы', 'точно', 'күдікті', 'емес',
                  'өнім', 'оним', 'onim', 'тамақ', 'азық', 'дүкен', 'дукен',
                  'мекеме', 'өндіруші', 'сұрайын', 'айтшы', 'білгім', 'келеді',
                  'жолы', 'бұлай', 'деген', 'жазады', 'жазды', 'сенен', 'маған'}
    raw_words = query_text.lower().replace('-', ' ').split()
    words = [w for w in raw_words if len(w) > 3 and w not in stop_words]

    for word in words:
        w_variants = get_variants(word)
        for w_var in w_variants:
            w_clean = clean_text(w_var)
            if len(w_clean) > 3:
                result = _is_substring_match(w_clean, t_clean)
                if result != 'none':
                    return result
            if fuzz.partial_ratio(w_var, title.lower()) > 80:
                return 'exact'

    # ── 3. ЖАЛПЫ ҰҚСАСТЫҚ (ratio) ────────────────────────────────────────
    for var in variants:
        v_clean = clean_text(var)
        r = fuzz.ratio(v_clean, t_clean)
        if r >= 85: return 'exact'
        if r >= 72: return 'fuzzy'

    for word in words:
        w_variants = get_variants(word)
        for w_var in w_variants:
            w_clean = clean_text(w_var)
            if len(w_clean) >= 4:
                r = fuzz.ratio(w_clean, t_clean)
                if r >= 83: return 'exact'
                if r >= 70: return 'fuzzy'

    return 'none'


def search_data(query_text):
    load_cache()
    results = []

    # ── E-КОД ІЗДЕУ ───────────────────────────────────────────────────────
    e_base, e_variant = parse_e_code(query_text)
    if e_base:
        for i in CACHE["ingredients"]:
            title = i.get("title", "") or ""
            name = i.get("name", "") or ""
            title_norm = clean_text(title).replace('е', 'e')
            name_norm = clean_text(name).replace('е', 'e')
            base_in_title = len(e_base) > 2 and e_base in title_norm
            base_in_name = len(e_base) > 2 and e_base in name_norm
            if base_in_title or base_in_name:
                if e_variant_in_range(e_variant, title):
                    item = format_item_dict(i, "Қоспа")
                    item['confidence'] = 'exact'
                    results.append(item)
        if results:
            return results

    # ── МЕКЕМЕЛЕР ІЗДЕУ ───────────────────────────────────────────────────
    for c in CACHE["companies"]:
        title = c.get("title", "") or ""
        legal = c.get("legal_name", "") or ""
        search_field = title if title else legal
        if not search_field:
            continue
        confidence = _is_match(query_text, search_field)
        if confidence != 'none':
            item = format_item_dict(c, "Мекеме")
            item['confidence'] = confidence
            results.append(item)
            if len(results) >= 20:
                break

    # ── ҚОСПАЛАР ІЗДЕУ ───────────────────────────────────────────────────
    for i in CACHE["ingredients"]:
        title = i.get("title", "") or ""
        name = i.get("name", "") or ""
        conf_title = _is_match(query_text, title) if title else 'none'
        conf_name = _is_match(query_text, name) if name else 'none'

        if conf_title == 'exact' or conf_name == 'exact':
            confidence = 'exact'
        elif conf_title == 'fuzzy' or conf_name == 'fuzzy':
            confidence = 'fuzzy'
        else:
            continue

        if not any(r.get("title") == title for r in results):
            item = format_item_dict(i, "Қоспа")
            item['confidence'] = confidence
            results.append(item)

        if len(results) >= 20:
            break

    results.sort(key=lambda x: 0 if x.get('confidence') == 'exact' else 1)
    return results
