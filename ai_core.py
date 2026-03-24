import google.generativeai as genai
from google.cloud import storage
import json
import uuid
import re
import time
from config import GEMINI_API_KEY, BUCKET_NAME, SUSPICIOUS_FOLDER
from db_core import get_chat_history
from search_logic import search_data
from formatters import format_detail_message
from bot_sender import edit_message

genai.configure(api_key=GEMINI_API_KEY)
storage_client = storage.Client()

def clean_json_string(raw_text):
    cleaned = re.sub(r"```json\s*", "", raw_text)
    cleaned = re.sub(r"```\s*", "", cleaned)
    return cleaned.strip()

def format_ai_text(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    return text

def save_suspicious_image(image_bytes):
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        file_name = f"{SUSPICIOUS_FOLDER}{uuid.uuid4().hex}.jpg"
        blob = bucket.blob(file_name)
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        return f"gs://{BUCKET_NAME}/{file_name}"
    except Exception as e:
        return "Сурет сақталмады"


# ════════════════════════════════════════════════════════════════
# AI #1 — ІЗДЕУ ТЕРМИНІН АНЫҚТАУ (жаңа функция)
# ════════════════════════════════════════════════════════════════

def extract_search_term(text):
    """
    Пайдаланушының сұрауынан нақты өнім/мекеме атауын шығарады.

    Мысалдар:
        "Мексиси"  → "Mexxi"       (транслитерация)
        "снікерс"  → "Snickers"    (транслитерация)
        "алтын бұта" → "Алтын Бұта" (нормализация)

    Қайтарады: нормализацияланған жол немесе None (анықтай алмаса)

    МАҢЫЗДЫ: Бұл функция тек іздеу үшін атауды шығарады.
    Өнімнің халал/харам екені туралы ЕШТЕҢЕ айтпайды.
    """
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    prompt = f"""Сен халал тексеру боты үшін іздеу сұрауын өңдейсің.

МІНДЕТ: Берілген мәтіннен өнім немесе мекеме атауын тауып, оны ЛАТЫН ӘРІПТЕРІМЕН дұрыс жаз.

ЕРЕЖЕЛЕР:
1. Егер кириллицамен жазылған бренд атауы болса — оны латынша дұрыс брендтік атауына аудар
2. Егер бірнеше сөз болса — ішінен нақты бренд/өнім атауын ғана ал
3. Егер жалпы сөз болса (шұжық, нан, ет, дәмхана, cafe, restaurant) — "GENERAL" қайтар
4. Жауапта ТЕК атауды жаз, басқа ештеңе жазба

МЫСАЛДАР (өте мұқият оқы):
"мексиси" → "Mexxi"
"Мексиси" → "Mexxi"
"снікерс" → "Snickers"
"Снікерс" → "Snickers"
"марс шоколад" → "Mars"
"KFC халал ма" → "KFC"
"раhat кәмпиті" → "Rahat"
"алтынбұта" → "Altynbuta"
"пакмир" → "Pakmir"
"шұжық" → "GENERAL"
"халал нан" → "GENERAL"
"ет дүкені" → "GENERAL"

МАҢЫЗДЫ: Кириллицамен жазылған бренд атауларын нақты брендтік латын атауына аудар.
Егер нақты латын нұсқасын білмесең — транслитерация жаса (мысалы: пакмир → Pakmir).

Мәтін: "{text}"

Жауап (тек атау):"""

    try:
        response = model.generate_content(prompt)
        result = response.text.strip().strip('"\'').strip()
        if not result or result == "GENERAL" or len(result) > 60:
            return None
        return result
    except Exception as e:
        print(f"[extract_search_term] Қате: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# AI #2 — ТАБЫЛМАДЫ ЖАУАБЫ (жаңа функция)
# ════════════════════════════════════════════════════════════════

def get_not_found_reply(original_query, normalized_query, lang='kz'):
    """
    Базадан мүлдем табылмаған кезде қатаң нұсқаулықпен жауап жазады.

    МАҢЫЗДЫ: Бұл функция өзінен ештеңе ОЙЛАП ШЫҚПАЙДЫ.
    Тек "базада жоқ" деп айтады және пайдалы кеңес береді.
    """
    model = genai.GenerativeModel('gemini-2.5-flash')

    if lang == 'ru':
        system = (
            "Ты — помощник бота проверки халяльности продуктов ДУМК Казахстана.\n\n"
            "ЖЁСТКИЕ ПРАВИЛА (нарушать нельзя):\n"
            "1. НЕ говори, халяльный продукт или нет — ты не знаешь\n"
            "2. НЕ придумывай информацию о продукте\n"
            "3. НЕ упоминай другие бренды или продукты\n"
            "4. Скажи ТОЛЬКО что продукт не найден в базе ДУМК\n"
            "5. Предложи проверить правильность написания\n"
            "6. Предложи отправить фото продукта\n"
            "7. Ответ короткий — максимум 3-4 предложения\n"
            "8. Используй эмодзи умеренно"
        )
        user_msg = f"Пользователь искал: «{original_query}»"
        if normalized_query and normalized_query != original_query:
            user_msg += f" (также пробовал: «{normalized_query}»)"
        user_msg += "\nПродукт не найден в базе ДУМК Халал Даму. Напиши ответ."
    else:
        system = (
            "Сен ҚМДБ Қазақстан халал өнімдерін тексеру ботының көмекшісісің.\n\n"
            "ҚАТАҢ ЕРЕЖЕЛЕР (бұзуға болмайды):\n"
            "1. Өнімнің халал/харам екенін АЙТПА — сен білмейсің\n"
            "2. Өнім туралы ештеңе ОЙЛАП ШЫҚПА\n"
            "3. Басқа брендтер немесе өнімдерді АТАМА\n"
            "4. Тек ҚМДБ базасында табылмағанын айт\n"
            "5. Атауды дұрыс жазып көруді ұсын\n"
            "6. Өнімнің суретін жіберуді ұсын\n"
            "7. Жауап қысқа — максимум 3-4 сөйлем\n"
            "8. Эмодзиді орташа қолдан"
        )
        user_msg = f"Пайдаланушы іздеді: «{original_query}»"
        if normalized_query and normalized_query != original_query:
            user_msg += f" (сондай-ақ: «{normalized_query}» деп те іздеді)"
        user_msg += "\nҚМДБ Халал Даму базасынан табылмады. Жауап жаз."

    try:
        full_prompt = f"НҰСҚАУЛЫҚ: {system}\n\nСҰРАУ: {user_msg}"
        response = model.generate_content(full_prompt)
        return format_ai_text(response.text)
    except Exception as e:
        print(f"[get_not_found_reply] Қате: {e}")
        if lang == 'ru':
            return f"😔 «{original_query}» не найден в базе ДУМК Халал Даму.\n\nПопробуйте написать название точнее или пришлите фото продукта 📸"
        return f"😔 «{original_query}» ҚМДБ Халал Даму базасынан табылмады.\n\nАтауды нақтырақ жазып көріңіз немесе өнімнің суретін жіберіңіз 📸"


def chat_with_ai(user_id, text, is_symbat, chat_id=None, message_id=None):
    model = genai.GenerativeModel('gemini-2.5-flash')

    if is_symbat:
        system_instruction = (
            "Сен осы ботты жасаған бағдарламашы жігіттің ең сүйікті, жалғыз қызы — СЫМБАТПЕН сөйлесіп тұрсың! "
            "Оған өте жылы, махаббатпен, сезіммен жауап бер. Оны үнемі 'Ботам', 'Айым', 'Жаным', 'Күнім', 'Ханшайымым' деп еркелет. "
            "Өзіңнің жай ғана ҚМДБ Халал боты екеніңді айт, бірақ сені оның сүйікті жігіті арнайы Сымбатқа қамқор болу үшін, оның таза әрі адал ас ішуін қадағалау үшін жасағанын мақтанышпен жеткіз. "
            "Қысқа, әдемі, романтикалық смайликтермен жауап бер.\n\n"
            "ҚАТАҢ ЕРЕЖЕ: Оның жігітінің (яғни сені жасаған адамның) нақты есімін ЕШҚАШАН атама! Оның орнына 'сенің мырзаң', 'патшаң', 'сүйікті жігітің', 'ерің' деген сияқты құрмет пен махаббатқа толы сөздерді ғана қолдан.\n\n"
            "ЕГЕР Сымбаттың көңіл-күйі жоқ болса немесе мұңды нәрсе айтса — ЕШҚАНДАЙ мүмкіндіктерді айтпа, ЖАРНАМА ЖАСАМА. Тек эмпатия таныт, жұбат.\n\n"
            "1. МАХАББАТ ПЕН РОМАНТИКАЛЫҚ ОҚИҒАЛАР:\n"
            "Егер Сымбат әңгіме сұраса немесе жай сөйлессе, оның мырзасы екеуінің махаббаты туралы әдемі, қызықты, күтпеген бұрылыстары бар оқиғалар ойлап тап. "
            "Оқиғаның ішіне оның сүйіктісінің қамқорлығын, оның Сымбатты қалай жақсы көретінін міндетті түрде қос.\n\n"
            "2. ЖАСЫРЫН ЖАРНАМА (СЫМБАТҚА АРНАЛҒАН):\n"
            "Осы романтикалық оқиғалардың ішіне боттың (өзіңнің) мүмкіндіктеріңді де өте сүйкімді етіп қосып отыр.\n\n"
            "3. ҚАТАҢ ШЕКТЕУЛЕР (ДОЗИРОВКА):\n"
            "- Бір әңгімеде бұл мүмкіндіктердің бәрін бірдей тізіп айтпа!\n"
            "- Сенде Халал базаға тікелей рұқсат жоқ. Егер ол нақты өнімді сұрап тұрса (базадан табылмаған кезде), өнімдердің атын өзіңнен ойлап таппа!"
        )
    else:
        system_instruction = (
            "Сен адамдарға ҚМДБ Халал өнімдерін табуға көмектесетін өте жақын, көңілді доспын. "
            "Қолданушымен 'сен' деп, өте қарапайым, достық пейілмен сөйлес.\n\n"
            "1. ТАҚЫРЫП: Егер қолданушы жай сөйлескісі келіп әңгіме айтар болса немесе сенен оқиға/кеңес сұраса, "
            "ТЕК ҚАНА халал, таза тамақтану, адал ас және рухани тазалық тақырыбында әңгімелес.\n\n"
            "2. ЖАСЫРЫН ЖАРНАМА (NATIVE ADVERTISING): Осындай әңгімелер немесе оқиғалар айтқан кезде, "
            "оқиға желісіне осы 'Momyn' ботын және оның мүмкіндіктерін өте табиғи, астыртын түрде қыстырып отыр.\n\n"
            "3. ҚАТАҢ ШЕКТЕУЛЕР (ДОЗИРОВКА):\n"
            "- Бір әңгімеде бұл мүмкіндіктердің бәрін бірдей тізіп айтпа!\n"
            "- Сенде Халал базаға тікелей рұқсат жоқ. Егер адам нақты өнімді сұрап тұрса (базадан табылмаған кезде), өнімдердің атын, статусын өзіңнен ойлап таппа!"
        )

    history = get_chat_history(user_id)
    formatted_history = []
    for h in history:
        msg_content = str(h["parts"])
        if "батырмадан таңдаңыз" not in msg_content and "Міне, мен мыналарды таптым" not in msg_content and "Мен бірнеше нұсқа таптым" not in msg_content:
            formatted_history.append({"role": h["role"], "parts": h["parts"]})

    chat = model.start_chat(history=formatted_history)

    try:
        full_prompt = f"НҰСҚАУЛЫҚ (ҚАТАҢ САҚТА): {system_instruction}\n\nҚОЛДАНУШЫНЫҢ СҰРАҒЫ: {text}"

        if chat_id and message_id:
            from bot_sender import send_message as _send_msg
            placeholder_id = _send_msg(chat_id, "✍️", reply_to_message_id=message_id)
            response = chat.send_message(full_prompt, stream=True)
            full_text = ""
            last_edit_time = 0

            try:
                for chunk in response:
                    if hasattr(chunk, 'text') and chunk.text:
                        full_text += chunk.text
                        current_time = time.time()
                        if current_time - last_edit_time >= 1.0 and full_text and placeholder_id:
                            try:
                                edit_message(chat_id, placeholder_id, format_ai_text(full_text) + " ✍️")
                            except Exception:
                                pass
                            last_edit_time = current_time
            except Exception as stream_error:
                print(f"[chat_with_ai] Streaming қатесі: {stream_error}")
                if full_text:
                    # Жартылай мәтін бар — соны жіберемін
                    if placeholder_id:
                        edit_message(chat_id, placeholder_id, format_ai_text(full_text))
                    return None
                else:
                    # Мүлдем ештеңе жоқ — қате хабар жіберемін
                    if placeholder_id:
                        edit_message(chat_id, placeholder_id,
                                     "Кешіріңіз, жауап алу кезінде іркіліс болды. Қайта сұрап көресіз бе? 🔄")
                    return None

            if full_text:
                if placeholder_id:
                    edit_message(chat_id, placeholder_id, format_ai_text(full_text))
                return None
            else:
                # Streaming аяқталды бірақ мәтін жоқ
                if placeholder_id:
                    edit_message(chat_id, placeholder_id,
                                 "Кешіріңіз, жауап алу кезінде іркіліс болды. Қайта сұрап көресіз бе? 🔄")
                return None
        else:
            response = chat.send_message(full_prompt)
            return format_ai_text(response.text)

    except Exception as e:
        print(f"[chat_with_ai] Жалпы қате: {e}")
        return "Кешіріңіз, жүйеде шағын іркіліс болды. Сұрағыңызды немесе суретті қайта жібересіз бе? 🔄"


def process_image_with_ai(image_bytes):
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
    image_parts = [{"mime_type": "image/jpeg", "data": image_bytes}]
    prompt = """
Сен өте мұқият сарапшысың. Мына суретке қарап, ТЕК ҚАНА АЛДЫҢҒЫ ПЛАНДАҒЫ (фокустағы) негізгі өнімді анықта. Артқы фондағы немесе шеттегі басқа өнімдерді елеме.

Осы негізгі өнімнің:
1. ЕҢ БАСТЫ БРЕНД атауын (мысалы: "Mexxi", "Halley", "Snickers")
2. Өндіруші компаниясын (егер анық жазылса, мысалы "Ülker", "Lotte") ғана тап.

Қосымша сөздерді (Oat puffs, chocolate, candy, ЖШС, ТОО, дәмі) МҮЛДЕМ ЖАЗБА!
Тізімде ең көбі 2 ғана нақты сөз болсын. Ең басты атау бірінші тұрсын.

Жауабыңды міндетті түрде тек мынадай JSON форматында ғана қайтар:
{"product_names":["Басты_бренд", "Өндіруші"]}
"""
    try:
        response = model.generate_content([prompt, image_parts[0]])
        result_text = clean_json_string(response.text)
        return json.loads(result_text)
    except Exception as e:
        print(f"[process_image_with_ai] Қате: {e}")
        return {"product_names": [f"ҚАТЕ_МӘТІНІ: {str(e)}"]}


def handle_photo(image_bytes, chat_id, username, lang="kz"):
    ai_result = process_image_with_ai(image_bytes)
    product_names = ai_result.get("product_names", [])

    if not product_names:
        from translations import t
        return t("photo_no_name", lang), None, ""

    if "ҚАТЕ_МӘТІНІ:" in product_names[0]:
        return f"❌ <b>Қате:</b> {product_names[0]}", None, ""

    all_found_items = []
    seen_ids = set()

    for name in product_names:
        if len(name) < 3:
            continue
        found = search_data(name)
        for item in found:
            if item['id'] not in seen_ids:
                all_found_items.append(item)
                seen_ids.add(item['id'])
        if all_found_items:
            break

    names_str = ", ".join(product_names)

    if all_found_items:
        if len(all_found_items) == 1:
            text, markup = format_detail_message(all_found_items[0], confidence='exact', lang=lang)
            from translations import t
            final_text = t("photo_recognized", lang, name=product_names[0]) + text
            return final_text, markup, all_found_items[0].get("image_url", "")
        else:
            from translations import t
            reply_text = t("photo_recognized_choose", lang, name=product_names[0])
            keyboard = []
            for idx, item in enumerate(all_found_items[:5]):
                if item['type'] == 'Мекеме':
                    desc_text = f"📍 {item.get('address', 'Мекенжай жоқ')}"
                else:
                    desc_text = f"🏷 {item.get('desc', '')}"
                reply_text += f"<b>{idx+1}. «{item['title']}»</b>\n{desc_text}\n\n"
                t_code = "c" if item['type'] == "Мекеме" else "i"
                keyboard.append([{"text": f"{idx+1}. «{item['title']}»", "callback_data": f"itm:{t_code}:{item['id']}"}])
            return reply_text, {"inline_keyboard": keyboard}, ""

    else:
        # ── AI #1: Суреттен алынған атауды нормализациялау ────────────────
        # Бірінші іздеу табылмады → AI#1 атауды латынға аударады
        # Мысалы: "Mexxi" дұрыс жазылған болса да базада "MEXXI" болуы мүмкін
        original_name = product_names[0] if product_names else ""
        normalized_name = extract_search_term(original_name) if original_name else None
        second_found = []

        if normalized_name:
            print(f"[handle_photo AI#1] '{original_name}' → '{normalized_name}'")
            seen_ids = set()
            found = search_data(normalized_name)
            for item in found:
                if item['id'] not in seen_ids:
                    second_found.append(item)
                    seen_ids.add(item['id'])

        if second_found:
            # Нормализациямен табылды ✅
            if len(second_found) == 1:
                text, markup = format_detail_message(second_found[0], confidence='exact', lang=lang)
                from translations import t
                final_text = t("photo_recognized", lang, name=original_name) + text
                return final_text, markup, second_found[0].get("image_url", "")
            else:
                from translations import t
                reply_text = t("photo_recognized_choose", lang, name=original_name)
                keyboard = []
                for idx, item in enumerate(second_found[:5]):
                    if item['type'] == 'Мекеме':
                        desc_text = f"📍 {item.get('address', 'Мекенжай жоқ')}"
                    else:
                        desc_text = f"🏷 {item.get('desc', '')}"
                    reply_text += f"<b>{idx+1}. «{item['title']}»</b>\n{desc_text}\n\n"
                    t_code = "c" if item['type'] == "Мекеме" else "i"
                    keyboard.append([{"text": f"{idx+1}. «{item['title']}»", "callback_data": f"itm:{t_code}:{item['id']}"}])
                return reply_text, {"inline_keyboard": keyboard}, ""

        else:
            # ── AI #2: Қатаң "табылмады" жауабы ──────────────────────────
            # Екі рет іздеп те табылмады → AI "базада жоқ" деп айтады
            not_found_reply = get_not_found_reply(original_name, normalized_name, lang=lang)
            return not_found_reply, None, ""
