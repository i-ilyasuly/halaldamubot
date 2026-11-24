# -*- coding: utf-8 -*-
"""
WhatsApp Cloud API арқылы хабарлама жіберу.

Telegram-ның bot_sender.py-іне ұқсас, бірақ WhatsApp ерекшеліктеріне бейімделген:
  • HTML жоқ → *қалың*, _көлбеу_, > дәйексөз (html_to_wa арқылы)
  • Батырмалар: ең көбі 3 reply-батырма немесе 10 жолдық тізім (list)
  • Интерактив хабарлама мәтіні ≤ 1024 таңба, қарапайым мәтін ≤ 4096
  • Хабарды өңдеу (edit), эффект, placeholder жоқ → оның орнына "typing" индикаторы
"""
import html
import re

import requests

from config import WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID, WA_API_VERSION

# bot_sender requests.post/get-ті 5 секундқа шектеп алмастырады —
# WhatsApp үшін өз сессиямызды ұстаймыз (медиа жүктеу ұзағырақ болуы мүмкін).
_session = requests.Session()

GRAPH_URL = "https://graph.facebook.com"

WA_TEXT_LIMIT = 4096
WA_BODY_LIMIT = 1024      # interactive body / image caption
WA_BTN_TITLE = 20         # reply батырма атауы
WA_ROW_TITLE = 24         # list жолының атауы
WA_ROW_DESC = 72          # list жолының сипаттамасы
WA_LIST_BTN = 20          # list ашатын батырма атауы
WA_MAX_BUTTONS = 3
WA_MAX_ROWS = 10


# ════════════════════════════════════════════════════════════════
# ФОРМАТТАУ
# ════════════════════════════════════════════════════════════════

def _wrap(marker, inner):
    """*мәтін* — WhatsApp маркер ішінде шеткі бос орын болмауы керек."""
    lead = inner[:len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()):]
    core = inner.strip()
    if not core:
        return inner
    # Көп жолды мәтінде әр жолды бөлек ораймыз, әйтпесе WhatsApp танымайды
    lines = [f"{marker}{ln.strip()}{marker}" if ln.strip() else ln for ln in core.split("\n")]
    return lead + "\n".join(lines) + trail


def _quote_block(inner):
    lines = inner.strip("\n").split("\n")
    return "\n".join(f"> {ln}" if ln.strip() else ">" for ln in lines)


def html_to_wa(text):
    """Telegram HTML → WhatsApp пішімі."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    # Сілтемелер: <a href="url">мәтін</a> → мәтін (url)
    s = re.sub(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
               lambda m: m.group(2) if m.group(2).strip() == m.group(1) else f"{m.group(2)} ({m.group(1)})",
               s, flags=re.I | re.S)
    # Telegram-ға тән тегтер — тек ішіндегі мәтін қалады
    s = re.sub(r"</?(tg-time|tg-spoiler|tg-emoji|span|u|ins)[^>]*>", "", s, flags=re.I)
    s = re.sub(r"<pre[^>]*>(.*?)</pre>", lambda m: f"```{m.group(1)}```", s, flags=re.I | re.S)
    s = re.sub(r"<code[^>]*>(.*?)</code>", lambda m: f"`{m.group(1)}`", s, flags=re.I | re.S)
    s = re.sub(r"<(b|strong)>(.*?)</\1>", lambda m: _wrap("*", m.group(2)), s, flags=re.I | re.S)
    s = re.sub(r"<(i|em)>(.*?)</\1>", lambda m: _wrap("_", m.group(2)), s, flags=re.I | re.S)
    s = re.sub(r"<(s|strike|del)>(.*?)</\1>", lambda m: _wrap("~", m.group(2)), s, flags=re.I | re.S)
    s = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>", lambda m: "\n" + _quote_block(m.group(1)) + "\n",
               s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", "", s)          # қалған белгісіз тегтер
    s = html.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _cut(text, limit):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _split_text(text, limit=WA_TEXT_LIMIT):
    """Ұзын мәтінді абзац/жол шекарасынан бөліп береді."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


# ════════════════════════════════════════════════════════════════
# ТӨМЕН ДЕҢГЕЙЛІ API
# ════════════════════════════════════════════════════════════════

def _headers():
    return {"Authorization": f"Bearer {WA_ACCESS_TOKEN}", "Content-Type": "application/json"}


