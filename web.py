import email.parser
import email.utils
import hashlib
import hmac
import json
import mimetypes
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import config
import storage
import tg

MAX_BODY = 200 * 1024 * 1024
MAX_PHOTO_BYTES = 12 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
SUBSCRIPTION_CACHE = 60

_sub_cache = {}
_sub_lock = threading.Lock()
_index_cache = {"mtime": 0, "html": b""}


# ================= AUTH =================
def parse_init_data(init_data):
    if not init_data:
        return None
    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
    except Exception:
        return None
    data = dict(pairs)
    received = data.pop("hash", "")
    data.pop("signature", None)
    if not received:
        return None
    check_string = "\n".join("%s=%s" % (k, v) for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    try:
        user = json.loads(data.get("user") or "{}")
    except Exception:
        return None
    if not user.get("id"):
        return None
    return user


def auth(payload):
    """payload: dict (JSON yoki multipart maydonlari). Foydalanuvchi yoki None."""
    user = parse_init_data(str(payload.get("init_data") or ""))
    if user is None and config.DISABLE_BOT:
        try:
            dev_id = int(payload.get("dev_user") or 0)
        except Exception:
            dev_id = 0
        if dev_id and dev_id in config.DEV_ADMIN_IDS:
            user = {"id": dev_id, "first_name": "Admin", "last_name": "(dev)", "username": "devadmin"}
    if not user:
        return None
    try:
        uid = int(user["id"])
    except Exception:
        return None
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x).strip()
    name = name or "Foydalanuvchi"
    username = user.get("username") or ""
    storage.touch_user(uid, name, username=username)
    storage.register_web_visit(uid)
    prof = storage.get_user(uid) or {}
    return {
        "id": uid,
        "name": name,
        "username": username,
        "avatar": prof.get("avatar", ""),
    }


def is_blocked_now(uid):
    return storage.is_blocked(uid) and not storage.is_admin(uid)


# ================= SUBSCRIPTION =================
def subscribed(uid):
    if storage.is_admin(uid):
        return True
    now = time.time()
    with _sub_lock:
        cached = _sub_cache.get(uid)
        if cached and now - cached[1] < SUBSCRIPTION_CACHE:
            return cached[0]
    import bot
    ok = len(bot.check_channels(uid)) == 0
    with _sub_lock:
        _sub_cache[uid] = (ok, now)
    return ok


# ================= SERIALIZERS =================
def cat_label(cat_id):
    c = config.CATEGORY_MAP.get(cat_id)
    return (c["icon"] + " " + c["name"]) if c else (cat_id or "MINECRAFT")


def mod_json(mid, m, favs):
    photos = storage.mod_photos(m)
    files = m.get("files", [])
    return {
        "id": mid,
        "name": m.get("name", "Nomsiz"),
        "description": m.get("description", "") or "",
        "category": m.get("category", "minecraft"),
        "category_name": cat_label(m.get("category", "minecraft")),
        "date": m.get("date", ""),
        "downloads": m.get("downloads", 0),
        "photos": ["/photo/%s/%d" % (mid, i) for i in range(len(photos))],
        "files": [
            {"name": f.get("file_name") or "fayl", "url": "/download/%s/%d" % (mid, i)}
            for i, f in enumerate(files)
        ],
        "saved": mid in favs,
        "comments": len(storage.data.get("comments", {}).get(mid, [])),
    }


def public_stats():
    d = storage.data
    return {
        "mods": len(d.get("mods", {})),
        "downloads": sum(m.get("downloads", 0) for m in d.get("mods", {}).values()),
        "favorites": sum(len(u.get("favorites", []) or []) for u in d.get("users", {}).values()),
    }


