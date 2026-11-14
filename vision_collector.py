from google.cloud import firestore

db = firestore.Client()

def check_violators_db(product_name, lang="kz"):
    """
    ҚМДБ Халал логотипін заңсыз пайдаланған мекемелер мен брендтерді тексереді.
    """
    try:
        results = db.collection("illegal_logo_violators") \
            .where("certified_at", "==", None).stream()
        for doc in results:
            data = doc.to_dict()
            brand = (data.get("brand_name") or "").lower()
            if brand and brand in product_name.lower():
                confirmed_at = data.get("confirmed_at", "")
                if lang == "ru":
                    return (
                        f"🚫 <b>ВНИМАНИЕ!</b>\n\n"
                        f"«{data.get('brand_name')}» — уличён в <b>незаконном использовании</b> "
                        f"логотипа ДУМК Халал Даму.\n\n"
                        f"📅 Дата: {confirmed_at}\n"
                        f"✅ Сертификат ДУМК: <b>ОТСУТСТВУЕТ</b>\n\n"
                        f"Не можем подтвердить халяльность."
                    )
                return (
                    f"🚫 <b>НАЗАР АУДАРЫҢЫЗ!</b>\n\n"
                    f"«{data.get('brand_name')}» — ҚМДБ Халал Даму логотипін "
                    f"<b>ЗАҢСЫЗ пайдаланғаны</b> анықталған.\n\n"
                    f"📅 Анықталған: {confirmed_at}\n"
                    f"✅ Ресми ҚМДБ сертификаты: <b>ЖОҚ</b>\n\n"
                    f"Бұл өнімнің халал екендігіне кепілдік бере алмаймыз."
                )
        return None
    except Exception as e:
        print(f"[vision] check_violators_db қате: {e}")
        return None
