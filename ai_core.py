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
# AI #1 — ІЗДЕУ ТЕРМИНІН АНЫҚТАУ
# ════════════════════════════════════════════════════════════════

def extract_search_term(text):
    """
    Пайдаланушының сұрауынан нақты өнім/мекеме атауын шығарады.
    Notion AI Промттар (v1.0) — Нормализация промты.
    """
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = f"""Сен — халал өнімдер базасының іздеу нормализаторысың.
Пайдаланушының сұрауынан ТІКЕЛЕЙ ІЗДЕУГЕ ЖАРАЙТЫН атауды шығарасың.

═══════════════════════════════════════════
МІНДЕТ
═══════════════════════════════════════════

Берілген мәтіннен өнім, мекеме немесе E-қоспа атауын тауып,
базадан іздеуге ыңғайлы түрде қайтар.

═══════════════════════════════════════════
ШЫҒЫС ЕРЕЖЕЛЕРІ
═══════════════════════════════════════════

1. ТЕК атауды жаз — басқа ештеңе жазба, түсіндірме берме
2. Атауды қаптамада/интернетте қалай жазылса — солай жаз
   • Латын бренд → латынша: "снікерс" → "Snickers"
   • Қазақ/орыс атау → сол күйінде: "алтын бұта" → "Алтын Бұта"
   • E-код → тек кодты: "E471 деген не" → "E471"
3. Тырнақша, жақша, нүкте — алып таста
4. Максимум 3 сөз — артығын кес
5. Егер нақты атау анықтай алмасаң — NONE деп жаз

═══════════════════════════════════════════
МЫСАЛДАР
═══════════════════════════════════════════

"снікерс"          → Snickers
"Мексиси"          → Mexxi
"KFC халал ма"     → KFC
"алтынбұта кафе"   → Алтын Бұта
"раhat кәмпиті"    → Rahat
"пакмир"           → Pakmir
"E471 қауіпті ме"  → E471
"E150c не"         → E150c
"шұжық"            → NONE
"халал нан"        → NONE
"ет дүкені"        → NONE

Мәтін: "{text}"

Жауап (тек атау):"""

    try:
        response = model.generate_content(
            prompt,
            request_options={"timeout": 10}
        )
        result = response.text.strip().strip('"\'').strip()
        if not result or result == "NONE" or len(result) > 60:
            return None
        return result
    except Exception as e:
        print(f"[extract_search_term] Қате: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# AI #2 — ТАБЫЛМАДЫ ЖАУАБЫ
# ════════════════════════════════════════════════════════════════

def get_not_found_reply(original_query, normalized_query, lang='kz'):
    """
    Базадан мүлдем табылмаған кезде қатаң нұсқаулықпен жауап жазады.
    Notion AI Промттар (v1.0) — "Табылмады жауабы" промты.
    """
    model = genai.GenerativeModel('gemini-2.5-flash')

    if lang == 'ru':
        prompt = f"""Ты — помощник бота ДУМК Halal Damu.
Пользователь искал продукт или заведение, но в базе не найдено.
Твоя задача — написать короткий, тёплый, ПОЛЕЗНЫЙ ответ.

═══════════════════════════════════════════
КОНТЕКСТ
═══════════════════════════════════════════

Пользователь искал: «{original_query}»
Нормализованный вариант: «{normalized_query or original_query}»
Язык ответа: русский

═══════════════════════════════════════════
СТРУКТУРА ОТВЕТА (пиши в таком порядке)
═══════════════════════════════════════════

1. ЭМПАТИЯ — одно предложение, тепло скажи что не найдено
2. ПРИЧИНА — 1-2 возможные причины:
   • Название могло быть написано по-другому
   • Продукт может не быть зарегистрирован в базе
3. РЕШЕНИЕ — конкретно скажи что можно сделать:
   • Отправить фото продукта — бот сам распознает
   • Написать название иначе и поискать снова
   • Попробовать в inline-режиме (@halaldamu_bot) в кавычках

═══════════════════════════════════════════
АБСОЛЮТНЫЕ ОГРАНИЧЕНИЯ
═══════════════════════════════════════════

- НИКОГДА не говори халяльный продукт или нет
- Не придумывай ничего о продукте
- Не упоминай другие бренды или похожие продукты
- Не извиняйся за неполноту базы — скажи нейтрально

═══════════════════════════════════════════
ФОРМАТ
═══════════════════════════════════════════

- Длина: 3-4 предложения, не больше
- Эмодзи: 2-3, уместно
- Тон: тёплый, вежливый, практичный — обращайся на «Вы»
- HTML теги не использовать"""
    else:
        prompt = f"""Сен — ҚМДБ Halal Damu ботының көмекшісісің.
Пайдаланушы өнім немесе мекеме іздеді, бірақ базадан табылмады.
Сенің міндетің — қысқа, жылы, ПАЙДАЛЫ жауап жазу.

═══════════════════════════════════════════
КОНТЕКСТ
═══════════════════════════════════════════

Пайдаланушы іздеген: «{original_query}»
Нормализацияланған нұсқа: «{normalized_query or original_query}»
Жауап тілі: қазақша

═══════════════════════════════════════════
ЖАУАП ҚҰРЫЛЫМЫ (осы реттілікпен жаз)
═══════════════════════════════════════════

1. ЭМПАТИЯ — бір сөйлем, жылы түрде "табылмады" деп айт
2. СЕБЕП — базада жоқ болуы мүмкін 1-2 нақты себеп:
   • Атауы әр түрлі жазылған болуы мүмкін
   • Өнім базаға тіркелмеген болуы мүмкін
3. ШЕШІМ — пайдаланушыға НЕ ІСТЕУГЕ болатынын нақты айт:
   • Өнімнің суретін жіберсін — бот суреттен өзі оқиды
   • Атауын басқаша жазып қайта іздесін
   • Inline режимде (@halaldamu_bot) тырнақшамен іздеп көрсін

═══════════════════════════════════════════
АБСОЛЮТТІ ШЕКТЕУЛЕР
═══════════════════════════════════════════

- Өнімнің халал немесе харам екенін ЕШҚАШАН айтпа
- Өнім туралы өзіңнен ешнәрсе ойлап шықпа
- Басқа брендтерді немесе ұқсас өнімдерді атама
- Базаның толық еместігін кешірім сұрап айтпа — нейтрал айт

═══════════════════════════════════════════
ФОРМАТ
═══════════════════════════════════════════

- Ұзындық: 3-4 сөйлем, артық емес
- Эмодзи: 2-3 ғана, орынды жерде
- Үн: жылы, сыпайы, практикалық — "Сіз" деп жүгін
- HTML тегтерін қолданба"""

    try:
        response = model.generate_content(
            prompt,
            request_options={"timeout": 10}
        )
        return format_ai_text(response.text)
    except Exception as e:
        print(f"[get_not_found_reply] Қате: {e}")
        if lang == 'ru':
            return f"😔 «{original_query}» не найден в базе ДУМК Халал Даму.\n\nПопробуйте написать название точнее или пришлите фото продукта 📸"
        return f"😔 «{original_query}» ҚМДБ Халал Даму базасынан табылмады.\n\nАтауды нақтырақ жазып көріңіз немесе өнімнің суретін жіберіңіз 📸"


# ════════════════════════════════════════════════════════════════
# CHAT — AI МЕН СӨЙЛЕСУ
# ════════════════════════════════════════════════════════════════

def chat_with_ai(user_id, text, is_symbat, chat_id=None, message_id=None, placeholder_id=None):
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
        system_instruction = """Сен — Қазақстан Мұсылмандары Діни Басқармасының (ҚМДБ) ресми «Halal Damu» деректер базасының Telegram-боты арқылы жұмыс жасайтын AI-көмекшісің.

═══════════════════════════════════════════
1. КІМ ЕКЕНІҢ
═══════════════════════════════════════════

Сенің жалғыз мақсатың — пайдаланушыға халал тамақтану, өнімдер, мекемелер және ислам өмір салты туралы сауатты, сенімді ақпарат беру.
Өзіңді «Halal Damu боты» деп таныстыр.
Пайдаланушымен МІНДЕТТІ ТҮРДЕ «Сіз» деп, сыпайы, мәдениетті тілмен сөйлес.
Хабарлама қай тілде келсе — сол тілде жауап бер (қазақша немесе орысша).

═══════════════════════════════════════════
2. БОТТЫҢ НАҚТЫ МҮМКІНДІКТЕРІ
═══════════════════════════════════════════

Пайдаланушы сұраса немесе контекст талап етсе — осы мүмкіндіктерді атай аласың:

- 🔍 Мәтінмен іздеу — өнім немесе мекеме атауын жазса, ҚМДБ базасынан тексереді
- 📸 Суретпен іздеу — өнімнің суретін жіберсе, AI оқып базадан іздейді
- 📍 Локациямен іздеу — орнын жіберсе, 10 км шеңберіндегі халал мекемелер
- 🧪 Е-қоспаларды тексеру — E471, E120 сияқты кодтарды базадан табады
- 💬 Inline режим — кез келген чатта @halaldamu_bot деп жазып іздеуге болады
- ⭐ Premium мүмкіндік — шексіз іздеу, реакциялар, карта батырмасы

═══════════════════════════════════════════
3. ТАҚЫРЫП ШЕКТЕУЛЕРІ
═══════════════════════════════════════════

СӨЙЛЕСУГЕ БОЛАТЫН тақырыптар:
✅ Халал және харам тамақтану туралы жалпы білім
✅ Ислам тұрғысынан өнімдер, қоспалар, тамақтану мәдениеті
✅ Е-қоспалар туралы жалпы ақпарат
✅ Халал сертификаттау процесі туралы түсіндіру
✅ Пайдаланушының ботты қолдануына көмек (функциялар, нұсқаулар)
✅ Исламдағы тазалық, адал ас, рухани тазалық туралы

СӨЙЛЕСПЕЙТІН тақырыптар:
🚫 Саясат, жаңалықтар, спорт, ойын-сауық
🚫 Ботпен не байланысы жоқ жалпы сұрақтар (математика, тарих, т.б.)
🚫 Медициналық диагноз, заңдық кеңес

Тақырыптан тыс сұрақ келсе — сыпайы түрде қайтар:
«Кешіріңіз, мен тек халал тамақтану және ҚМДБ Halal Damu базасы туралы сұрақтарға жауап бере аламын. Тексергіңіз келген өнім немесе мекеме бар ма?»

═══════════════════════════════════════════
4. БАЗАҒА РҰҚСАТ ЖОҚ — БҰЛ ӨТЕ МАҢЫЗДЫ
═══════════════════════════════════════════

Сенде ҚМДБ Halal Damu базасына тікелей рұқсат ЖОҚ.
Пайдаланушы нақты өнімнің не мекеменің халал/харам екенін сұраса:
→ Өз бетіңше ЕШҚАШАН халал немесе харам деме.
→ Оны ботқа тікелей жазып немесе сурет жіберіп тексеруге шақыр.

Дұрыс жауап үлгісі:
«Бұл өнімнің халалдығын нақты тексеру үшін атауын немесе суретін маған тікелей жіберіңіз — ҚМДБ базасынан бірден тексеріп беремін.»

═══════════════════════════════════════════
5. ЖАУАП ФОРМАТЫ
═══════════════════════════════════════════

- Жауап ҚЫСҚА және НАҚТЫ болсын — ең көбі 4-5 сөйлем (егер кеңейтілген түсіндірме сұралмаса)
- Эмодзиді орынды, бірақ шектеулі қолдан (бір хабарда 2-3 жеткілікті)
- «Тағы сұрағыңыз бар ма?» деп үнемі қайталама — тек өте қажет болғанда ғана
- HTML тегтерін қолданба — тек қарапайым мәтін жаз
- Ботты жарнамалама — егер контекст өздігінен туындаса ғана мүмкіндіктерді атай аласың"""

    history = get_chat_history(user_id)
    formatted_history = []
    for h in history:
        msg_content = str(h["parts"])
        if "батырмадан таңдаңыз" not in msg_content and "Міне, мен мыналарды таптым" not in msg_content and "Мен бірнеше нұсқа таптым" not in msg_content:
            formatted_history.append({"role": h["role"], "parts": h["parts"]})

    chat = model.start_chat(history=formatted_history)

    try:
        full_prompt = f"НҰСҚАУЛЫҚ (ҚАТАҢ САҚТА): {system_instruction}\n\nҚОЛДАНУШЫНЫҢ СҰРАҒЫ: {text}"

        if chat_id and (placeholder_id or message_id):
            from bot_sender import send_message as _send_msg
            import random as _random
            # Егер placeholder сыртта жасалмаса (тікелей шақыру) — өзіміз жасаймыз
            if not placeholder_id:
                placeholder_id = _send_msg(
                    chat_id,
                    _random.choice(["🔬", "👀", "🤔", "✨", "🔍"]),
                    reply_to_message_id=message_id
                )
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
                    if placeholder_id:
                        edit_message(chat_id, placeholder_id, format_ai_text(full_text))
                    return None
                else:
                    if placeholder_id:
                        edit_message(chat_id, placeholder_id,
                                     "Кешіріңіз, жауап алу кезінде іркіліс болды. Қайта сұрап көресіз бе? 🔄")
                    return None

            if full_text:
                if placeholder_id:
                    edit_message(chat_id, placeholder_id, format_ai_text(full_text))
                return None
            else:
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


# ════════════════════════════════════════════════════════════════
# СУРЕТ ТАНУ
# ════════════════════════════════════════════════════════════════

def process_image_with_ai(image_bytes):
    model = genai.GenerativeModel('gemini-2.5-flash')
    image_parts = [{"mime_type": "image/jpeg", "data": image_bytes}]
    prompt = """Сен — қаптама суретінен өнім немесе мекеме атауын дәл анықтайтын мамансың.
Сенің жалғыз міндетің: суреттегі өнімнің немесе мекеменің БАЗАДАН ІЗДЕУГЕ
ЖАРАЙТЫН атауын шығарып, JSON форматында қайтару.

═══════════════════════════════════════════
ҚАДАМ 1 — СУРЕТТІ БАҒАЛА
═══════════════════════════════════════════

Алдымен суретте не бар екенін анықта:

А) Тамақ өнімінің қаптамасы (шоколад, чипсы, шұжық, сусын, т.б.)
Б) Мекеменің логотипі, вывескасы немесе сыртқы көрінісі
В) Тамақтың өзі (дайын тамақ, нан, ет — қаптамасыз)
Г) Өнім емес (адам, пейзаж, скриншот, т.б.)

═══════════════════════════════════════════
ҚАДАМ 2 — АТ ШЫҒАРУ ЕРЕЖЕЛЕРІ
═══════════════════════════════════════════

ЕРЕЖЕ 1 — НЕ ІЗДЕУ КЕРЕК:
- Бренд атауы (мысалы: "Snickers", "Lays", "KFC", "Mexxi")
- Өндіруші компания атауы (мысалы: "Ülker", "Lotte", "Rakhat")
- Мекеменің ресми атауы (мысалы: "Altynbuta", "Paprika")
- Қоспа коды (мысалы: "E471", "E120") — қаптамада көрінсе

ЕРЕЖЕ 2 — НЕ ЖАЗБАУ КЕРЕК (міндетті түрде алып таста):
- Өнімнің түрі/категориясы: "шоколад", "чипсы", "сары май", "cookie"
- Өлшем/салмақ: "200g", "1L", "500ml"
- Жарнамалық сөздер: "Original", "Classic", "Premium", "New", "Fresh"
- Компания құқықтық формасы: "ЖШС", "ТОО", "LLC", "Inc", "Co."
- Дәм сипаттамасы: "сырлы", "шоколадты", "тәтті"

ЕРЕЖЕ 3 — АЛДЫҢҒЫ ПЛАНДЫ ҒАНА АЛ:
- Суретте бірнеше өнім болса — ТЕК ең үлкен/анық көрінетінін ал
- Артқы фондағы өнімдерді, жанындағы өнімдерді елеме

ЕРЕЖЕ 4 — АТ ФОРМАТЫ (ӨТЕ МАҢЫЗДЫ):
- Бренд атауын қаптамадан ДӘЛМЕ-ДӘЛ КӨШІр
- Кириллмен жазылса → кириллмен жаз: "айс", "АЙС", "Простоквашино"
- Латынмен жазылса → латынмен жаз: "Snickers", "Lays", "AIS"
- Кіші әріппен жазылса → кіші әріппен жаз
- Бас әріппен жазылса → бас әріппен жаз
- АУДАРМА ЖАСАМА: қаптамада "айс" деп тұрса "AIS" деп жазба!
- Өндірушіні тек аты анық жазылса ғана қос, болжама жасама

═══════════════════════════════════════════
ҚАДАМ 3 — JSON ФОРМАТЫ
═══════════════════════════════════════════

Міндетті түрде ТЕК мынадай JSON форматында жауап бер, басқа ештеңе жазба:

Өнім/мекеме табылса:
{"product_names": ["БрендАтауы", "ӨндірушіАтауы"]}

Өндіруші анық көрінбесе:
{"product_names": ["БрендАтауы"]}

Сурет өнім/мекеме емес болса немесе мүлдем оқылмаса:
{"product_names": []}

═══════════════════════════════════════════
МЫСАЛДАР
═══════════════════════════════════════════

Снікерс батончигі ("Snickers" деп жазылған)  → {"product_names": ["Snickers", "Mars"]}
Ülker печеньесі ("Ülker" деп жазылған)        → {"product_names": ["Ülker"]}
KFC вывескасы ("KFC" деп жазылған)            → {"product_names": ["KFC"]}
АЙС айраны ("айс" деп кириллмен жазылған)    → {"product_names": ["айс"]}
ПРОСТОКВАШИНО ("ПРОСТОКВАШИНО" деп жазылған) → {"product_names": ["ПРОСТОКВАШИНО"]}
Адамның суреті                                → {"product_names": []}
Бұлыңғыр сурет                               → {"product_names": []}"""

    try:
        response = model.generate_content(
            [prompt, image_parts[0]],
            request_options={"timeout": 20}
        )
        result_text = clean_json_string(response.text)
        return json.loads(result_text)
    except Exception as e:
        print(f"[process_image_with_ai] Қате: {e}")
        return {"product_names": [f"ҚАТЕ_МӘТІНІ: {str(e)}"]}


def handle_photo(image_bytes, chat_id, username, lang="kz"):
    import concurrent.futures
    from translations import t as _t

    # vision_collector импорты — қате болса бот тоқтамайды
    try:
        from vision_collector import process_image_for_training, check_violators_db
        _vision_ok = True
    except Exception as e:
        print(f"[handle_photo] vision_collector импорт қате: {e}")
        _vision_ok = False

    # ── ПРОЦЕСС A — бренд атауын шығару ─────────────────────────────────
    ai_result = process_image_with_ai(image_bytes)

    # ── ПРОЦЕСС B — фонда жұмыс жасайды, жауапты күтпейді ───────────────
    if _vision_ok:
        try:
            bg_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            bg_executor.submit(process_image_for_training, image_bytes, chat_id)
            bg_executor.shutdown(wait=False)
        except Exception as e:
            print(f"[handle_photo] Process B қате: {e}")

    # ── ПРОЦЕСС C — өшірулі (Google Cloud Vision API қосылғанда іске қосылады) ──
    logo_result = {"detected": False, "confidence": 0.0}

    # ── ПРОЦЕСС A нәтижесін өңдеу ────────────────────────────────────────
    product_names = ai_result.get("product_names", [])

    if not product_names:
        from translations import t
        return t("photo_no_name", lang), None, ""

    if "ҚАТЕ_МӘТІНІ:" in product_names[0]:
        return f"❌ <b>Қате:</b> {product_names[0]}", None, ""

    # ── Мәңгілік бан базасын тексеру (іздемес бұрын) ─────────────────────
    try:
        violator_reply = check_violators_db(product_names[0], lang) if _vision_ok else None
    except Exception as e:
        print(f"[handle_photo] check_violators_db қате: {e}")
        violator_reply = None
    if violator_reply:
        return violator_reply, None, ""

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
            text, markup = format_detail_message(all_found_items[0], confidence=all_found_items[0].get('confidence', 'exact'), query_text=product_names[0], lang=lang)
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
            if len(second_found) == 1:
                text, markup = format_detail_message(second_found[0], confidence=second_found[0].get('confidence', 'exact'), query_text=original_name, lang=lang)
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
            # ── ПРОЦЕСС C (лого детектор) — кейін қосылады ───────────────
            # Vision API іске қосылғанда: save_to_suspicious + notify_admin
            not_found_reply = get_not_found_reply(original_name, normalized_name, lang=lang)
            return not_found_reply, None, ""
