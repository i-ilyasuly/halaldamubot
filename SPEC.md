# 📋 MOMYN BOT — ТОЛЫҚ СПЕЦИФИКАЦИЯ (SPEC.md)

> **Бұл файл — жобаның "заңы".** Кез-келген өзгеріс жасамас бұрын осы файлды оқу МІНДЕТТІ.
> Өзгеріс жасалған соң осы файл да жаңартылуы МІНДЕТТІ.
>
> **Соңғы жаңарту:** 2026-03-20
> **Жоба:** @momyn_bot (ҚМДБ Халал боты)
> **Репозиторий:** https://github.com/i-ilyasuly/all.adal

---

## 🧭 ЖАЛПЫ СИПАТТАМА

Momyn Bot — Telegram боты. Қолданушыға ҚМДБ (Қазақстан мұсылмандары діни басқармасы) тіркеген халал өнімдерді, мекемелерді және Е-қоспаларды табуға көмектеседі. Бот Google Cloud Functions платформасында жұмыс істейді — яғни бөлек сервер жоқ, тек webhook арқылы.

**Мақсаты:** Қолданушы дүкенде өнім ұстап тұрып, оның халал екенін 1 секундта тексере алу.

---

## 🏗️ ЖАЛПЫ АРХИТЕКТУРА

```
Telegram-дан хабар келеді
        ↓
main.py (webhook кіру нүктесі)
        ↓
    [Хабар түріне қарай бөлінеді]
    ├── message → handlers_message.py
    ├── callback_query → handlers_callback.py
    ├── inline_query → handlers_inline.py
    └── pre_checkout_query → payments.py
        ↓
    [Деректер жұмысы]
    ├── Іздеу → search_logic.py → db_core.py (Firestore кэш)
    ├── AI → ai_core.py (Gemini 2.5 Flash)
    └── Форматтау → formatters.py + translations.py
        ↓
bot_sender.py (Telegram API-ге жауап жіберу)
```

**Деректер қоймалары:**
- **Firestore** — companies, ingredients, users, chat_history, draft_gifts, pending_gifts, payments_history, search_sessions
- **BigQuery** — bot_statistics.usage_logs (статистика)
- **Google Cloud Storage** — күдікті суреттер (BUCKET_NAME/suspicious/)

---

## 📁 ФАЙЛДАР — ТОЛЫҚ СИПАТТАМА

---

### 1. `main.py` — Webhook кіру нүктесі

**Не жасайды:** Google Cloud Functions-тің негізгі функциясы. Telegram-дан келген барлық сұраныстарды қабылдап, дұрыс handler-ге жібереді.

**Маңызды логика:**
- `GET` сұраныс + дұрыс `cron_key` → `update_database()` + `clear_cache()` шақырылады (дерекқорды жаңарту)
- `GET` сұраныс + қате кілт → "Қате пароль", 403
- `POST` сұраныс → `update` JSON-ын талдайды:
  - `pre_checkout_query` бар → `process_pre_checkout(update)`
  - `callback_query` бар → `handle_callback(update["callback_query"])`
  - `inline_query` бар → `handle_inline(update["inline_query"])`
  - `message` бар → `handle_message(update["message"])`

**Байланысты файлдар:** `config.py`, `updater.py`, `db_core.py`, `payments.py`, `handlers_callback.py`, `handlers_inline.py`, `handlers_message.py`

---

### 2. `config.py` — Конфигурация

**Не жасайды:** Барлық API кілттерін, тұрақты мәндерді сақтайды.

**Ішіндегі маңызды айнымалылар:**
- `GEMINI_API_KEY` — Google Gemini AI кілті
- `BUCKET_NAME` — Google Cloud Storage шелек аты
- `SUSPICIOUS_FOLDER` — күдікті суреттер сақталатын папка жолы
- `CRON_SECRET` — дерекқорды жаңарту үшін пароль
- Telegram Bot Token және басқа кілттер

**⚠️ Ескерту:** Бұл файлда нақты кілттер болғандықтан GitHub-қа тікелей push жасалмауы тиіс (немесе environment variables арқылы беріледі).

---

### 3. `db_core.py` — Деректер базасымен жұмыс

**Не жасайды:** Firestore және BigQuery-мен барлық операциялар осы файлда.

**Маңызды функциялар:**

