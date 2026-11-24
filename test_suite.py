# -*- coding: utf-8 -*-
import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock GCP client libraries before importing modules that initialize them
sys.modules['google.cloud'] = MagicMock()
sys.modules['google.cloud.firestore'] = MagicMock()
sys.modules['google.cloud.bigquery'] = MagicMock()
sys.modules['google.cloud.vision'] = MagicMock()
sys.modules['google.cloud.storage'] = MagicMock()
sys.modules['vertexai'] = MagicMock()
sys.modules['vertexai.generative_models'] = MagicMock()
# functions_framework google.cloud.functions-ты импорттайды (ол жоғарыда mock), сондықтан оны да алмастырамыз
_ff = MagicMock()
_ff.http = lambda f: f
sys.modules['functions_framework'] = _ff

# Now we can import the modules to test
import formatters
import search_logic
import db_core

class TestFormatters(unittest.TestCase):
    def test_strip_html(self):
        self.assertEqual(formatters.strip_html("<p>Hello <br/> World</p>"), "Hello   World")
        self.assertEqual(formatters.strip_html("No HTML"), "No HTML")
        self.assertEqual(formatters.strip_html(""), "")
        self.assertEqual(formatters.strip_html(None), "")

    def test_date_to_unix(self):
        # '01.01.2026' -> Unix timestamp (UTC)
        ts = formatters._date_to_unix("01.01.2026")
        self.assertIsNotNone(ts)
        self.assertEqual(ts, 1767225600)

        # Invalid date should return None
        self.assertIsNone(formatters._date_to_unix("invalid-date"))

    def test_format_item_dict_company(self):
        company_data = {
            "id": "123",
            "title": "Test Company",
            "legal_name": "Test Legal LLC",
            "address": "123 Main St",
            "map_link": "http://maps.google.com/?q=43.25,76.92",
            "certificate_date_start": "01.01.2025",
            "certificate_date_end": "31.12.2025",
            "certificate_status": "active",
            "featured_image": {"thumbnail": "thumb.jpg"}
        }
        res = formatters.format_item_dict(company_data, "\u041c\u0435\u043a\u0435\u043c\u0435")
        self.assertEqual(res["id"], "123")
        self.assertEqual(res["type"], "\u041c\u0435\u043a\u0435\u043c\u0435")
        self.assertEqual(res["title"], "Test Company")
        self.assertEqual(res["desc"], "Test Legal LLC")
        self.assertEqual(res["status"], "\u2705 \u0411\u0435\u043b\u0441\u0435\u043d\u0434\u0456")
        self.assertEqual(res["image_url"], "thumb.jpg")

    def test_format_item_dict_ingredient(self):
        ing_data = {
            "id": "456",
            "title": "E120",
            "name": "\u041a\u0430\u0440\u043c\u0438\u043d",
            "status": {"name": "\u0425\u0430\u043b\u044f\u043b\u044c"}
        }
        res = formatters.format_item_dict(ing_data, "\u049a\u043e\u0441\u043f\u0430")
        self.assertEqual(res["id"], "456")
        self.assertEqual(res["type"], "\u049a\u043e\u0441\u043f\u0430")
        self.assertEqual(res["title"], "E120")
        self.assertEqual(res["desc"], "\u041a\u0430\u0440\u043c\u0438\u043d")
        self.assertEqual(res["status"], "\u2705 \u0420\u04b1\u049b\u0441\u0430\u0442 \u0435\u0442\u0456\u043b\u0433\u0435\u043d")