def _post(payload, timeout=15):
    """messages endpoint-іне POST. Сәтті болса — жіберілген хабар ID-сі (wamid)."""
    url = f"{GRAPH_URL}/{WA_API_VERSION}/{WA_PHONE_NUMBER_ID}/messages"
    body = {"messaging_product": "whatsapp", **payload}
    try:
        resp = _session.post(url, json=body, headers=_headers(), timeout=timeout)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            print(f"[wa_sender] API қате {resp.status_code}: {data} | type={payload.get('type')}")
            return None
        msgs = data.get("messages") or []
        return msgs[0].get("id") if msgs else True
    except Exception as e:
        print(f"[wa_sender] Желі қатесі: {e}")
        return None


def _ctx(reply_to):
    return {"context": {"message_id": reply_to}} if reply_to else {}


# ════════════════════════════════════════════════════════════════
# ЖІБЕРУ ФУНКЦИЯЛАРЫ
# ════════════════════════════════════════════════════════════════

def send_text(to, text, reply_to=None, preview_url=True):
    """Қарапайым мәтін. 4096-дан ұзын болса — бірнеше хабарға бөлінеді."""
    last_id = None
    for i, chunk in enumerate(_split_text(text)):
        last_id = _post({
            "to": to, "type": "text",
            "text": {"body": chunk, "preview_url": preview_url},
            **(_ctx(reply_to) if i == 0 else {}),
        })
    return last_id


def send_image(to, image_url, caption=None, reply_to=None):
    image = {"link": image_url}
    if caption:
        image["caption"] = _cut(caption, WA_BODY_LIMIT)
    return _post({"to": to, "type": "image", "image": image, **_ctx(reply_to)})


def send_buttons(to, body, buttons, reply_to=None, footer=None):
    """buttons: [(id, title), ...] — ең көбі 3."""
    interactive = {
        "type": "button",
        "body": {"text": _cut(body, WA_BODY_LIMIT)},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": bid[:256], "title": _cut(title, WA_BTN_TITLE)}}
            for bid, title in buttons[:WA_MAX_BUTTONS]
        ]},
    }
    if footer:
        interactive["footer"] = {"text": _cut(footer, 60)}
    return _post({"to": to, "type": "interactive", "interactive": interactive, **_ctx(reply_to)})


def send_list(to, body, button_label, rows, reply_to=None, section_title=None):
    """rows: [(id, title, description), ...] — ең көбі 10."""
    section = {"rows": [
        {"id": rid[:200], "title": _cut(title, WA_ROW_TITLE),
         **({"description": _cut(desc, WA_ROW_DESC)} if desc else {})}
        for rid, title, desc in rows[:WA_MAX_ROWS]
    ]}
    if section_title:
        section["title"] = _cut(section_title, 24)
    interactive = {
        "type": "list",
        "body": {"text": _cut(body, WA_BODY_LIMIT)},
        "action": {"button": _cut(button_label, WA_LIST_BTN), "sections": [section]},
    }
    return _post({"to": to, "type": "interactive", "interactive": interactive, **_ctx(reply_to)})


def send_cta_url(to, body, display_text, url, reply_to=None):
    """Бір сілтеме-батырмасы бар хабар (мысалы, «Картадан көру»)."""
    interactive = {
        "type": "cta_url",
        "body": {"text": _cut(body, WA_BODY_LIMIT)},
        "action": {"name": "cta_url",
                   "parameters": {"display_text": _cut(display_text, WA_BTN_TITLE), "url": url}},
    }
    return _post({"to": to, "type": "interactive", "interactive": interactive, **_ctx(reply_to)})


def send_location_request(to, body, reply_to=None):
    """«Орнымды жіберу» батырмасы бар хабар."""
    interactive = {
        "type": "location_request_message",
        "body": {"text": _cut(body, WA_BODY_LIMIT)},
        "action": {"name": "send_location"},
    }
    return _post({"to": to, "type": "interactive", "interactive": interactive, **_ctx(reply_to)})


def send_reaction(to, message_id, emoji):
    return _post({"to": to, "type": "reaction",
                  "reaction": {"message_id": message_id, "emoji": emoji}}, timeout=5)


def mark_read(message_id, typing=True):
    """Хабарды «оқылды» деп белгілеп, «жазып жатыр...» индикаторын көрсетеді (≤25 сек)."""
    payload = {"status": "read", "message_id": message_id}
    if typing:
        payload["typing_indicator"] = {"type": "text"}
    return _post(payload, timeout=5)