#### Кэш жүйесі
```
CACHE = {"companies": [], "ingredients": [], "loaded": False}
```
- `load_cache()` — Firestore-дан companies және ingredients жүктейді (бір рет)
- `clear_cache()` — кэшті тазалайды (cron жаңартқанда шақырылады)
- **⚠️ Маңызды:** Кэш Cloud Function instance өмір сүргенше тірі тұрады. `clear_cache()` тек cron арқылы шақырылады.

#### Пайдаланушы жүйесі
- `add_user(user_id, first_name, username)` — жаңа қолданушы қосу
- `get_user_language(user_id)` → `'kz'` немесе `'ru'` (әдепкі: `'kz'`)
- `set_user_language(user_id, lang)` — тілді сақтау
- `get_user_gender(user_id)` → `"Ер"` немесе `"Әйел"` немесе `None`
- `set_user_gender(user_id, gender)` — жынысты сақтау

#### Қатынас тексеру (check_access)
```
check_access(user_id, is_symbat) → (bool, tier)
```
Тиерлер:
- `"VIP"` — SYMBAT_ID (1042456426) — шексіз қатынас
- `"premium"` — premium_until мерзімі бітпеген → күніне 150 іздеу
- `"free"` — күніне 5 іздеу
- `"LIMIT"` — free limit бітті
- `"SPAM_LIMIT"` — premium spam limit бітті

#### Premium жүйесі
- `grant_premium(user_id, days)` — premium береді. **Маңызды:** Белсенді тариф болса үстіне қосады (жазып тастамайды). Мысалы: 20 күн + 30 күн = 50 күн.
- `revoke_premium(user_id)` — premium алады
- `record_payment(...)` — төлем тарихын жазады

#### Сыйлық кодтары
- `create_gift_code(buyer_id, buyer_name, recipient_username, tariff_id)` → код жасайды
  - `draft_gifts/{code}` — сыйлық ақпараты
  - `pending_gifts/{username}` — алушы бірінші /start жазғанда автоматты табу үшін
- `get_pending_gift_for_username(username)` — күтіп тұрған сыйлықты табу
- `delete_pending_gift(username)` — сыйлық қабылданған соң өшіру
- `redeem_gift_code(code, user_id)` → `(bool, buyer_name, days)` — кодты пайдалану
  - **⚠️ Маңызды:** Сыйлықты жасаған адам өзі ала алмайды (buyer_id тексеріледі)

#### Іздеу сессиясы (пагинация)
- `save_search_session(user_id, items)` → `session_id` — нәтижелерді уақытша сақтау
- `get_search_session(session_id)` → items тізімі

#### BigQuery логтау
- `log_to_bigquery(user_id, action, query_text, status, ...)` — барлық іс-әрекеттерді жазу

#### Чат тарихы (AI үшін)
- `get_chat_history(user_id)` → соңғы 20 хабар тізімі
- `save_chat_history(user_id, role, text)` — хабарды сақтау (20-дан артса ескілерін өшіреді)

**Байланысты файлдар:** `formatters.py`, `tariffs.py`

---

### 4. `ai_core.py` — Жасанды интеллект

**Не жасайды:** Google Gemini AI-мен барлық жұмыс осы файлда.

**Қолданатын модельдер:**
- `gemini-2.5-flash` — чат (мәтінмен сөйлесу)
- `gemini-3.1-flash-lite-preview` — сурет тану (өнім атын алу)

#### chat_with_ai(user_id, text, is_symbat, chat_id, message_id)
Gemini-мен чат жүргізеді. Екі режимі бар:

**Сымбат режимі (is_symbat=True):**
- SYMBAT_ID (1042456426) үшін ғана
- Өте жылы, романтикалық тонда
- Боттың мүмкіндіктерін романтикалық оқиғалар ішіне қыстырады
- Жігіттің нақты есімін ЕШҚАШАН атамайды

**Қалыпты режим (is_symbat=False):**
- Барлық қолданушылар үшін
- Достық, қарапайым тон
- Тек халал тамақтану тақырыбында
- Ботты native advertising арқылы жарнамалайды

**Streaming режимі (chat_id және message_id берілсе):**
1. Алдымен "✍️" placeholder хабар жіберіледі
2. Gemini stream арқылы жауап береді
3. Әр 1 секунд сайын placeholder edit_message арқылы жаңартылады
4. Аяқталған соң финалды мәтін қойылады
5. Функция `None` қайтарады (хабар өзі жіберіліп қойған)