def admin_stats():
    d = storage.data
    live_days = config.LIVE_USER_DAYS
    users = d.get("users", {})
    today = time.strftime("%d.%m.%Y")
    blocked = [{"id": uid, "name": b.get("name", uid), "date": b.get("date", "")}
               for uid, b in d.get("blocked", {}).items()]
    groups = [{"id": gid, "title": g.get("title", ""), "date": g.get("date", "")}
              for gid, g in storage.live_groups().items()]
    return {
        "users_total": len(users),
        "users_live": storage.live_users_count(),
        "users_today": sum(1 for u in users.values() if str(u.get("date", "")).startswith(today)),
        "live_days": live_days,
        "web_live": storage.web_live_count(),
        "mods": len(d.get("mods", {})),
        "downloads": sum(m.get("downloads", 0) for m in d.get("mods", {}).values()),
        "comments": sum(len(v) for v in d.get("comments", {}).values()),
        "groups_live": groups,
        "groups_total": len(d.get("groups", {})),
        "blocked": blocked,
        "admins": d.get("admins", []),
        "channels": d.get("channels", []),
    }


def save_uploaded(content, orig_name, prefix, directory=None):
    ext = os.path.splitext(orig_name or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".zip", ".mcpack",
                   ".mcaddon", ".mcworld", ".jar", ".rar", ".7z", ".txt", ".pdf"):
        ext = ".jpg" if not orig_name else ext[:8]
    safe = storage.safe_filename(os.path.splitext(orig_name or "")[0])[:40]
    fn = "%s_%d_%s%s" % (prefix, int(time.time() * 1000), safe, ext)
    path = os.path.join(directory or config.MODS_DIR, fn)
    with open(path, "wb") as f:
        f.write(content)
    return path


def remove_mod_files(mod):
    for f in mod.get("files", []):
        fp = f.get("file_path") or ""
        if fp and os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass
    for p in storage.mod_photos(mod):
        pp = p.get("path") or ""
        if pp and os.path.exists(pp):
            try:
                os.remove(pp)
            except Exception:
                pass


def publish_mod(mid):
    mod = storage.data.get("mods", {}).get(mid)
    if not mod:
        return False
    link = "https://t.me/%s?start=%s" % (config.BOT_USERNAME, mid)
    caption = "<b>%s</b>\n\n%s\n\n📱 Kanal: @%s" % (
        _esc(mod.get("name", "")), _esc(mod.get("description", "") or ""),
        config.CHANNEL_USERNAME)
    kb = tg.inline_kb([[tg.button("⬇️ Yuklab olish", url=link)]])
    photos = storage.mod_photos(mod)
    if photos:
        p0 = photos[0]
        if p0.get("path") and os.path.exists(p0["path"]):
            tg.send_photo(config.CHANNEL_ID, p0["path"], caption, kb)
        elif p0.get("file_id"):
            tg.send_photo(config.CHANNEL_ID, p0["file_id"], caption, kb)
        if len(photos) > 1:
            tg.send_media_group(config.CHANNEL_ID, photos[1:])
    else:
        tg.send_message(config.CHANNEL_ID, caption, kb)
    return True


def _esc(text):
    from html import escape
    return escape(str(text or ""))


