import json
import threading
import urllib.parse
import urllib.request

import storage

_lock = threading.Lock()
_cache = {}

API = "https://api.mymemory.translated.net/get"


def translate(text, target, source="uz"):
    """Bepul MyMemory API orqali tarjima. Xato bo'lsa bo'sh qaytaradi."""
    text = (text or "").strip()
    if not text:
        return ""
    key = (text, source, target)
    with _lock:
        if key in _cache:
            return _cache[key]
    out = ""
    try:
        q = urllib.parse.quote(text[:900])
        url = "%s?q=%s&langpair=%s|%s" % (API, q, source, target)
        req = urllib.request.Request(url, headers={"User-Agent": "ModHub/2.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        out = ((d.get("responseData") or {}).get("translatedText") or "").strip()
        if out.lower() == text.lower():
            out = ""
    except Exception:
        out = ""
    with _lock:
        _cache[key] = out
    return out


def translate_mod_later(mid, delay=0):
    def _job():
        if delay:
            import time
            time.sleep(delay)
        try:
            translate_mod(mid)
        except Exception as e:
            print("Tarjima xatosi (%s): %s" % (mid, e))

    threading.Thread(target=_job, daemon=True).start()


def translate_mod(mid):
    mod = storage.data.get("mods", {}).get(mid)
    if not mod:
        return False
    name = mod.get("name", "")
    desc = mod.get("description", "") or ""
    tr = mod.setdefault("tr", {})
    changed = False
    for lang in ("en", "ru"):
        cur = dict(tr.get(lang) or {})
        if not cur.get("name"):
            t = translate(name, lang)
            if t:
                cur["name"] = t
                changed = True
        if desc and not cur.get("description"):
            t = translate(desc, lang)
            if t:
                cur["description"] = t
                changed = True
        tr[lang] = cur
    if changed:
        storage.save_data()
    return True