**Streaming жоқ режимде:** толық жауапты қайтарады.

**format_ai_text(text):** `**бұл**` → `<b>бұл</b>`, `*бұл*` → `<i>бұл</i>` (Telegram HTML-ге аударады)

#### process_image_with_ai(image_bytes)
Суреттен өнім атын табады.
- Тек алдыңғы пландағы негізгі өнімді анықтайды
- Брендтің атауы + өндіруші компания (максимум 2 сөз)
- JSON форматында қайтарады: `{"product_names": ["Mexxi", "Ulker"]}`

#### handle_photo(image_bytes, chat_id, username, lang)
Суретті толық өңдейтін функция:
1. `process_image_with_ai()` → атауларды алады
2. `search_data()` арқылы базадан іздейді
3. Нәтижеге қарай:
   - 1 нәтиже → `format_detail_message()` + image_url қайтарады
   - Бірнеше нәтиже → тізім + батырмалар
   - Табылмаса → "табылмады" хабары

#### save_suspicious_image(image_bytes)
Күдікті суреттерді GCS-ке сақтайды. `gs://BUCKET_NAME/suspicious/uuid.jpg` форматында.

---

### 5. `search_logic.py` — Іздеу логикасы

**Не жасайды:** Базадан халал өнімдерді іздейді.

**Іздеу алгоритмі (search_data функциясы):**
1. `load_cache()` — кэш жүктеу
2. E-код іздеу → `parse_e_code()` + `e_variant_in_range()` — диапазон қолдауымен
3. Мекемелер іздеу — `title` (жоқ болса `legal_name`) өрісінен
4. Қоспалар іздеу — `title` (E-код) ЖӘНЕ `name` (мәтіндік атауы) өрістерінен
5. Нәтижелер `confidence` белгісімен: `'exact'` немесе `'fuzzy'`

**E-код функциялары:**
- `parse_e_code(query)` → `(base, variant)` мысалы: "E150c" → ("e150", "c")
- `e_variant_in_range(variant, title_raw)` → `bool`
  - `variant=None` → ӘРҚАШАН True
  - `"(a-d)"` диапазоны → a, b, c, d сәйкес
  - `"Е160b"` бір нұсқа → тек b сәйкес
  - Нұсқасыз өнімге нұсқамен іздеу → False

**get_nearby_companies(lat, lon, page, lang):**
- Берілген координаттан **10 км** радиустағы халал мекемелерді табады
- Пагинация қолдайды
- Карта батырмасымен қайтарады

---

### 6. `formatters.py` — Хабарларды форматтау

**Не жасайды:** Деректерді Telegram HTML хабарына айналдырады.

#### format_item_dict(data, type_name)
Firestore-дан келген сөздікті стандартты item-ге айналдырады.

**Мекеме үшін статус логикасы:**
- `certificate_status == "active"` → `"✅ Белсенді"`
- `certificate_status == "expired"` → `"❌ Мерзімі аяқталған"`
- `certificate_status == "revoked"` → `"🚫 Қайтарып алынған"`
- Басқа → `"⚠️ {cert_status}"`

**Қоспа үшін статус логикасы:**
- `status.name == "Халяль"` → `"✅ Рұқсат етілген"`
- `status.name == "Харам"` → `"🚫 Харам"`
- Басқа (Күдікті, белгісіз) → `"⚠️ Күдікті"`

**`_localize_status(status, lang)`** — статусты орысшаға аударады (display үшін):
- `"✅ Рұқсат етілген"` → `"✅ Разрешено (халяль)"` (ru)
- `"⚠️ Күдікті"` → `"⚠️ Сомнительно"` (ru)
- `"🚫 Харам"` → `"🚫 Харам"` (өзгермейді)

#### format_detail_message(item, confidence, query_text, lang)
Толық хабар мәтіні мен батырмаларын жасайды.

**Мекеме хабарының батырмалары:**
- `🗺️ Картадан көру` — тек Белсенді мекемелерде + map_link болса
- `👍 Пайдалы` / `👎 Қате` — feedback батырмалары

**Қоспа хабарының батырмалары:**
- `👍 Пайдалы` / `👎 Қате` — feedback батырмалары (карта батырмасы жоқ)

**Fuzzy ескертуі:** confidence='fuzzy' болса хабардың жоғарысына ескерту қосылады.