# ================= MULTIPART =================
def parse_multipart(body, content_type):
    fields = {}
    files = []
    try:
        raw = (b"Content-Type: " + content_type.encode("latin-1", "replace") +
               b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
        msg = email.parser.BytesParser().parsebytes(raw)
        if not msg.is_multipart():
            return fields, files
        for part in msg.get_payload():
            disp = str(part.get("Content-Disposition") or "")
            if "form-data" not in disp.lower():
                continue
            name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                files.append({
                    "field": name or "",
                    "filename": filename,
                    "content": payload,
                    "ctype": part.get_content_type(),
                })
            else:
                try:
                    fields[name] = payload.decode("utf-8")
                except Exception:
                    fields[name] = payload.decode("latin-1", "replace")
    except Exception as e:
        print("Multipart parse xatosi:", e)
    return fields, files


# ================= HANDLER =================
class WebHandler(BaseHTTPRequestHandler):
    server_version = "ModHub/2.0"
    protocol_version = "HTTP/1.1"

    # ---------- helpers ----------
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _text(self, text, status=200, ctype="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _file(self, path, download_name=None):
        try:
            size = os.path.getsize(path)
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            if download_name:
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''%s" % urllib.parse.quote(download_name))
                self.send_header("Cache-Control", "no-store")
            else:
                self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print("Fayl yuborish xatosi:", e)

    def _index(self):
        path = os.path.join(config.STATIC_DIR, "index.html")
        try:
            mtime = os.path.getmtime(path)
            with _sub_lock:
                if _index_cache["mtime"] != mtime:
                    with open(path, "rb") as f:
                        _index_cache["html"] = f.read()
                    _index_cache["mtime"] = mtime
                html = _index_cache["html"]
        except Exception:
            self._text("index.html topilmadi", 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(html)
        except Exception:
            pass

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except Exception:
            length = 0
        if length > MAX_BODY:
            return None, None
        body = self.rfile.read(length) if length > 0 else b""
        ctype = self.headers.get("Content-Type") or ""
        if ctype.startswith("multipart/form-data"):
            return parse_multipart(body, ctype)
        if not body:
            return {}, []
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = {}
        return (data if isinstance(data, dict) else {}), []

    # ---------- GET ----------
    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(parsed.path)
            q = urllib.parse.parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                return self._index()

            if path == "/api/health":
                return self._json({"ok": True, "mods": len(storage.data.get("mods", {}))})

            if path == "/api/comments":
                mid = (q.get("mod_id") or [""])[0]
                comments = storage.data.get("comments", {}).get(mid, [])
                return self._json({"ok": True, "comments": list(comments)})

            if path == "/api/admin/backup":
                payload = {"init_data": (q.get("init_data") or [""])[0]}
                user = auth(payload)
                if not user or not storage.is_admin(user["id"]):
                    return self._json({"ok": False, "error": "Ruxsat yo'q"}, 403)
                storage.save_data()
                return self._file(config.DATA_FILE,
                                  "modhub_backup_%s.json" % time.strftime("%Y%m%d_%H%M"))

            m = re.match(r"^/photo/([\w.-]+)/(\d+)$", path)
            if m:
                return self._serve_mod_photo(m.group(1), int(m.group(2)))

            m = re.match(r"^/download/([\w.-]+)/(\d+)$", path)
            if m:
                return self._serve_mod_download(m.group(1), int(m.group(2)))

            if path.startswith("/assets/"):
                return self._serve_dir(os.path.join(config.STATIC_DIR, "assets"),
                                       path[len("/assets/"):])
            if path.startswith("/mods_static/"):
                return self._serve_dir(config.MODS_DIR, path[len("/mods_static/"):])
            if path.startswith("/avatars/"):
                return self._serve_dir(config.AVATARS_DIR, path[len("/avatars/"):])

            self._json({"ok": False, "error": "Topilmadi"}, 404)
        except Exception as e:
            print("GET xatosi:", e)
            self._json({"ok": False, "error": str(e)}, 500)

    def _serve_dir(self, base, rel):
        rel = rel.strip("/")
        if not rel or ".." in rel or "/" in rel or "\\" in rel:
            return self._json({"ok": False, "error": "Noto'g'ri yo'l"}, 400)
        fpath = os.path.join(base, os.path.basename(rel))
        if os.path.isfile(fpath):
            return self._file(fpath)
        self._json({"ok": False, "error": "Fayl topilmadi"}, 404)

    def _serve_mod_photo(self, mid, idx):
        mod = storage.data.get("mods", {}).get(mid)
        photos = storage.mod_photos(mod) if mod else []
        if idx < 0 or idx >= len(photos):
            return self._json({"ok": False, "error": "Rasm topilmadi"}, 404)
        p = photos[idx]
        path = p.get("path") or ""
        if not (path and os.path.exists(path)):
            fid = p.get("file_id") or ""
            if not fid:
                return self._json({"ok": False, "error": "Rasm yo'q"}, 404)
            safe_mid = re.sub(r"[^\w.-]", "_", mid)
            path = os.path.join(config.MODS_DIR, "cache_%s_%d.jpg" % (safe_mid, idx))
            if not os.path.exists(path) and not tg.download_file(fid, path):
                return self._json({"ok": False, "error": "Rasm yuklanmadi"}, 404)
        self._file(path)

    def _serve_mod_download(self, mid, idx):
        mod = storage.data.get("mods", {}).get(mid)
        files = mod.get("files", []) if mod else []
        if idx < 0 or idx >= len(files):
            return self._json({"ok": False, "error": "Fayl topilmadi"}, 404)
        f = files[idx]
        name = f.get("file_name") or "mod_file"
        path = f.get("file_path") or ""
        if not (path and os.path.exists(path)):
            fid = f.get("file_id") or ""
            if not fid:
                return self._json({"ok": False, "error": "Fayl serverda yo'q"}, 404)
            safe_mid = re.sub(r"[^\w.-]", "_", mid)
            path = os.path.join(config.MODS_DIR, "cache_dl_%s_%d_%s" % (
                safe_mid, idx, storage.safe_filename(name)))
            if not os.path.exists(path) and not tg.download_file(fid, path):
                return self._json({"ok": False, "error": "Fayl yuklanmadi"}, 404)
        mod["downloads"] = mod.get("downloads", 0) + 1
        storage.save_data()
        self._file(path, name)

    # ---------- POST ----------
    def do_POST(self):
        payload, files = self._read_body()
        if payload is None:
            return self._json({"ok": False, "error": "So'rov juda katta"}, 413)
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == "/api/init":
                return self._api_init(payload)
            if path == "/api/visit":
                return self._api_visit(payload)
            if path == "/api/favorite":
                return self._api_favorite(payload)
            if path == "/api/settings":
                return self._api_settings(payload)
            if path == "/api/avatar":
                return self._api_avatar(payload, files)
            if path == "/api/comments":
                return self._api_comment_add(payload)
            if path == "/api/check_sub":
                return self._api_check_sub(payload)
            if path == "/api/contact":
                return self._api_contact(payload)
            if path.startswith("/api/admin/"):
                return self._api_admin(path, payload, files)
            self._json({"ok": False, "error": "Topilmadi"}, 404)
        except Exception as e:
            print("POST xatosi (%s): %s" % (self.path, e))
            self._json({"ok": False, "error": str(e)}, 500)

    # ---------- USER APIs ----------
    def _api_init(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        uid = user["id"]
        if is_blocked_now(uid):
            return self._json({"ok": True, "blocked": True, "is_admin": False,
                               "message": "Siz bloklangansiz iltimos admin bilan bo'g'laning : @Cayouz",
                               "user": user})
        prof = storage.get_user(uid) or {}
        favs = set(prof.get("favorites", []) or [])
        mods = [mod_json(mid, m, favs) for mid, m in storage.data.get("mods", {}).items()]
        mods.sort(key=lambda x: storage.parse_ts(x.get("date", "")), reverse=True)
        return self._json({
            "ok": True,
            "user": user,
            "is_admin": storage.is_admin(uid),
            "subscribed": subscribed(uid),
            "blocked": False,
            "settings": prof.get("settings", {"theme": "dark", "sound": True, "bg": True}),
            "favorites": list(favs),
            "invited_count": prof.get("invited_count", 0),
            "joined": prof.get("date", ""),
            "mods": mods,
            "categories": config.CATEGORIES,
            "channels": storage.data.get("channels", []),
            "bot_username": config.BOT_USERNAME,
            "support": config.SUPPORT_USERNAME,
            "stats": public_stats(),
        })

    def _api_visit(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        return self._json({"ok": True, "web_live": storage.web_live_count()})

    def _api_favorite(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "blocked": True, "error": "Bloklangansiz"}, 403)
        if not subscribed(user["id"]):
            return self._json({"ok": False, "forced_sub": True,
                               "error": "Avval kanallarga obuna bo'ling"}, 403)
        mid = str(payload.get("mod_id") or "")
        if mid not in storage.data.get("mods", {}):
            return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
        saved = storage.toggle_favorite(user["id"], mid)
        return self._json({"ok": True, "saved": saved})

    def _api_settings(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "blocked": True, "error": "Bloklangansiz"}, 403)
        settings = storage.set_settings(user["id"], {
            "theme": payload.get("theme"),
            "sound": payload.get("sound"),
            "bg": payload.get("bg"),
        })
        return self._json({"ok": True, "settings": settings})

    def _api_avatar(self, payload, files):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "blocked": True, "error": "Bloklangansiz"}, 403)
        photo = None
        for f in files:
            if f["field"] in ("avatar", "photo"):
                photo = f
                break
        if photo is None:
            return self._json({"ok": False, "error": "Rasm yuborilmadi"}, 400)
        if len(photo["content"]) > 6 * 1024 * 1024:
            return self._json({"ok": False, "error": "Rasm 6MB dan kichik bo'lsin"}, 400)
        prof = storage.get_user(user["id"])
        old = (prof.get("avatar") or "").replace("/avatars/", "")
        if old:
            old_path = os.path.join(config.AVATARS_DIR, os.path.basename(old))
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
        path = save_uploaded(photo["content"], photo["filename"] or "avatar.jpg",
                             "u%s" % user["id"], config.AVATARS_DIR)
        prof["avatar"] = "/avatars/" + os.path.basename(path)
        storage.save_data()
        return self._json({"ok": True, "avatar": prof["avatar"]})

    def _api_comment_add(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "blocked": True, "error": "Bloklangansiz"}, 403)
        if not subscribed(user["id"]):
            return self._json({"ok": False, "forced_sub": True,
                               "error": "Avval kanallarga obuna bo'ling"}, 403)
        mid = str(payload.get("mod_id") or "")
        text = str(payload.get("text") or "").strip()[:500]
        if not text or mid not in storage.data.get("mods", {}):
            return self._json({"ok": False, "error": "Xabar bo'sh"}, 400)
        item = {
            "user_id": user["id"],
            "user_name": user["name"],
            "text": text,
            "date": storage.now_str(),
        }
        storage.data.setdefault("comments", {}).setdefault(mid, []).append(item)
        storage.save_data()
        return self._json({"ok": True, "comment": item})

    def _api_check_sub(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        with _sub_lock:
            _sub_cache.pop(user["id"], None)
        return self._json({
            "ok": True,
            "subscribed": subscribed(user["id"]),
            "channels": storage.data.get("channels", []),
        })

    def _api_contact(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "blocked": True, "error": "Bloklangansiz"}, 403)
        text = str(payload.get("text") or "").strip()[:1500]
        if not text:
            return self._json({"ok": False, "error": "Xabar bo'sh"}, 400)
        import bot
        sent = 0
        for admin_id in storage.data.get("admins", []):
            msg = ("📩 <b>Yangi xabar (Saytdan)</b>\n\n"
                   "👤 <b>%s</b> (ID: <code>%s</code>)\n"
                   "💬 %s\n📅 %s\n\n"
                   "💡 <i>Shu xabarga Telegram'da 'Reply' qilsangiz javob foydalanuvchiga boradi.</i>"
                   % (_esc(user["name"]), user["id"], _esc(text), storage.now_str()))
            kb = tg.inline_kb([[tg.button("👤 Profil", url="tg://user?id=%s" % user["id"])]])
            res = tg.send_message(admin_id, msg, kb)
            if res.get("ok"):
                sent += 1
                storage.register_reply(res["result"]["message_id"], user["id"],
                                       user["id"], user["name"])
        return self._json({"ok": sent > 0, "sent": sent})

    # ---------- ADMIN APIs ----------
    def _api_admin(self, path, payload, files):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if not storage.is_admin(user["id"]):
            return self._json({"ok": False, "error": "Faqat admin uchun"}, 403)
        action = path[len("/api/admin/"):]

        if action == "stats":
            return self._json({"ok": True, "stats": admin_stats()})

        if action == "users":
            q = str(payload.get("q") or "").strip().lower()
            cutoff = time.time() - config.LIVE_USER_DAYS * 86400
            rows = []
            for uid, u in storage.data.get("users", {}).items():
                if storage.parse_ts(u.get("last_seen", "")) < cutoff:
                    continue
                if q and q not in str(u.get("name", "")).lower() and q not in uid:
                    continue
                rows.append({
                    "id": uid,
                    "name": u.get("name", ""),
                    "username": u.get("username", ""),
                    "last_seen": u.get("last_seen", ""),
                    "blocked": storage.is_blocked(uid),
                    "favorites": len(u.get("favorites", []) or []),
                })
            rows.sort(key=lambda x: storage.parse_ts(x["last_seen"]), reverse=True)
            return self._json({"ok": True, "users": rows[:200], "total": len(rows)})

        if action == "mod_add":
            return self._admin_mod_add(payload, files)

        if action == "mod_edit":
            mid = str(payload.get("mod_id") or "")
            mod = storage.data.get("mods", {}).get(mid)
            if not mod:
                return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
            if payload.get("name"):
                mod["name"] = str(payload["name"]).strip()[:120]
            if "description" in payload:
                mod["description"] = str(payload.get("description") or "").strip()[:2000]
            cat = str(payload.get("category") or "")
            if cat in config.CATEGORY_MAP and cat not in ("all", "favorites"):
                mod["category"] = cat
            storage.save_data()
            return self._json({"ok": True})

        if action == "mod_delete":
            mid = str(payload.get("mod_id") or "")
            mod = storage.data.get("mods", {}).get(mid)
            if not mod:
                return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
            remove_mod_files(mod)
            name = mod.get("name", "")
            del storage.data["mods"][mid]
            for uid, u in storage.data.get("users", {}).items():
                favs = u.get("favorites") or []
                if mid in favs:
                    favs.remove(mid)
            storage.save_data()
            return self._json({"ok": True, "name": name})

        if action == "mod_publish":
            mid = str(payload.get("mod_id") or "")
            if mid not in storage.data.get("mods", {}):
                return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
            ok = publish_mod(mid)
            return self._json({"ok": bool(ok)})

        if action == "broadcast":
            text = str(payload.get("text") or "").strip()
            if not text:
                return self._json({"ok": False, "error": "Xabar bo'sh"}, 400)
            import bot
            blocked = storage.data.get("blocked", {})
            total = len([u for u in storage.data.get("users", {}) if u not in blocked])

            def runner():
                t, ok, fail = bot.broadcast_text(text)
                try:
                    tg.send_message(user["id"],
                                    "📢 <b>Xabar tarqatish yakunlandi</b>\n\n"
                                    "👥 Jami: <b>%d</b>\n🟢 Yetib bordi: <b>%d</b>\n"
                                    "🔴 Yetib bormadi: <b>%d</b>" % (t, ok, fail))
                except Exception:
                    pass

            threading.Thread(target=runner, daemon=True).start()
            return self._json({"ok": True, "started": True, "total": total})

        if action == "channels":
            return self._json({"ok": True, "channels": storage.data.get("channels", [])})

        if action == "channel_add":
            ch = str(payload.get("channel") or "").strip()
            if not (ch.startswith("@") or ch.startswith("-")):
                return self._json({"ok": False, "error": "@username yoki -100... ID kiriting"}, 400)
            chans = storage.data.setdefault("channels", [])
            if ch in chans:
                return self._json({"ok": False, "error": "Bu kanal allaqachon bor"}, 400)
            check = tg.api_request("getChat", {"chat_id": ch})
            if not check.get("ok"):
                return self._json({"ok": False,
                                   "error": "Kanal topilmadi. Botni kanalga ADMIN qilib qo'shing."}, 400)
            chans.append(ch)
            storage.save_data()
            return self._json({"ok": True, "channels": chans})

        if action == "channel_del":
            ch = str(payload.get("channel") or "").strip()
            chans = storage.data.setdefault("channels", [])
            if ch in chans:
                chans.remove(ch)
                storage.save_data()
            with _sub_lock:
                _sub_cache.clear()
            return self._json({"ok": True, "channels": chans})

        if action == "block":
            target = str(payload.get("user_id") or "").strip()
            if not target.isdigit():
                return self._json({"ok": False, "error": "Faqat raqamli ID kiriting"}, 400)
            target_id = int(target)
            if storage.is_admin(target_id):
                return self._json({"ok": False, "error": "Adminni bloklab bo'lmaydi"}, 400)
            prof = storage.get_user(target_id) or {}
            storage.block_user(target_id, prof.get("name", str(target_id)))
            try:
                tg.send_message(target_id, "Siz bloklangansiz iltimos admin bilan bo'g'laning : @Cayouz")
            except Exception:
                pass
            return self._json({"ok": True})

        if action == "unblock":
            target = str(payload.get("user_id") or "").strip()
            storage.unblock_user(target)
            return self._json({"ok": True})

        if action == "comment_delete":
            mid = str(payload.get("mod_id") or "")
            try:
                idx = int(payload.get("index"))
            except Exception:
                idx = -1
            items = storage.data.get("comments", {}).get(mid, [])
            if 0 <= idx < len(items):
                items.pop(idx)
                storage.save_data()
                return self._json({"ok": True, "comments": items})
            return self._json({"ok": False, "error": "Izoh topilmadi"}, 404)

        if action == "admin_add":
            target = str(payload.get("user_id") or "").strip()
            if not target.lstrip("-").isdigit():
                return self._json({"ok": False, "error": "To'g'ri ID kiriting"}, 400)
            tid = int(target)
            admins = storage.data.setdefault("admins", [])
            if tid not in admins:
                admins.append(tid)
                storage.save_data()
            return self._json({"ok": True, "admins": admins})

        if action == "admin_del":
            target = str(payload.get("user_id") or "").strip()
            if not target.lstrip("-").isdigit():
                return self._json({"ok": False, "error": "To'g'ri ID kiriting"}, 400)
            tid = int(target)
            if tid in config.ADMIN_IDS:
                return self._json({"ok": False, "error": "Asosiy adminni o'chirib bo'lmaydi"}, 400)
            admins = storage.data.setdefault("admins", [])
            if tid in admins:
                admins.remove(tid)
                storage.save_data()
            return self._json({"ok": True, "admins": admins})

        return self._json({"ok": False, "error": "Noma'lum amal"}, 404)

    def _admin_mod_add(self, payload, files):
        name = str(payload.get("name") or "").strip()[:120]
        desc = str(payload.get("description") or "").strip()[:2000]
        cat = str(payload.get("category") or "minecraft")
        if cat not in config.MOD_CATEGORY_IDS:
            cat = "minecraft"
        if not name:
            return self._json({"ok": False, "error": "Mod nomini kiriting"}, 400)
        photos_in = [f for f in files if f["field"] == "photos" and f["content"]][
            :config.MAX_UPLOAD_PHOTOS]
        files_in = [f for f in files if f["field"] == "files" and f["content"]][
            :config.MAX_MOD_FILES]
        for p in photos_in:
            if len(p["content"]) > MAX_PHOTO_BYTES:
                return self._json({"ok": False, "error": "Har bir rasm 12MB dan kichik bo'lsin"}, 400)
        for f in files_in:
            if len(f["content"]) > MAX_FILE_BYTES:
                return self._json({"ok": False, "error": "Har bir fayl 50MB dan kichik bo'lsin"}, 400)
        if not photos_in:
            return self._json({"ok": False, "error": "Kamida 1 ta rasm yuklang"}, 400)
        if not files_in:
            return self._json({"ok": False, "error": "Kamida 1 ta mod fayli yuklang"}, 400)

        mod_id = "mod_%d_%s" % (int(time.time()), os.urandom(2).hex())
        photos = []
        for p in photos_in:
            path = save_uploaded(p["content"], p["filename"] or "photo.jpg", mod_id)
            photos.append({"file_id": "", "path": path})
        file_list = []
        for f in files_in:
            path = save_uploaded(f["content"], f["filename"] or "file.zip", mod_id)
            file_list.append({"file_id": "", "file_name": f["filename"] or "fayl", "file_path": path})

        mod = {
            "id": mod_id,
            "name": name,
            "description": desc,
            "category": cat,
            "photos": photos,
            "cover_file": photos[0]["path"] if photos else "",
            "cover_id": "",
            "files": file_list,
            "uploader": "web",
            "date": storage.now_str(),
            "downloads": 0,
        }
        storage.data.setdefault("mods", {})[mod_id] = mod
        storage.save_data(backup=False)

        published = False
        if str(payload.get("publish") or "") in ("1", "true", "on"):
            published = publish_mod(mod_id)
        return self._json({"ok": True, "mod": mod_json(mod_id, mod, set()), "published": published})

    def log_message(self, fmt, *args):
        pass


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_server(block=True):
    port = config.PORT
    try:
        server = ThreadedHTTPServer(("0.0.0.0", port), WebHandler)
        print("Web server: http://0.0.0.0:%d" % port)
        if block:
            server.serve_forever()
        else:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    except Exception as e:
        print("Web server xatosi:", e)
        return None