class TestSearchLogic(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(search_logic.clean_text("\u0410\u0419\u0421"), "\u0430\u0439\u0441")
        self.assertEqual(search_logic.clean_text("Snickers!"), "snickers")
        self.assertEqual(search_logic.clean_text("\u041d\u0430\u043d \u04e9\u043d\u0456\u043c\u0434\u0435\u0440\u0456"), "\u043d\u0430\u043do\u043di\u043c\u0434\u0435\u0440i")

    def test_get_variants(self):
        variants = search_logic.get_variants("\u0410\u0439\u0441")
        self.assertIn("\u0430\u0439\u0441", variants)
        self.assertIn("ays", variants)

    def test_extract_coords(self):
        link = "https://yandex.kz/maps/-/CDuW52-y?ll=76.889397,43.245842&z=17"
        # 43.245842 is latitude, 76.889397 is longitude
        coords = search_logic.extract_coords(link)
        self.assertIsNotNone(coords)
        self.assertAlmostEqual(coords[0], 43.245842)
        self.assertAlmostEqual(coords[1], 76.889397)

    def test_parse_e_code(self):
        self.assertEqual(search_logic.parse_e_code("E120"), ('e120', None))
        self.assertEqual(search_logic.parse_e_code("e-120a"), ('e120', 'a'))
        self.assertEqual(search_logic.parse_e_code("\u0415 120 (b)"), ('e120', 'b'))
        self.assertEqual(search_logic.parse_e_code("Regular Text"), (None, None))

    def test_e_variant_in_range(self):
        self.assertTrue(search_logic.e_variant_in_range("b", "E120(a-c)"))
        self.assertFalse(search_logic.e_variant_in_range("d", "E120(a-c)"))
        self.assertTrue(search_logic.e_variant_in_range("a", "E120a"))
        self.assertFalse(search_logic.e_variant_in_range("b", "E120a"))

class TestDatabaseCore(unittest.TestCase):
    @patch('db_core.db')
    def test_get_item_by_id_cache_hit(self, mock_db):
        # Setup mock cache
        db_core.CACHE["loaded"] = True
        db_core.CACHE["loaded_at"] = db_core._now()
        db_core.CACHE["companies"] = [{
            "id": "company_1",
            "title": "Cached Company",
            "certificate_status": "active"
        }]
        
        # Test cache hit (should not call firestore)
        res = db_core.get_item_by_id("c", "company_1")
        self.assertIsNotNone(res)
        self.assertEqual(res["title"], "Cached Company")
        mock_db.collection.assert_not_called()

    @patch('db_core.db')
    def test_get_item_by_id_cache_miss(self, mock_db):
        # Force cache miss
        db_core.CACHE["loaded"] = False
        
        # Mock Firestore response
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.id = "company_firestore"
        mock_doc.to_dict.return_value = {
            "title": "Firestore Company",
            "certificate_status": "active"
        }
        mock_db.collection.return_value.document.return_value = mock_doc_ref = MagicMock()
        mock_doc_ref.get.return_value = mock_doc

        res = db_core.get_item_by_id("c", "company_firestore")
        self.assertIsNotNone(res)
        self.assertEqual(res["title"], "Firestore Company")
        mock_db.collection.assert_called_with("companies")
        mock_db.collection.return_value.document.assert_called_with("company_firestore")

class TestGroupHandlers(unittest.TestCase):
    def test_via_bot_query_extraction(self):
        import re
        text1 = "🔍 Snickers"
        query1 = re.sub(r'^[🔎🔍\s]+', '', text1).strip()
        self.assertEqual(query1, "Snickers")
        
        text2 = "🔎 Snickers"
        query2 = re.sub(r'^[🔎🔍\s]+', '', text2).strip()
        self.assertEqual(query2, "Snickers")
        
        text3 = "  🔍   Snickers  "
        query3 = re.sub(r'^[🔎🔍\s]+', '', text3).strip()
        self.assertEqual(query3, "Snickers")

    def test_build_search_results_page_with_header(self):
        from handlers_message import _build_search_results_page
        items = [
            {"type": "Мекеме", "title": "Hani 1", "address": "Ural", "status": "Белсенді", "id": "1"},
            {"type": "Мекеме", "title": "Hani 2", "address": "Astana", "status": "Белсенді", "id": "2"}
        ]
        text, kb = _build_search_results_page(items, 1, 5, session_id="test_sess", header_text="Custom Header Text")
        self.assertTrue(text.startswith("Custom Header Text"))
        self.assertEqual(len(kb), 2)  # 2 item buttons
        # Verify that buttons have the "style" field
        self.assertEqual(kb[0][0].get("style"), "success")


class TestThreadedMode(unittest.TestCase):
    def test_context_var_thread_id(self):
        from bot_sender import message_thread_id_var, send_message
        import unittest.mock as mock

        # Test 1: When message_thread_id_var is None
        message_thread_id_var.set(None)
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 123}}
            send_message(12345, "hello")
            payload = mock_post.call_args[1]["json"]
            self.assertNotIn("message_thread_id", payload)

        # Test 2: When message_thread_id_var has a value
        message_thread_id_var.set(999)
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 123}}
            send_message(12345, "hello")
            payload = mock_post.call_args[1]["json"]
            self.assertEqual(payload.get("message_thread_id"), 999)
        message_thread_id_var.set(None)


import unittest.mock as mock

class TestCronCache(unittest.TestCase):
    @mock.patch("main.update_database")
    @mock.patch("main.clear_cache")
    @mock.patch("main.load_cache")
    def test_cron_pre_warming(self, mock_load, mock_clear, mock_update):
        from main import telegram_webhook
        from config import CRON_SECRET

        mock_update.return_value = "db updated"
        mock_req = mock.Mock()
        mock_req.method = "GET"
        mock_req.args = {"cron_key": CRON_SECRET}

        response, code = telegram_webhook(mock_req)
        self.assertEqual(code, 200)
        self.assertEqual(response, "db updated")
        mock_update.assert_called_once()
        mock_clear.assert_called_once()
        mock_load.assert_called_once()