---

### 7. `handlers_message.py` — Хабарларды өңдеу

**Не жасайды:** Қолданушыдан келген барлық хабарларды өңдейді.

**_main_keyboard(lang):** Негізгі reply keyboard — боттың басты мәзірі.

**Кіру нүктелері:**

#### /start командасы:
1. Жаңа қолданушы → тіл таңдату (🇰🇿 / 🇷🇺 батырмалары)
2. `/start gift_XXXX` → сыйлық кодын қолдану
3. SYMBAT_ID → арнайы қарсы алу хабары

#### Негізгі мәзір батырмалары (reply keyboard):
- `🔍 Іздеу` / `Поиск` → іздеу режимін іске қосу
- `📍 Жақын маңдағы` / `Рядом` → локация сұрату
- `⭐ Premium` → premium ақпараты мен сатып алу
- `🎁 Сыйлық` / `Подарить` → сыйлық мәзірі
- `⚙️ Баптаулар` / `Настройки` → баптаулар

#### Хабар түрлері:
- **Мәтін** → `search_data()` арқылы іздейді → нәтижеге қарай жауап
- **Фото** → `handle_photo()` → AI суреті тану → іздеу
- **Локация** → `get_nearby_companies()` → жақын мекемелер тізімі
- **Username күту режимі** (gift_state) → сыйлық үшін username жинайды

**Іздеу нәтижелерінің логикасы:**
- 0 нәтиже → "табылмады" + AI-ға беру ұсынысы
- 1 нәтиже (exact) → тікелей `format_detail_message()`
- 1+ нәтиже → `save_search_session()` + пагинациялы тізім

---

### 8. `handlers_callback.py` — Батырма басуларды өңдеу

**Не жасайды:** Inline батырмаларды (callback_query) өңдейді.

**SYMBAT_ID = 1042456426** — арнайы VIP қолданушы.

**Эффекттер (тек premium/VIP):**
- `EFFECT_HALAL` = "5046509860389126442" — Белсенді мекемеде 🎉 реакция
- `EFFECT_EXPIRED` = "5104858069142078462" — Мерзімі аяқталған/жойылған мекемеде 👎 реакция

**Callback data форматтары және логикасы:**

| Callback data | Не болады |
|---|---|
| `lang:kz` / `lang:ru` | Тіл сақталады → жынысын сұрайды |
| `lang_change:kz` / `lang_change:ru` | Баптаудан тіл өзгерту → жаңа тілде мәзір жіберіледі |
| `gender:male` / `gender:female` | Жынысты сақтайды → негізгі мәзір шығады |
| `settings:gender` | Жынысты өзгерту батырмаларын шығарады |
| `settings:language` | Тіл өзгерту батырмаларын шығарады |
| `buy_premium` | `handle_buy_premium_callback()` шақырады |
| `buy_tariff:{tariff_id}` | Тариф таңдалды → invoice жіберіледі |
| `gift_type:link` / `gift_type:inline` / `gift_type:username` | Сыйлық түрі → тариф таңдату немесе username сұрату |
| `gift_tariff:{tariff_id}:{gift_type}:{recipient}` | Сыйлық тарифы таңдалды → анонимді/атымен сұрайды |
| `gift_anon:named/anon:{gift_type}:{tariff_id}:{recipient}` | Invoice жіберіледі |
| `gift_username_confirm:{username}` | Username расталды → тариф таңдату |
| `gift_username_cancel` | Болдырмау → сыйлық мәзіріне қайту |
| `gift_username_retry` | Username қайта енгізу |
| `itm:c:{id}` / `itm:i:{id}` | Өнім/мекеме толық ақпараты → фото + мәтін + батырмалар |
| `srch:{page}:{session_id}` | Пагинация → кеш сессиясынан деректер |
| `loc:{page}:{lat}:{lon}` | Локация пагинациясы |
| `fb:good:...` | Пайдалы feedback → логтайды, батырмаларды өшіреді |
| `fb:bad:...` | Пайдасыз feedback → себеп таңдату батырмалары шығады |
| `fb:reason:{code}:...` | Себеп таңдалды → логтайды |

**itm callback толық логикасы:**
1. `get_item_by_id(t_code, item_id)` — базадан алады
2. `check_access()` → tier анықтайды
3. Premium/VIP болса → статусқа қарай эффект + реакция
4. image_url болса → `send_photo_message()`, болмаса → `send_message()`
5. Табылмаса → `answer_callback(show_alert=True)`

