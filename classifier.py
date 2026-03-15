import json
import re
import google.generativeai as genai
from config import GEMINI_API_KEY

genai.configure(api_key=GEMINI_API_KEY)

def classify_query(text):
    """
    Пайдаланушы мәтінін классификациялайды:
    - {"action": "search", "query": "Snickers"} — өнім/мекеме іздеу
    - {"action": "chat"} — AI мен сөйлесу

    Тек 4+ сөзді сұраулар үшін шақырылады.
    Gemini Flash Lite — жылдам әрі арзан.
    """
    model = genai.GenerativeModel('gemini-2.0-flash-lite')

    prompt = f"""Пайдаланушы Telegram-да халал тамақ тексеретін ботқа жазды.

Мына мәтінді талда: "{text}"

Екі жағдайдың бірі:
1. Пайдаланушы нақты өнім, тамақ, дәмхана, немесе E-қоспаның халал екенін сұрап жатыр → action: "search", query өрісіне тек ең негізгі іздеу сөзін жаз (бренд атауы немесе өнім атауы, артық сөздерсіз)
2. Пайдаланушы жай сөйлесіп жатыр, амандасып жатыр, немесе жалпы сұрақ қоюда → action: "chat"

Ережелер:
- "халал ма", "харам ба", "тексер", "бар ма" сияқты сұрақтар болса — бұл іздеу (search)
- "E471", "E120" сияқты E-кодтар болса — бұл іздеу (search), query-ге кодты жаз
- "жи жауап берші ... халал ма" болса — бұл іздеу (search), өнім атауын ал
- Амандасу, әңгіме, кеңес сұрау — бұл chat

Тек JSON форматында жауап бер, басқа ештеңе жазба:
{{"action": "search", "query": "өнім атауы"}}
немесе
{{"action": "chat"}}"""

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        # JSON тазалау
        raw = re.sub(r'```json\s*', '', raw)
        raw = re.sub(r'```\s*', '', raw).strip()
        result = json.loads(raw)
        action = result.get("action", "chat")
        query = result.get("query", "").strip() if action == "search" else ""
        return action, query
    except Exception as e:
        print(f"[classifier] Қате: {e}")
        # Қате болса — тікелей іздеу жіберейік (қауіпсіз fallback)
        return "search", text


def should_classify(text):
    """
    4+ сөз болса классификатор шақырылады.
    1-3 сөз — тікелей іздеу.
    """
    words = text.strip().split()
    return len(words) >= 4