def download_media(media_id):
    """Пайдаланушы жіберген сурет/файлдың байттарын қайтарады."""
    try:
        meta = _session.get(f"{GRAPH_URL}/{WA_API_VERSION}/{media_id}",
                            headers=_headers(), timeout=15).json()
        url = meta.get("url")
        if not url:
            print(f"[wa_sender] media url жоқ: {meta}")
            return None
        resp = _session.get(url, headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}"}, timeout=30)
        if resp.status_code != 200:
            print(f"[wa_sender] media жүктеу қатесі: {resp.status_code}")
            return None
        return resp.content
    except Exception as e:
        print(f"[wa_sender] download_media қате: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# TELEGRAM MARKUP → WHATSAPP
# ════════════════════════════════════════════════════════════════

def split_markup(markup):
    """Telegram inline_keyboard-ты (callback батырмалар, url батырмалар) екіге бөледі."""
    callbacks, urls = [], []
    if not markup or not isinstance(markup, dict):
        return callbacks, urls
    for row in markup.get("inline_keyboard", []) or []:
        for btn in row:
            if btn.get("callback_data"):
                callbacks.append((btn["callback_data"], btn.get("text", "")))
            elif btn.get("url"):
                urls.append((btn.get("text", ""), btn["url"]))
    return callbacks, urls


def send_rich(to, text, markup=None, image_url=None, reply_to=None,
              list_label="Таңдау", allowed_prefixes=None, prompt="👇"):
    """
    Telegram стиліндегі (HTML мәтін + inline_keyboard + сурет) жауапты
    WhatsApp-қа ең жақын түрде жібереді. Соңғы жіберілген хабар ID-сін қайтарады.
    """
    body = html_to_wa(text)
    callbacks, urls = split_markup(markup)
    if allowed_prefixes:
        callbacks = [(cid, title) for cid, title in callbacks if cid.startswith(tuple(allowed_prefixes))]

    # Бір ғана сілтеме және басқа батырма жоқ → cta_url батырмасы
    cta = None
    if len(urls) == 1 and not callbacks and not image_url:
        cta = urls[0]
    elif urls:
        body += "\n\n" + "\n".join(f"{html_to_wa(title)}\n{url}" for title, url in urls)

    last_id = None
    body_sent = False

    if image_url:
        if len(body) <= WA_BODY_LIMIT and not callbacks:
            last_id = send_image(to, image_url, caption=body, reply_to=reply_to)
            body_sent = bool(last_id)
        else:
            send_image(to, image_url, reply_to=reply_to)
        reply_to = None

    if not body_sent and cta and len(body) <= WA_BODY_LIMIT:
        last_id = send_cta_url(to, body, html_to_wa(cta[0]), cta[1], reply_to=reply_to)
        body_sent = bool(last_id)
        if not body_sent:   # cta сәтсіз болса — сілтемені мәтінге қосамыз
            body += f"\n\n{cta[1]}"

    if not callbacks:
        if not body_sent:
            last_id = send_text(to, body, reply_to=reply_to)
        return last_id

    # Батырмалар бар: мәтін қысқа болса — бір интерактив хабарға сыйғызамыз
    if not body_sent and len(body) > WA_BODY_LIMIT:
        send_text(to, body, reply_to=reply_to)
        reply_to = None
        body_sent = True
    inter_body = prompt if body_sent else body

    short = all(len(title) <= WA_BTN_TITLE for _, title in callbacks)
    if len(callbacks) <= WA_MAX_BUTTONS and short:
        last_id = send_buttons(to, inter_body, callbacks, reply_to=reply_to)
    else:
        rows = []
        for cid, title in callbacks[:WA_MAX_ROWS]:
            title = html_to_wa(title)
            desc = title if len(title) > WA_ROW_TITLE else None
            rows.append((cid, title, desc))
        last_id = send_list(to, inter_body, list_label, rows, reply_to=reply_to)

    if not last_id:
        # Интерактив сәтсіз (мысалы, атау шектен асты) — ең болмаса мәтінді жеткіземіз
        print("[wa_sender] interactive сәтсіз → қарапайым мәтін")
        last_id = send_text(to, body if not body_sent else inter_body)
    return last_id