---

### 9. `handlers_inline.py` — Inline режим

**Не жасайды:** `@momyn_bot [іздеу мәтіні]` форматындағы inline сұраныстарды өңдейді.

**Логикасы:**
1. Қолданушы кез-келген чатта `@momyn_bot Snickers` деп жазады
2. `check_access()` тексереді → limit бітсе ескерту
3. `search_data()` арқылы іздейді
4. Нәтижелерді inline нәтиже ретінде қайтарады
5. `increment_usage()` шақырады

---

### 10. `payments.py` — Telegram Stars төлемдері

**Не жасайды:** Telegram Stars арқылы Premium сатып алу мен сыйлық беруді өңдейді.

**process_pre_checkout(update):**
- Telegram-дан pre_checkout_query келеді → `answer_pre_checkout_query(ok=True)` деп жауап береді

**handle_buy_premium_callback(chat_id, callback_id):**
- Premium сатып алу батырмасы басылғанда → тариф таңдату мәзірі шығады

**Сәтті төлем (successful_payment) логикасы:**
- `payload` талдайды: `premium_{tariff_id}` немесе `gift_{gift_type}_{tariff_id}_{buyer_name}_{recipient}`
- **Өзіне алу:** `grant_premium()` шақырады → растау хабары жіберіледі
- **Сыйлық:** `create_gift_code()` → `/start gift_CODE` сілтемесі жасалады → invoice жіберіледі

---

### 11. `tariffs.py` — Premium тарифтер

**Не жасайды:** Барлық тариф ақпараты бір жерде сақталады.

**Қазіргі тарифтер:**

| ID | Күн | Stars | KZT | Жеңілдік |
|---|---|---|---|---|
| `premium_30_days` | 30 | 100 ⭐ | ~1 000 ₸ | 0% |
| `premium_90_days` | 90 | 250 ⭐ | ~2 300 ₸ | -17% |
| `premium_180_days` | 180 | 500 ⭐ | ~4 600 ₸ | -17% |
| `premium_365_days` | 365 | 1000 ⭐ | ~9 100 ₸ | -17% |

**Маңызды функциялар:**
- `get_tariff_by_id(tariff_id)` → тариф сөздігі немесе None
- `get_tariff_keyboard(callback_prefix, lang)` → inline батырмалар, тілге сай белгі
- `get_tariff_description(tariff_id, lang)` → форматталған мәтін (invoice-та қолданылады)

**Тариф белгілері (label):**
- `label` — қазақша: "1 ай", "3 ай", "6 ай", "12 ай"
- `label_ru` — орысша: "1 месяц", "3 месяца", "6 месяцев", "12 месяцев"

---

### 12. `gift_state.py` — Сыйлық процесінің күйі

**Не жасайды:** Username сұрату кезіндегі күйді (state) сақтайды.

**Функциялар:**
- `set_awaiting_username(user_id)` — бот username күтіп тұр деп белгілейді
- `get_pending_username(user_id)` → `True/False` — күтіп тұр ма?
- `set_pending_anon(user_id, data)` — аноним таңдау күйін сақтайды
- `get_pending_anon(user_id)` → сақталған деректер
- `clear_state(user_id)` — барлық күйді тазалайды

**⚠️ Маңызды:** Бұл күй Cloud Function instance-ында сақталады (in-memory). Инстанс өшсе күй жоғалады. Егер бұл мәселе болса — Firestore-ға ауыстыру керек.

---

### 13. `translations.py` — Тіл аудармасы

**Не жасайды:** Барлық хабарлар мәтіні 🇰🇿 қазақша / 🇷🇺 орысша нұсқалары.

**Қолдану:**
```python
from translations import t
t('welcome_new', lang, name="Асыл")  # → "Сәлем, Асыл! ..."
```

**⚠️ Маңызды:** Жаңа хабар қосқан кезде міндетті түрде екі тілде (`kz` және `ru`) қосу керек.

---

### 14. `bot_sender.py` — Telegram API-ге хабар жіберу

**Не жасайды:** Барлық Telegram API сұраныстары осы файл арқылы өтеді.

