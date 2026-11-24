# Телеграм
BOT_TOKEN = "8734616545:AAGhS7IrOlTCMTH2iN286s2Gtd81UeqNx5g"
WEBHOOK_SECRET = "momyn-secret-2024"

# Гугл Жобасы
PROJECT_ID = "momyn-t1"
REGION = "us-central1"

GEOCODING_API_KEY = "AIzaSyCYQoJ6V2wYZm9LCAZDmaReft_dBpdo9r0"

# Түнгі жаңарту паролі
CRON_SECRET = "momyn_halal_update_777"

# Gemini AI кілті
GEMINI_API_KEY = "AIzaSyCaMFQZbuhb2xzBdzRq3K6jEaYF2u83PkU"

# Cloud Storage (Суреттер сақталатын шелек)
BUCKET_NAME = "momyn-vision-assets"
SUSPICIOUS_FOLDER = "audit_suspicious/"

ADMIN_TELEGRAM_ID = 123456789

# Сымбаттың Telegram ID-сі (handlers_callback / handlers_inline осыны импорттайды)
SYMBAT_ID = 1042456426


def get_bot_username():
    """Telegram бот логині (@-сыз). Сыйлық сілтемелерін жасауға қолданылады."""
    return "halaldamu_bot"


# ── WhatsApp Cloud API (Meta) ────────────────────────────────────────────────
# Құпия мәндер кодқа жазылмайды — Cloud Function environment variables арқылы беріледі:
#   gcloud functions deploy ... --set-env-vars WA_PHONE_NUMBER_ID=...,WA_VERIFY_TOKEN=...
#   (WA_ACCESS_TOKEN мен WA_APP_SECRET-ті Secret Manager арқылы берген дұрыс)
import os as _os

WA_ACCESS_TOKEN = _os.environ.get("WA_ACCESS_TOKEN", "")        # System User тұрақты токені
WA_PHONE_NUMBER_ID = _os.environ.get("WA_PHONE_NUMBER_ID", "")  # Meta → WhatsApp → API Setup
WA_VERIFY_TOKEN = _os.environ.get("WA_VERIFY_TOKEN", "")        # Webhook тіркегенде өзіміз ойлап табатын сөз
WA_APP_SECRET = _os.environ.get("WA_APP_SECRET", "")            # Meta App → Settings → Basic → App Secret
WA_API_VERSION = _os.environ.get("WA_API_VERSION", "v23.0")
