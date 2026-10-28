import json
import re
import vertexai
from vertexai.generative_models import GenerativeModel
from config import PROJECT_ID, REGION

vertexai.init(project=PROJECT_ID, location="global")

def classify_query(text):
    """
    Пайдаланушы мәтінін классификациялайды.
    Notion AI Промттар (v1.0) — "Сұрауды жіктеу" промты.
    """
    model = GenerativeModel('gemini-2.5-flash')

    prompt = f"""Сен — халал өнімдер базасының іздеу маршрутизаторысың.
Пайдаланушының хабарламасын оқып, БІРДЕН JSON қайтар.

═══════════════════════════════════════════
ШЫҒЫС ФОРМАТЫ — тек осы екі нұсқа
═══════════════════════════════════════════

{{"action": "search", "query": "нақты атау"}}
{{"action": "chat"}}

═══════════════════════════════════════════
"search" — қашан таңдаймыз?
═══════════════════════════════════════════

Пайдаланушы мыналарды іздеп жатса:
- Өнім атауы: "Snickers халал ма", "Lay's жеуге болады ма"
- Мекеме атауы: "KFC рұқсат па", "Altyn Buta халал ма"
- E-қоспа коды: "E471 не", "E120 харам ба", "E150c қауіпті ме"
- Бренд + сұрақ кез-келген түрде

query өрісіне НЕ жазу керек:
✅ Тек бренд/өнім/мекеме атауын ғана жаз — 1-3 сөз
✅ E-код болса: тек кодты жаз (мысалы: "E471")
✅ Тырнақшадағы сөз болса — сол тырнақшадағы сөз

query өрісінен НЕ алып тастау керек:
❌ халал, харам, рұқсат, жарай ма, ма, ме, ба, бе
❌ өнім, тамақ, дүкен, мекеме, дәмхана
❌ білгім келеді, айтшы, сұрайын, тексер

"X емес Y" ережесі:
"пакмир емес tagam" → query: "tagam"
"tagam деп емес пакмир деп" → query: "пакмир"
Соңғы аталған атауды ал.

═══════════════════════════════════════════
"chat" — қашан таңдаймыз?
═══════════════════════════════════════════

- Амандасу: "сәлем", "қалайсыз", "привет", "қалайсың", "жақсымысың"
- Жалпы сұрақ: "халал дегеніміз не", "ботты қалай пайдаланамын"
- Ешқандай нақты өнім/мекеме атауы жоқ
- Рақмет, сау бол, пока сияқты сөздер

═══════════════════════════════════════════
МЫСАЛДАР
═══════════════════════════════════════════

"пакмир халал ма"                           → {{"action":"search","query":"пакмир"}}
"Snickers жесем болады ма"                 → {{"action":"search","query":"Snickers"}}
"KFC-тің осы жердегісі халал ма"           → {{"action":"search","query":"KFC"}}
"E471 қоспасы қауіпті ме"                  → {{"action":"search","query":"E471"}}
"tagam емес пакмир деген өнім халал ма"    → {{"action":"search","query":"пакмир"}}
"«rahat» кәмпиті жарай ма"                → {{"action":"search","query":"rahat"}}
"Lay's чипсының халал екенін білгім келеді" → {{"action":"search","query":"Lay's"}}
"снікерс"                                   → {{"action":"search","query":"Snickers"}}
"ассалаумағалейкүм"                        → {{"action":"chat"}}
"сәлем"                                    → {{"action":"chat"}}
"қалайсың"                                 → {{"action":"chat"}}
"қалай жүрсің"                             → {{"action":"chat"}}
"халал тамақ дегеніміз не"                → {{"action":"chat"}}
"ботты қалай пайдаланамын"                → {{"action":"chat"}}
"рақмет"                                   → {{"action":"chat"}}

Пайдаланушы хабарламасы: "{text}"

ТЕК JSON қайтар, басқа ештеңе жазба:"""

    quoted = re.findall(r'[«»""\']([\w\s\-]+)[«»""\']', text)
    if quoted:
        hint = f"\nЕскерту: Тырнақшадағы атау: {quoted}. Іздеу атауы осы болуы мүмкін."
        prompt += hint

    try:
        response = model.generate_content(
            prompt
        )
        raw = response.text.strip()
        raw = re.sub(r'```json\s*', '', raw)
        raw = re.sub(r'```\s*', '', raw).strip()
        result = json.loads(raw)
        action = result.get("action", "chat")
        query = result.get("query", "").strip() if action == "search" else ""
        return action, query
    except Exception as e:
        print(f"[classifier] Қате: {e}")
        return "search", text


def should_classify(text):
    """
    4+ сөз болса классификатор шақырылады.
    1-3 сөз — тікелей іздеу.
    Ескерту: 1-3 сөзді chat хабарлар (сәлем, қалайсың)
    search_data табылмай, 4D арқылы classify_query-ге барады.
    """
    words = text.strip().split()
    return len(words) >= 4
