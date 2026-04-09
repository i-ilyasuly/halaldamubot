import requests
from google.cloud import firestore

db = firestore.Client()

def extract_list(api_data):
    """API-дан келген мәліметтің ішінен нақты тізімді (list) тауып алатын ақылды функция"""
    if isinstance(api_data, list):
        return api_data
    elif isinstance(api_data, dict):
        # Егер мәлімет қорап (dict) болса, ішінен тізімді іздейміз
        for key, value in api_data.items():
            if isinstance(value, list):
                return value
    # Егер ешнәрсе табылмаса, бос тізім қайтарады
    return []

def update_database():
    """ҚМДБ базасынан мекемелер мен қоспаларды көшіру"""
    result_text = "Жаңарту басталды...\n"

    # 1. МЕКЕМЕЛЕРДІ ЖАҢАРТУ
    try:
        comp_url = "https://halaldamu.kz/wp-json/map/v1/active-companies?lang=kz&show_all=1"
        print(f"[updater] Мекемелер API сұрауы: {comp_url}")
        comp_resp = requests.get(comp_url, timeout=150)
        print(f"[updater] HTTP статус: {comp_resp.status_code}, ұзындық: {len(comp_resp.content)} байт")
        raw_companies = comp_resp.json()

        if isinstance(raw_companies, dict):
            print(f"[updater] API dict қайтарды, кілттер: {list(raw_companies.keys())[:10]}")
        elif isinstance(raw_companies, list):
            print(f"[updater] API тікелей тізім қайтарды")

        companies = extract_list(raw_companies)
        print(f"[updater] Мекемелер API-дан алынды: {len(companies)} дана")

        count_c = 0
        errors_c = 0
        for comp in companies:
            if isinstance(comp, dict):
                doc_id = str(comp.get("id", count_c))
                try:
                    db.collection("companies").document(doc_id).set(comp, merge=True)
                    count_c += 1
                except Exception as write_err:
                    errors_c += 1
                    print(f"[updater] Мекеме жазу қатесі id={doc_id}: {write_err}")

        print(f"[updater] Мекемелер жазылды: {count_c}, қате: {errors_c}")
        result_text += f"- Мекемелер ({count_c}/{len(companies)} дана) сақталды."
        if errors_c:
            result_text += f" ({errors_c} қате болды)"
        result_text += "\n"
    except Exception as e:
        print(f"[updater] ҚАТЕ (Мекемелер): {e}")
        result_text += f"ҚАТЕ (Мекемелер): {e}\n"

    # 2. ҚОСПАЛАРДЫ ЖАҢАРТУ
    try:
        ing_url = "https://old.halaldamu.kz/ru/api/qospalar/1/1"
        print(f"[updater] Қоспалар API сұрауы: {ing_url}")
        ing_resp = requests.get(ing_url, timeout=150)
        print(f"[updater] HTTP статус: {ing_resp.status_code}, ұзындық: {len(ing_resp.content)} байт")
        raw_ingredients = ing_resp.json()

        ingredients = extract_list(raw_ingredients)
        print(f"[updater] Қоспалар API-дан алынды: {len(ingredients)} дана")

        count_i = 0
        errors_i = 0
        for ing in ingredients:
            if isinstance(ing, dict):
                doc_id = str(ing.get("id", count_i))
                try:
                    db.collection("ingredients").document(doc_id).set(ing, merge=True)
                    count_i += 1
                except Exception as write_err:
                    errors_i += 1
                    print(f"[updater] Қоспа жазу қатесі id={doc_id}: {write_err}")

        print(f"[updater] Қоспалар жазылды: {count_i}, қате: {errors_i}")
        result_text += f"- Қоспалар ({count_i}/{len(ingredients)} дана) сақталды."
        if errors_i:
            result_text += f" ({errors_i} қате болды)"
        result_text += "\n"
    except Exception as e:
        print(f"[updater] ҚАТЕ (Қоспалар): {e}")
        result_text += f"ҚАТЕ (Қоспалар): {e}\n"

    # 3. КЭШ ЖАҢАРТУ УАҚЫТЫН ЖАЗ
    try:
        db.collection("cache_meta").document("last_updated").set({
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        result_text += "- Кэш timestamp жаңартылды.\n"
        print("[updater] Кэш timestamp жаңартылды ✅")
    except Exception as e:
        print(f"[updater] ҚАТЕ (cache_meta): {e}")
        result_text += f"ҚАТЕ (cache_meta): {e}\n"

    print(f"[updater] Нәтиже: {result_text.strip()}")
    return result_text
