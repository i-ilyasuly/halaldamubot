# ════════════════════════════════════════════════════════════════════════════
# quotes.py — Halal Damu Bot | Дәйексөз жүйесі
# ════════════════════════════════════════════════════════════════════════════
#
# Қолдану:
#   from quotes import get_quote
#   quote_block = get_quote("halal", lang="kz")
#   msg += "\n\n" + quote_block
#
# Санаттар: halal, haram, expired, suspicious, not_found,
#            location, payment, gift_received
# ════════════════════════════════════════════════════════════════════════════

import random
from quotes_quran import QURAN_QUOTES
from quotes_kazakh import KAZAKH_QUOTES

# ── Барлық санаттар бойынша пулдарды біріктіру ─────────────────────────────
_POOL: dict[str, list] = {}

for _cat in ("halal", "haram", "expired", "suspicious",
             "not_found", "location", "payment", "gift_received"):
    _quran  = QURAN_QUOTES.get(_cat, [])
    _kazakh = KAZAKH_QUOTES.get(_cat, [])
    _POOL[_cat] = _quran + _kazakh


# ── Форматтаушылар ──────────────────────────────────────────────────────────

def _format_quran(q: dict, lang: str) -> str:
    """Құран аяты үшін <blockquote expandable> блогы."""
    arabic = q.get("arabic", "")
    text   = q.get(lang, q.get("kz", ""))
    source = q.get(f"source_{lang}", q.get("source_kz", ""))

    lines = [f"🕌 <i>{arabic}</i>", ""]
    if text:
        lines.append(text)
    if source:
        lines.append("")
        lines.append(f"📖 <i>{source}</i>")

    inner = "\n".join(lines)
    return f"<blockquote expandable>{inner}</blockquote>"


def _format_kazakh(q: dict, lang: str) -> str:
    """Қазақ мақал-мәтелі үшін <blockquote expandable> блогы."""
    kz_text     = q.get("kz", "")
    ru_text     = q.get("ru", "")
    desc        = q.get(f"description{'_ru' if lang == 'ru' else ''}", "")
    read_more   = q.get("read_more", "")

    # Мақалды \n бойынша жол бойынша сақтаймыз
    main_text = kz_text if lang == "kz" else (ru_text or kz_text)

    lines = [f"💬 <i>{main_text}</i>"]

    # Орысша нұсқада қазақшасын да көрсетеміз (егер бар болса)
    if lang == "ru" and kz_text and ru_text and kz_text != ru_text:
        lines.insert(0, f"💬 <i>{kz_text}</i>")
        lines[1] = f"<i>{ru_text}</i>"

    if desc:
        lines.append("")
        lines.append(f"<i>{desc}</i>")

    lines.append("")
    if read_more:
        label = "Толығырақ оқу →" if lang == "kz" else "Подробнее →"
        lines.append(f'📚 maqal.kz · <a href="{read_more}">{label}</a>')
    else:
        lines.append("📚 maqal.kz")

    inner = "\n".join(lines)
    return f"<blockquote expandable>{inner}</blockquote>"


# ── Негізгі функция ─────────────────────────────────────────────────────────

def get_quote(category: str, lang: str = "kz") -> str:
    """
    Берілген санат пен тіл үшін кездейсоқ дәйексөз қайтарады.
    Пул бос болса — бос жол қайтарады.

    Args:
        category: "halal" | "haram" | "expired" | "suspicious" |
                  "not_found" | "location" | "payment" | "gift_received"
        lang:     "kz" | "ru"

    Returns:
        Telegram HTML форматындағы <blockquote expandable> жолы,
        немесе пул бос болса бос жол "".
    """
    pool = _POOL.get(category, [])
    if not pool:
        return ""

    q = random.choice(pool)
    q_type = q.get("type", "")

    if q_type == "quran":
        return _format_quran(q, lang)
    elif q_type == "kazakh_proverb":
        return _format_kazakh(q, lang)
    else:
        return ""