**Негізгі функциялар:**
- `send_message(chat_id, text, reply_markup, reply_to_message_id, message_effect_id)` → `message_id`
- `send_photo_message(chat_id, image_url, caption, reply_markup, message_effect_id)` → `message_id`
- `edit_message(chat_id, message_id, text, reply_markup)` — хабарды өзгерту
- `edit_reply_markup(chat_id, message_id, reply_markup, inline_message_id)` — тек батырмаларды өзгерту
- `answer_callback(callback_id, text, show_alert)` — callback-ке жауап
- `set_message_reaction(chat_id, message_id, emoji)` — реакция қою
- `send_gift_invoice(chat_id, ...)` — сыйлық invoice жіберу
- `send_tariff_invoice(chat_id, tariff_id)` — тариф invoice жіберу
- `send_gift_tariff_invoice(chat_id, tariff_id, gift_type, recipient_username, buyer_name)` — сыйлық тарифі invoice

---

### 15. `updater.py` — Деректер базасын жаңарту

**Не жасайды:** ҚМДБ сайтынан жаңа халал өнімдер мен мекемелерді Firestore-ға жүктейді.

**Шақырылу:** `main.py` арқылы GET + cron_key параметрімен (cron жұмысы).

**⚠️ Маңызды:** `update_database()` аяқталған соң `clear_cache()` міндетті түрде шақырылады — бұл ескі кэшті тазалайды.

---

## 🔄 НЕГІЗГІ СЦЕНАРИЙЛЕР (USER FLOWS)

### Сценарий 1: Жаңа қолданушы

```
/start → тіл таңдау батырмалары (🇰🇿 / 🇷🇺)
  → lang:kz немесе lang:ru callback
    → тіл сақталады
    → жынысын сұрайды (🙎‍♂️ / 🙎‍♀️)
      → gender:male/female callback
        → жыныс сақталады
        → негізгі мәзір шығады (reply keyboard)
```

### Сценарий 2: Мәтінмен іздеу

```
Қолданушы "Snickers" жазады
  → check_access() → рұқсат бар ма?
    → Жоқ: лимит хабары
    → Иә: search_data("Snickers")
      → 0 нәтиже: "Табылмады" + AI ұсынысы
      → 1 нәтиже: format_detail_message() → хабар + батырмалар
      → 2+ нәтиже: save_search_session() → пагинациялы тізім
        → itm:i:{id} батырмасы басылады
          → format_detail_message() → толық ақпарат
```

### Сценарий 3: Суретпен іздеу

```
Қолданушы сурет жібереді
  → check_access() → рұқсат бар ма?
    → Жоқ: лимит хабары
    → Иә: handle_photo()
      → process_image_with_ai() → өнім аты алынады
        → search_data(өнім аты)
          → Нәтижелер → (Сценарий 2 сияқты)
```

### Сценарий 4: Локация жіберу

```
Қолданушы локация жібереді
  → get_nearby_companies(lat, lon, page=1)
    → Жақын мекемелер тізімі + пагинация батырмалары
      → loc:{page}:{lat}:{lon} → келесі беттер
```

### Сценарий 5: Inline режим

```
Кез-келген чатта "@momyn_bot Snickers" жазылады
  → handle_inline()
    → check_access() → лимит тексеру
    → search_data("Snickers")
    → Inline нәтижелер тізімі көрінеді
    → Таңдалса → чатқа хабар жіберіледі
```

### Сценарий 6: Premium сатып алу

```
⭐ Premium батырмасы → premium ақпараты + "Сатып алу" батырмасы
  → buy_premium callback
    → тариф таңдату (buy_tariff:premium_30_days т.б.)
      → confirm мәтіні + invoice жіберіледі
        → Қолданушы Stars төлейді
          → pre_checkout_query → answer ok
            → successful_payment
              → grant_premium(days)
              → растау хабары
```

### Сценарий 7: Сыйлық беру

```
🎁 Сыйлық батырмасы → 3 опция:
  ├── Сілтеме арқылы (link)
  ├── Inline арқылы (inline)
  └── Username арқылы (username)
      → Username сұрату → қолданушы жазады
        → Растау батырмасы
          → Тариф таңдату
            → Анонимді/Атымен таңдату
              → Invoice жіберіледі
                → Төлем → create_gift_code()
                  → /start gift_CODE сілтемесі жасалады
                    → Алушы /start gift_CODE жазады
                      → redeem_gift_code()
                        → grant_premium(days)
```

---

