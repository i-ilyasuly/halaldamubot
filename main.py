import functions_framework
from config import CRON_SECRET
from updater import update_database
from db_core import clear_cache
from payments import process_pre_checkout

from handlers_callback import handle_callback
from handlers_inline import handle_inline
from handlers_message import handle_message

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

        if "pre_checkout_query" in update:
            process_pre_checkout(update)

        elif "callback_query" in update:
            handle_callback(update["callback_query"])

        elif "inline_query" in update:
            handle_inline(update["inline_query"])

        elif "message" in update:
            handle_message(update["message"])

    return "OK", 200