# ════════════════════════════════════════════════════════════════
# WHATSAPP
# ════════════════════════════════════════════════════════════════

class TestWhatsAppFormat(unittest.TestCase):
    def test_html_to_wa_basic(self):
        from wa_sender import html_to_wa
        self.assertEqual(html_to_wa("<b>Hani </b>бар"), "*Hani* бар")
        self.assertEqual(html_to_wa("<i>ескерту</i>"), "_ескерту_")
        self.assertEqual(html_to_wa("a &amp; b &lt;c&gt;"), "a & b <c>")
        self.assertEqual(html_to_wa('<tg-time unix="1" format="D">03.12.2026</tg-time>'), "03.12.2026")
        self.assertEqual(html_to_wa('<a href="https://x.kz">Сайт</a>'), "Сайт (https://x.kz)")

    def test_html_to_wa_blockquote(self):
        from wa_sender import html_to_wa
        out = html_to_wa("✅ OK\n<blockquote>🏭 Өндіруші\n📊 Статус</blockquote>")
        self.assertIn("> 🏭 Өндіруші\n> 📊 Статус", out)
        self.assertNotIn("<", out)

    def test_html_to_wa_real_detail_message(self):
        from wa_sender import html_to_wa
        item = {"type": "Мекеме", "title": "Hani", "status": "Белсенді", "desc": "ЖШС Hani",
                "date_start": "01.01.2026", "date_end": "01.01.2027", "id": "5",
                "map_link": "https://maps.google.com/?q=1,2"}
        text, markup = formatters.format_detail_message(item, lang="kz", tier="free")
        out = html_to_wa(text)
        self.assertNotRegex(out, r"<[a-z/]")
        self.assertIn("01.01.2027", out)

    def test_split_text(self):
        from wa_sender import _split_text
        chunks = _split_text(("а" * 3000 + "\n\n") * 3, limit=4096)
        self.assertTrue(all(len(c) <= 4096 for c in chunks))
        self.assertEqual(len(chunks), 3)


class TestWhatsAppSendRich(unittest.TestCase):
    def setUp(self):
        import wa_sender
        self.wa = wa_sender
        self.sent = []
        self._orig = wa_sender._post
        wa_sender._post = lambda payload, timeout=15: (self.sent.append(payload) or "wamid.X")

    def tearDown(self):
        self.wa._post = self._orig

    def test_detail_with_two_buttons_and_map(self):
        markup = {"inline_keyboard": [
            [{"text": "🗺️ Картадан көру", "url": "https://maps/x"}],
            [{"text": "👍 Пайдалы", "callback_data": "fb:good:itm:c:1"},
             {"text": "👎 Қате", "callback_data": "fb:bad:itm:c:1"}]]}
        self.wa.send_rich("777", "<b>Hani</b> ✅", markup, reply_to="wamid.in")
        self.assertEqual(len(self.sent), 1)
        p = self.sent[0]
        self.assertEqual(p["interactive"]["type"], "button")
        self.assertIn("https://maps/x", p["interactive"]["body"]["text"])
        self.assertEqual(p["context"]["message_id"], "wamid.in")
        ids = [b["reply"]["id"] for b in p["interactive"]["action"]["buttons"]]
        self.assertEqual(ids, ["fb:good:itm:c:1", "fb:bad:itm:c:1"])

    def test_many_items_become_list(self):
        kb = [[{"text": f"{i}. «Өте ұзын өнім атауы номер {i}»", "callback_data": f"itm:i:{i}"}] for i in range(5)]
        kb.append([{"text": "Келесі ➡️", "callback_data": "srch:2:abc"}])
        self.wa.send_rich("777", "header", {"inline_keyboard": kb}, list_label="Таңдау")
        p = self.sent[-1]
        self.assertEqual(p["interactive"]["type"], "list")
        rows = p["interactive"]["action"]["sections"][0]["rows"]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(len(r["title"]) <= 24 for r in rows))

    def test_single_url_becomes_cta(self):
        self.wa.send_rich("777", "text", {"inline_keyboard": [[{"text": "🗺️ Карта", "url": "https://m"}]]})
        self.assertEqual(self.sent[-1]["interactive"]["type"], "cta_url")

    def test_long_text_sent_separately(self):
        self.wa.send_rich("777", "x" * 2000, {"inline_keyboard": [[{"text": "A", "callback_data": "fb:good:ai"}]]})
        self.assertEqual(self.sent[0]["type"], "text")
        self.assertEqual(self.sent[1]["type"], "interactive")

    def test_unsupported_callbacks_filtered(self):
        markup = {"inline_keyboard": [[{"text": "Buy", "callback_data": "buy_tariff:x"}]]}
        self.wa.send_rich("777", "t", markup, allowed_prefixes=("itm:",))
        self.assertEqual(self.sent[-1]["type"], "text")