## ⚠️ МАҢЫЗДЫ ЕРЕЖЕЛЕР (ӨЗГЕРТУ АЛДЫНДА ОҚУ)

### Байланысты жерлер (касательные точки)

Мына файлды өзгертсең — мына жерлерді де тексер:

| Өзгерілетін файл | Қандай жерлер бұзылуы мүмкін |
|---|---|
| `tariffs.py` | `payments.py`, `handlers_callback.py`, `bot_sender.py` — invoice сомалары |
| `db_core.py` → check_access | `handlers_message.py`, `handlers_inline.py` — барлық іздеуде |
| `formatters.py` → format_item_dict | `search_logic.py`, `ai_core.py` — item структурасы |
| `formatters.py` → format_detail_message | `handlers_callback.py` (itm:), `ai_core.py` (handle_photo) |
| `translations.py` | Барлық `t()` шақырулары — жаңа кілт қосылса екі тілде болуы керек |
| `bot_sender.py` | Барлық файлдар — хабар жіберу интерфейсі |
| `gift_state.py` | `handlers_callback.py`, `handlers_message.py` — username күту логикасы |
| `config.py` | `ai_core.py`, `db_core.py`, `main.py` |

### Callback data форматы — САҚТА!

Callback data өзгертсең — **ескі форматтар бұзылады!** Себебі Telegram-да жіберілген батырмалар ескі callback_data сақтайды.

### SYMBAT_ID

`SYMBAT_ID = 1042456426` — бұл константа `handlers_callback.py` және `ai_core.py`-да қолданылады. Өзгертпе.

### Кэш жүйесі

- `CACHE` тек Cloud Function instance тірі тұрғанда сақталады
- Жаңа деректер `updater.py` + `clear_cache()` арқылы ғана жаңартылады
- Кэшті бұзатын өзгерістер жасасаң — `clear_cache()` шақырылуын тексер

---

## 🧪 ТЕСТ ТІЗІМІ (өзгерістен кейін тексер)

Кез-келген өзгерістен кейін мына сценарийлерді тексер:

- [ ] Жаңа қолданушы → /start → тіл → жыныс → мәзір шығуы
- [ ] Мәтінмен іздеу → нәтиже шығуы (1 нәтиже + бірнеше нәтиже)
- [ ] Суретпен іздеу → AI тануы → нәтиже
- [ ] Локация → жақын мекемелер
- [ ] Inline режим → @momyn_bot арқылы іздеу
- [ ] itm: callback → толық ақпарат + батырмалар
- [ ] srch: callback → пагинация жұмысы
- [ ] loc: callback → локация пагинациясы
- [ ] fb: callback → feedback жазылуы
- [ ] Premium сатып алу → invoice → grant_premium
- [ ] Сыйлық → username → тариф → анонимді → invoice → create_gift_code → redeem
- [ ] Тіл өзгерту → барлық хабарлар жаңа тілде
- [ ] Лимит тексеру → free (5/күн), premium (150/күн)
- [ ] Сымбат режимі → арнайы тон + мүмкіндіктер

---

## 📝 ӨЗГЕРІСТЕР ЖУРНАЛЫ

| Күні | Не өзгерді | Қай файл |
|---|---|---|
| 2026-03-20 | SPEC.md жасалды | — |
| 2026-03-20 | Қоспа статусы түзетілді: Халал/Харам/Күдікті дұрыс анықталады | `formatters.py` |
| 2026-03-20 | Қоспаларды мәтіндік атауынан іздеу қосылды (name өрісі) | `search_logic.py` |
| 2026-03-20 | result_ingredient_haram мәтіні түзетілді; result_ingredient_suspicious қосылды | `translations.py` |
| 2026-03-20 | E-код диапазон іздеу қосылды: parse_e_code() + e_variant_in_range() | `search_logic.py` |
| 2026-03-20 | Тілдік қателіктер түзетілді: статус орысшаға аударылды (_localize_status); тариф белгілері label_ru қосылды; get_tariff_keyboard/get_tariff_description lang параметрін қабылдайды; handlers_message.py және handlers_callback.py-да lang берілді | `formatters.py`, `tariffs.py`, `handlers_callback.py`, `handlers_message.py` |
| 2026-03-20 | Локация радиусы 50 км → 10 км өзгертілді | `search_logic.py` |

> Кез-келген өзгерісті осы кестеге жазып қой.
