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


if __name__ == '__main__':
    unittest.main()