class TestWhatsAppWebhook(unittest.TestCase):
    def _req(self, method="POST", args=None, body=b"{}", sig=None, json_data=None):
        r = mock.Mock()
        r.method = method
        r.args = args or {}
        r.headers = {"X-Hub-Signature-256": sig} if sig else {}
        r.get_data.return_value = body
        r.get_json.return_value = json_data
        return r

    def test_verify_challenge(self):
        import wa_handlers
        with mock.patch.object(wa_handlers, "WA_VERIFY_TOKEN", "tok"):
            req = self._req("GET", {"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "42"})
            self.assertEqual(wa_handlers.handle_whatsapp_request(req), ("42", 200))
            req = self._req("GET", {"hub.mode": "subscribe", "hub.verify_token": "bad", "hub.challenge": "42"})
            self.assertEqual(wa_handlers.handle_whatsapp_request(req)[1], 403)

    def test_signature_checked(self):
        import hmac, hashlib, wa_handlers
        body = b'{"object":"whatsapp_business_account","entry":[]}'
        good = "sha256=" + hmac.new(b"sec", body, hashlib.sha256).hexdigest()
        with mock.patch.object(wa_handlers, "WA_APP_SECRET", "sec"), \
             mock.patch.object(wa_handlers, "WA_ACCESS_TOKEN", "t"), \
             mock.patch.object(wa_handlers, "WA_PHONE_NUMBER_ID", "1"), \
             mock.patch.object(wa_handlers, "process_payload") as pp:
            self.assertEqual(wa_handlers.handle_whatsapp_request(self._req(body=body, sig="sha256=00"))[1], 403)
            pp.assert_not_called()
            self.assertEqual(wa_handlers.handle_whatsapp_request(
                self._req(body=body, sig=good, json_data={"object": "x"}))[1], 200)
            pp.assert_called_once()

    def test_main_routes_meta_requests(self):
        import main
        with mock.patch("wa_handlers.handle_whatsapp_request", return_value=("ok", 200)) as h:
            req = self._req("GET", {"hub.mode": "subscribe"})
            self.assertEqual(main.telegram_webhook(req), ("ok", 200))
            h.assert_called_once()

    def test_text_message_runs_search(self):
        import wa_handlers
        payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": "77010000000", "profile": {"name": "Айбек"}}],
            "messages": [{"from": "77010000000", "id": "wamid.T1", "type": "text", "text": {"body": "Hani"}}]}}]}]}
        item = {"type": "Мекеме", "title": "Hani", "status": "Белсенді", "desc": "", "id": "9"}
        with mock.patch.object(wa_handlers, "_get_user_data", return_value={"language": "kz"}), \
             mock.patch.object(wa_handlers, "check_access", return_value=(True, "premium")), \
             mock.patch.object(wa_handlers, "search_data", return_value=[item]), \
             mock.patch("classifier.should_classify", return_value=False), \
             mock.patch.object(wa_handlers, "increment_usage"), \
             mock.patch.object(wa_handlers, "log_to_bigquery"), \
             mock.patch.object(wa_handlers, "save_chat_history"), \
             mock.patch.object(wa_handlers.wa, "mark_read"), \
             mock.patch.object(wa_handlers.wa, "send_reaction") as react, \
             mock.patch.object(wa_handlers.wa, "send_rich") as rich:
            wa_handlers._PROCESSED.clear()
            wa_handlers.process_payload(payload)
            wa_handlers.process_payload(payload)   # дубликат — қайта өңделмеуі керек
            self.assertEqual(rich.call_count, 1)
            self.assertEqual(rich.call_args[0][0], "77010000000")
            self.assertIn("Hani", rich.call_args[0][1])
            react.assert_called_once_with("77010000000", "wamid.T1", "✅")

    def test_reply_lang_sets_language(self):
        import wa_handlers
        msg = {"from": "7701", "id": "wamid.L", "type": "interactive",
               "interactive": {"type": "button_reply", "button_reply": {"id": "lang:ru", "title": "RU"}}}
        with mock.patch.object(wa_handlers, "_get_user_data", return_value={"language": "kz"}), \
             mock.patch.object(wa_handlers, "set_user_language") as setl, \
             mock.patch.object(wa_handlers.wa, "mark_read"), \
             mock.patch.object(wa_handlers.wa, "send_text") as st, \
             mock.patch.object(wa_handlers.wa, "send_location_request"):
            wa_handlers.handle_message(msg, "Аня")
            setl.assert_called_once_with("wa_7701", "ru")
            self.assertIn("Русский", st.call_args_list[0][0][1])


if __name__ == '__main__':
    unittest.main()
