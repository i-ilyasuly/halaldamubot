# WhatsApp интеграциясы

Бот WhatsApp Cloud API (Meta) арқылы жұмыс істейді. Іздеу, сурет тану, ЖИ, Firestore, BigQuery — Telegram-мен ортақ.

## Файлдар

| Файл | Не істейді |
|---|---|
| `wa_sender.py` | WhatsApp-қа хабар жіберу; Telegram HTML → WhatsApp пішімі; inline_keyboard → батырма/тізім |
| `wa_handlers.py` | Webhook-ты растау, қолтаңбаны тексеру, хабарларды өңдеу (мәтін, сурет, локация, батырмалар) |
| `main.py` | `whatsapp_webhook` кіру нүктесі; `telegram_webhook` Meta сұраныстарын да өзі бағыттайды |
| `config.py` | `WA_*` баптаулары — тек environment variables-тан оқылады |

Пайдаланушылар Firestore-да `users/wa_<телефон>` болып сақталады, BigQuery-де `platform = "whatsapp"`.

## Іске қосу қадамдары

1. **Meta Business аккаунты** — business.facebook.com, компанияны растау (Business Verification).
2. **Meta for Developers** → *Create App* → түрі *Business* → **WhatsApp** өнімін қосу.
3. **Нөмір** — WhatsApp → API Setup → *Add phone number*. Бұл нөмір қарапайым WhatsApp / WhatsApp Business қосымшасында тіркелмеген болуы керек.
4. **Тұрақты токен** — Business Settings → Users → *System users* → Admin қолданушы жасау → қолданбаны тағайындау → *Generate token* (`whatsapp_business_messaging`, `whatsapp_business_management` рұқсаттары).
5. **Environment variables** — Cloud Function-ға қосу:

   ```bash
   gcloud functions deploy <функция-аты> \
     --update-env-vars WA_PHONE_NUMBER_ID=<id>,WA_VERIFY_TOKEN=<өзіңіз ойлап тапқан сөз> \
     --update-secrets WA_ACCESS_TOKEN=wa-access-token:latest,WA_APP_SECRET=wa-app-secret:latest
   ```

   `WA_APP_SECRET` — App → Settings → Basic → *App Secret*. Онсыз барлық POST сұраныстар қабылданбайды (403).

6. **Webhook** — App → WhatsApp → Configuration:
   - *Callback URL*: Telegram боттың қазіргі Cloud Function URL-ы (жаңа деплой керек емес) немесе `--entry-point whatsapp_webhook` арқылы бөлек функция.
   - *Verify token*: 5-қадамдағы `WA_VERIFY_TOKEN`.
   - *Webhook fields*: **messages** белгілеу.
7. Тексеру: нөмірге «Сәлем» деп жазу → тіл таңдау батырмалары келуі керек.

## Telegram-нан айырмашылықтар

- Inline режим, Telegram Stars төлемі, сыйлықтар, хабарды өңдеу/эффект — WhatsApp-та жоқ, сондықтан қосылмаған.
- Батырмалар: ≤3 болса reply-батырма, көп болса тізім (≤10 жол). Сілтеме батырмалары мәтінге қосылады (жалғыз болса — cta_url батырмасы).
- Placeholder эмодзи орнына «жазып жатыр...» индикаторы көрсетіледі.
- Пайдаланушы бірінші жазғаннан кейін 24 сағат ішінде жауаптар тегін. Бот өзі бірінші жазуы (жаппай хабарлама) үшін Meta-да бекітілген ақылы template керек.
- Дубликаттан қорғау үшін Firestore-да `wa_processed` коллекциясы толады — TTL саясатын (мысалы, 7 күн, `at` өрісі бойынша) қосқан дұрыс.
