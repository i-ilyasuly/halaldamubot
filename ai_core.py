import functions_framework
import time
from config import CRON_SECRET
from updater import update_database
from db_core import clear_cache, load_cache
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
            print("[Cron] База жаңартылды, кэш тазартылды. Кэшті алдын ала жүктеу (pre-warming) басталды...")
            load_cache()
            print("[Cron] Кэш алдын ала сәтті жүктелді (pre-warming аяқталды).")
            return result, 200
        return "Қате пароль", 403

    if request.method == "POST":
        update = request.get_json()
        req_type = "unknown"
        if "message" in update: req_type = "message"
        elif "callback_query" in update: req_type = f"callback:{update['callback_query'].get('data', '')}"
        elif "inline_query" in update: req_type = "inline"
        elif "pre_checkout_query" in update: req_type = "pre_checkout"
        elif "my_chat_member" in update: req_type = "my_chat_member"

        update_id = update.get("update_id") if update else None
        print(f"[Webhook Start] update_id={update_id}, type={req_type}")
        t_start = time.perf_counter()

        try:
            # ── WEBHOOK RETRY ҚОРҒАНЫСЫ ──────────────────────────────────────
            # Telegram баяу жауапта update-ті қайта жібереді.
            # update_id бойынша бірдей сұрауды 2-рет өңдемейміз.
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

            # --- Thread Mode (Тақырыптар) қолдауы ---
            message_thread_id = None
            if update:
                if "message" in update:
                    msg_obj = update["message"]
                    chat_type = msg_obj.get("chat", {}).get("type")
                    if chat_type == "private":
                        message_thread_id = msg_obj.get("message_thread_id")
                elif "callback_query" in update:
                    cb_message = update["callback_query"].get("message", {})
                    chat_type = cb_message.get("chat", {}).get("type")
                    if chat_type == "private":
                        message_thread_id = cb_message.get("message_thread_id")

            from bot_sender import message_thread_id_var
            message_thread_id_var.set(message_thread_id)

            if "pre_checkout_query" in update:
                process_pre_checkout(update)

            elif "callback_query" in update:
                handle_callback(update["callback_query"])

            elif "inline_query" in update:
                handle_inline(update["inline_query"])

            elif "my_chat_member" in update:
                from handlers_message import handle_my_chat_member
                handle_my_chat_member(update["my_chat_member"])

            elif "message" in update:
                handle_message(update["message"])

            dt = time.perf_counter() - t_start
            print(f"[Webhook End] update_id={update_id}, type={req_type} took {dt:.3f}s")

        except Exception as e:
            import traceback
            dt = time.perf_counter() - t_start
            print(f"[Webhook End] update_id={update_id}, type={req_type} FAILED in {dt:.3f}s. Error: {e}")
            traceback.print_exc()

    return "OK", 200
