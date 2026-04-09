import functions_framework
import time
from config import CRON_SECRET
from updater import update_database
from db_core import clear_cache
from payments import process_pre_checkout

from handlers_callback import handle_callback
from handlers_inline import handle_inline
from handlers_message import handle_message

# Telegram webhook retry-ды болдырмау үшін update_id кэші.
# Instance ішінде тұрақты: бір instance 10-15 минут тіршілік етеді,
# сол кезде бірдей update_id 2-рет өңделмейді.
_PROCESSED = {}
_PROCESSED_MAX = 500   # кэш өсіп кетпес үшін шек


@functions_framework.http
def telegram_webhook(request):
    if request.method == "GET":
        if request.args.get("cron_key") == CRON_SECRET:
            result = update_database()
            clear_cache()
            return result, 200
        return "Қате пароль", 403

    if request.method == "POST":
        update = request.get_json()

        # ── WEBHOOK RETRY ҚОРҒАНЫСЫ ──────────────────────────────────────
        # Telegram баяу жауапта update-ті қайта жібереді.
        # update_id бойынша бірдей сұрауды 2-рет өңдемейміз.
        update_id = update.get("update_id") if update else None
        if update_id:
            if update_id in _PROCESSED:
                print(f"[main] Дубликат update_id={update_id} елемеледі")
                return "OK", 200
            _PROCESSED[update_id] = time.time()
            # Кэш өсіп кетпес үшін — ескі жазбаларды тазалаймыз
            if len(_PROCESSED) > _PROCESSED_MAX:
                oldest = sorted(_PROCESSED, key=_PROCESSED.get)[:100]
                for k in oldest:
                    del _PROCESSED[k]

        if "pre_checkout_query" in update:
            process_pre_checkout(update)

        elif "callback_query" in update:
            handle_callback(update["callback_query"])

        elif "inline_query" in update:
            handle_inline(update["inline_query"])

        elif "message" in update:
            handle_message(update["message"])

    return "OK", 200
