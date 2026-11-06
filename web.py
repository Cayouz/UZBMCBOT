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
    signature = data.pop("signature", None)
    if not received:
        return None
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()

    def _check(fields):
        check_string = "\n".join("%s=%s" % (k, v) for k, v in sorted(fields.items()))
        calc = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(calc, received)

    if not _check(data) and not (signature is not None and _check(dict(data, signature=signature))):
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
        "tg_lang": user.get("language_code") or "",
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


def user_lang(uid):
    s = (storage.get_user(uid) or {}).get("settings") or {}
    return s.get("lang") or "uz"


def mod_json(mid, m, favs, lang="uz"):
    photos = storage.mod_photos(m)
    files = m.get("files", [])
    tr = (m.get("tr") or {}).get(lang) or {}
    return {
        "id": mid,
        "name": tr.get("name") or m.get("name", "Nomsiz"),
        "description": tr.get("description") or m.get("description", "") or "",
        "category": m.get("category", "minecraft"),
        "category_name": cat_label(m.get("category", "minecraft")),
        "editions": storage.mod_editions(m),
        "date": m.get("date", ""),
        "downloads": m.get("downloads", 0),
        "photos": ["/photo/%s/%d%s" % (
            mid, i, "?v=" + urllib.parse.quote(str(m["photo_revision"])) if m.get("photo_revision") else "")
            for i in range(len(photos))],
        "files": [
            {"name": f.get("file_name") or "fayl", "url": "/download/%s/%d" % (mid, i)}
            for i, f in enumerate(files)
        ],
        "saved": mid in favs,
        "hidden": bool(m.get("hidden")),
        "channel_tracked": bool(m.get("channel_posts")),
        "channel_sync_error": bool(m.get("channel_sync_error")),
        "comments": len(storage.data.get("comments", {}).get(mid, [])),
    }


def public_stats():
    d = storage.data
    mods = [mod for mod in d.get("mods", {}).values() if storage.mod_visible(mod)]
    return {
        "mods": len(mods),
        "downloads": sum(m.get("downloads", 0) for m in mods),
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
    fn = "%s_%d_%s_%s%s" % (prefix, int(time.time() * 1000), os.urandom(8).hex(), safe, ext)
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


_channel_lock = threading.RLock()


def _channel_content(mid, mod):
    link = "https://t.me/%s?start=%s" % (config.BOT_USERNAME, mid)
    name = str(mod.get("name") or "")[:120]
    footer = "\n\n📱 Kanal: @%s" % config.CHANNEL_USERNAME
    description = str(mod.get("description") or "")[:max(0, 1024 - len(name) - len(footer) - 4)]
    caption = "<b>%s</b>\n\n%s%s" % (_esc(name), _esc(description), footer)
    keyboard = tg.inline_kb([[tg.button("⬇️ Yuklab olish", url=link)]])
    return caption, keyboard


def _channel_photo(photo):
    path = photo.get("path") or ""
    return path if path and os.path.isfile(path) else photo.get("file_id") or ""


def _channel_ok(result):
    return bool(result.get("ok") or "message is not modified" in str(result.get("description") or "").lower())


def publish_mod(mid):
    with _channel_lock:
        mod = storage.data.get("mods", {}).get(mid)
        if not mod or mod.get("hidden"):
            return False
        caption, keyboard = _channel_content(mid, mod)
        photos = storage.mod_photos(mod)
        if photos:
            photo = _channel_photo(photos[0])
            if not photo:
                return False
            result = tg.send_photo(config.CHANNEL_ID, photo, caption, keyboard)
        else:
            result = tg.send_message(config.CHANNEL_ID, caption, keyboard)
        message_id = (result.get("result") or {}).get("message_id")
        if not result.get("ok") or not message_id:
            return False
        post = {"chat_id": config.CHANNEL_ID, "message_id": message_id,
                "kind": "photo" if photos else "text", "extra_ids": []}
        mod.setdefault("channel_posts", []).append(post)
        storage.save_data()
        extra = photos[1:]
        if len(extra) == 1:
            photo = _channel_photo(extra[0])
            result = tg.send_photo(config.CHANNEL_ID, photo) if photo else {"ok": False}
            messages = [result.get("result") or {}] if result.get("ok") else []
        elif extra:
            result = tg.send_media_group(config.CHANNEL_ID, extra)
            messages = result.get("result") or [] if result.get("ok") else []
        else:
            messages = []
        post["extra_ids"] = [message["message_id"] for message in messages if message.get("message_id")]
        complete = len(post["extra_ids"]) == len(extra)
        mod["channel_sync_error"] = not complete
        storage.save_data()
        return complete


def sync_mod_posts(mid, media_changed=False):
    with _channel_lock:
        mod = storage.data.get("mods", {}).get(mid)
        posts = mod.get("channel_posts") if mod else None
        if not posts:
            return None
        caption, keyboard = _channel_content(mid, mod)
        photos = storage.mod_photos(mod)
        media_changed = media_changed or mod.get("channel_sync_error", False)
        ok = True
        for post in posts:
            chat_id, message_id = post["chat_id"], post["message_id"]
            if photos and (media_changed or post["kind"] == "text"):
                photo = _channel_photo(photos[0])
                result = tg.edit_photo(chat_id, message_id, photo, caption, keyboard) if photo else {"ok": False}
                if _channel_ok(result):
                    post["kind"] = "photo"
            elif post["kind"] == "photo":
                result = tg.api_request("editMessageCaption", {
                    "chat_id": chat_id, "message_id": message_id, "caption": caption,
                    "parse_mode": "HTML", "reply_markup": json.dumps(keyboard)})
            else:
                result = tg.edit_message(chat_id, message_id, caption, keyboard)
            ok = _channel_ok(result) and ok
            if not media_changed:
                continue
            extra_ids = post["extra_ids"]
            extra = photos[1:]
            for index, photo in enumerate(extra):
                source = _channel_photo(photo)
                if index < len(extra_ids):
                    result = tg.edit_photo(chat_id, extra_ids[index], source) if source else {"ok": False}
                else:
                    result = tg.send_photo(chat_id, source, silent=True) if source else {"ok": False}
                    new_id = (result.get("result") or {}).get("message_id")
                    if result.get("ok") and new_id:
                        extra_ids.append(new_id)
                    else:
                        ok = False
                        break
                ok = _channel_ok(result) and ok
            for old_id in extra_ids[len(extra):][:]:
                result = tg.api_request("deleteMessage", {"chat_id": chat_id, "message_id": old_id})
                if result.get("ok"):
                    extra_ids.remove(old_id)
                else:
                    ok = False
        mod["channel_sync_error"] = not ok
        storage.save_data()
        return ok


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

    def _file(self, path, download_name=None, private=False):
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
            elif private:
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
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

    # ---------- HEAD (uptime monitorlar uchun) ----------
    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        status = 200 if path in ("/", "/index.html", "/api/health") else 404
        self.send_response(status)
        if status == 200:
            ctype = "application/json; charset=utf-8" if path == "/api/health" else "text/html; charset=utf-8"
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.close_connection = True
        self.end_headers()

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
                mod = storage.data.get("mods", {}).get(mid)
                if mod and not storage.mod_visible(mod):
                    return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
                comments = []
                for c in storage.data.get("comments", {}).get(mid, []):
                    cc = dict(c)
                    cc.setdefault("avatar", (storage.get_user(c.get("user_id")) or {}).get("avatar", ""))
                    comments.append(cc)
                return self._json({"ok": True, "comments": comments})

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
                return self._serve_avatar(path[len("/avatars/"):])

            self._json({"ok": False, "error": "Topilmadi"}, 404)
        except Exception as e:
            print("GET xatosi:", e)
            self._json({"ok": False, "error": str(e)}, 500)

    def _serve_dir(self, base, rel):
        rel = rel.strip("/")
        if not rel or ".." in rel or "/" in rel or "\\" in rel:
            return self._json({"ok": False, "error": "Noto'g'ri yo'l"}, 400)
        fpath = os.path.join(base, os.path.basename(rel))
        if base == config.MODS_DIR:
            normalized_path = os.path.normcase(os.path.abspath(fpath))
            normalized_name = os.path.normcase(rel)
            for mid, mod in storage.data.get("mods", {}).items():
                if not mod.get("hidden"):
                    continue
                paths = [os.path.normcase(os.path.abspath(record["file_path"]))
                         for record in mod.get("files") or [] if record.get("file_path")]
                prefixes = tuple(os.path.normcase(prefix) for prefix in (mid + "_", "cache_dl_" + mid + "_"))
                if normalized_path in paths or normalized_name.startswith(prefixes):
                    return self._json({"ok": False, "error": "Fayl topilmadi"}, 404)
        if os.path.isfile(fpath):
            return self._file(fpath)
        self._json({"ok": False, "error": "Fayl topilmadi"}, 404)

    def _serve_avatar(self, rel):
        name = os.path.basename(rel.strip("/"))
        if not name or ".." in name:
            return self._json({"ok": False, "error": "Noto'g'ri yo'l"}, 400)
        fpath = os.path.join(config.AVATARS_DIR, name)
        if not os.path.isfile(fpath):
            fid = storage.find_avatar_file_id(name)
            if fid and tg.download_file(fid, fpath):
                return self._file(fpath)
            return self._json({"ok": False, "error": "Fayl topilmadi"}, 404)
        self._file(fpath)

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
            media_key = hashlib.sha256(fid.encode()).hexdigest()[:16]
            path = os.path.join(config.MODS_DIR, "cache_%s_%d_%s.jpg" % (safe_mid, idx, media_key))
            if not os.path.exists(path) and not tg.download_file(fid, path):
                return self._json({"ok": False, "error": "Rasm yuklanmadi"}, 404)
        self._file(path)

    def _serve_mod_download(self, mid, idx):
        mod = storage.data.get("mods", {}).get(mid)
        if mod and not storage.mod_visible(mod):
            return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
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
            media_key = hashlib.sha256(fid.encode()).hexdigest()[:16]
            path = os.path.join(config.MODS_DIR, "cache_dl_%s_%d_%s_%s" % (
                safe_mid, idx, media_key, storage.safe_filename(name)))
            if not os.path.exists(path) and not tg.download_file(fid, path):
                return self._json({"ok": False, "error": "Fayl yuklanmadi"}, 404)
        f["file_path"] = path
        storage.file_sha256(f)
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
            if path == "/api/download":
                return self._api_download(payload)
            if path == "/api/check_sub":
                return self._api_check_sub(payload)
            if path == "/api/contact":
                return self._api_contact(payload, files)
            if path == "/api/messages":
                return self._api_messages(payload)
            if path == "/api/message_photo":
                return self._api_message_photo(payload)
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
        lang = user_lang(uid)
        mods = [mod_json(mid, m, favs, lang) for mid, m in storage.data.get("mods", {}).items()
                if storage.mod_visible(m, uid)]
        mods.sort(key=lambda x: storage.parse_ts(x.get("date", "")), reverse=True)
        return self._json({
            "ok": True,
            "user": user,
            "is_admin": storage.is_admin(uid),
            "subscribed": subscribed(uid),
            "blocked": False,
            "settings": prof.get("settings", {"theme": "dark", "sound": True, "bg": True}),
            "unread": storage.unread_messages(uid),
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
        return self._json({"ok": True, "web_live": storage.web_live_count(),
                           "unread": storage.unread_messages(user["id"])})

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
        mod = storage.data.get("mods", {}).get(mid)
        if not mod or not storage.mod_visible(mod, user["id"]):
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
            "lang": payload.get("lang"),
            "font": payload.get("font"),
        })
        return self._json({"ok": True, "settings": settings})

    def _api_download(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "blocked": True, "error": "Bloklangansiz"}, 403)
        if not subscribed(user["id"]):
            return self._json({"ok": False, "forced_sub": True,
                               "error": "Avval kanallarga obuna bo'ling"}, 403)
        mid = str(payload.get("mod_id") or "")
        mod = storage.data.get("mods", {}).get(mid)
        if not mod or not storage.mod_visible(mod, user["id"]):
            return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
        files = mod.get("files", []) or []
        if not files:
            return self._json({"ok": False, "error": "Fayl biriktirilmagan"}, 404)
        try:
            idx = int(payload.get("file"))
        except Exception:
            idx = -1
        items = [files[idx]] if 0 <= idx < len(files) else files[:10]
        sent, last_err = 0, ""
        for f in items:
            path = f.get("file_path") or ""
            fid = f.get("file_id") or ""
            if path and os.path.exists(path):
                res = tg.send_document(user["id"], path)
            elif fid:
                res = tg.send_document(user["id"], fid)
            else:
                last_err = last_err or "Fayl serverda yo'q"
                continue
            if res.get("ok"):
                sent += 1
            else:
                last_err = res.get("description") or res.get("error") or "Telegram xatosi"
        if not sent:
            return self._json({"ok": False, "error": last_err or "Yuborishda xatolik"}, 502)
        mod["downloads"] = mod.get("downloads", 0) + 1
        storage.save_data()
        return self._json({"ok": True, "sent": sent, "total": len(items)})

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
        prof["avatar_file_id"] = ""
        try:
            res = tg.send_photo(user["id"], path, caption="🖼 <b>Profil rasmi saqlandi</b>", silent=True)
            sizes = (res.get("result") or {}).get("photo") or []
            if sizes:
                prof["avatar_file_id"] = sizes[-1].get("file_id", "")
        except Exception as e:
            print("Avatar zaxira xatosi:", e)
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
        mod = storage.data.get("mods", {}).get(mid)
        if mod and not storage.mod_visible(mod, user["id"]):
            return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
        text = str(payload.get("text") or "").strip()[:500]
        if not text or not mod:
            return self._json({"ok": False, "error": "Xabar bo'sh"}, 400)
        item = {
            "user_id": user["id"],
            "user_name": user["name"],
            "avatar": (storage.get_user(user["id"]) or {}).get("avatar", ""),
            "text": text,
            "date": storage.now_str(),
        }
        storage.data.setdefault("comments", {}).setdefault(mid, []).append(item)
        storage.save_data()
        return self._json({"ok": True, "comment": item})

    def _api_messages(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "blocked": True, "error": "Bloklangansiz"}, 403)
        msgs = [{"id": m.get("id", ""), "from": m.get("from", ""),
                 "text": m.get("text", ""), "date": m.get("date", ""),
                 "read": m.get("read", False), "has_photo": bool(m.get("photo"))}
                for m in storage.get_messages(user["id"])]
        storage.mark_messages_read(user["id"])
        return self._json({"ok": True, "messages": msgs, "unread": 0})

    def _api_message_photo(self, payload):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "error": "Bloklangansiz"}, 403)
        mid = str(payload.get("message_id") or "")
        message = next((m for m in storage.get_messages(user["id"])
                        if m.get("id") == mid and m.get("photo")), None)
        if not message:
            return self._json({"ok": False, "error": "Rasm topilmadi"}, 404)
        photo = message["photo"]
        path = photo.get("path") or ""
        if not path or not os.path.isfile(path):
            directory = os.path.join(config.BASE_DIR, "chat_photos")
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "msg_%s.jpg" % message["id"])
            if not photo.get("file_id") or not tg.download_file(photo["file_id"], path):
                return self._json({"ok": False, "error": "Rasm yuklanmadi"}, 404)
            photo["path"] = path
            storage.save_data()
        return self._file(path, private=True)

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

    def _api_contact(self, payload, files):
        user = auth(payload)
        if not user:
            return self._json({"ok": False, "error": "Avtorizatsiya xatosi"}, 401)
        if is_blocked_now(user["id"]):
            return self._json({"ok": False, "blocked": True, "error": "Bloklangansiz"}, 403)
        text = str(payload.get("text") or "").strip()[:1500]
        uploads = [f for f in files if f["field"] == "photo" and f["content"]]
        if len(uploads) > 1:
            return self._json({"ok": False, "error": "Bir xabarda bitta rasm yuboring"}, 400)
        if not text and not uploads:
            return self._json({"ok": False, "error": "Xabar bo'sh"}, 400)
        photo = None
        if uploads:
            content = uploads[0]["content"]
            if len(content) > 6 * 1024 * 1024:
                return self._json({"ok": False, "error": "Rasm 6MB dan kichik bo'lsin"}, 400)
            if content.startswith(b"\xff\xd8\xff"):
                ext = ".jpg"
            elif content.startswith(b"\x89PNG\r\n\x1a\n"):
                ext = ".png"
            elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                ext = ".webp"
            else:
                return self._json({"ok": False, "error": "JPG, PNG yoki WebP rasm yuboring"}, 400)
            directory = os.path.join(config.BASE_DIR, "chat_photos")
            os.makedirs(directory, exist_ok=True)
            path = save_uploaded(content, "chat" + ext, os.urandom(16).hex(), directory)
            photo = {"path": path, "file_id": ""}
        item = storage.add_message(user["id"], "user", text, photo=photo)
        sent = 0
        for admin_id in storage.data.get("admins", []):
            photo_ok = True
            if photo:
                res_photo = tg.send_photo(admin_id, photo["path"], caption=_esc(text[:1024]))
                photo_ok = bool(res_photo.get("ok"))
                if photo_ok:
                    sizes = (res_photo.get("result") or {}).get("photo") or []
                    if sizes:
                        item["photo"]["file_id"] = sizes[-1].get("file_id", "")
                    storage.register_reply(res_photo["result"]["message_id"], user["id"],
                                           user["id"], user["name"])
            msg = ("📩 <b>Yangi xabar (Saytdan)</b>\n\n"
                   "👤 <b>%s</b> (ID: <code>%s</code>)\n"
                   "💬 %s\n📅 %s\n\n"
                   "💡 <i>Shu xabarga Telegram'da 'Reply' qilsangiz javob foydalanuvchiga boradi.</i>"
                   % (_esc(user["name"]), user["id"], _esc(text), storage.now_str()))
            kb = tg.inline_kb([[tg.button("👤 Profil", url="tg://user?id=%s" % user["id"])]])
            res = tg.send_message(admin_id, msg, kb)
            if res.get("ok"):
                if photo_ok:
                    sent += 1
                storage.register_reply(res["result"]["message_id"], user["id"],
                                       user["id"], user["name"])
        storage.save_data()
        return self._json({"ok": True, "sent": sent})

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

        if action == "backup":
            ok = storage.backup_now(force=True, wait=True)
            if not ok:
                return self._json({"ok": False, "error": "Zaxira yuborilmadi"}, 502)
            return self._json({"ok": True})

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
                    "avatar": u.get("avatar", ""),
                    "last_seen": u.get("last_seen", ""),
                    "blocked": storage.is_blocked(uid),
                    "favorites": len(u.get("favorites", []) or []),
                })
            rows.sort(key=lambda x: storage.parse_ts(x["last_seen"]), reverse=True)
            return self._json({"ok": True, "users": rows[:200], "total": len(rows)})

        if action == "mod_add":
            return self._admin_mod_add(payload, files, user)

        if action == "mod_get":
            mid = str(payload.get("mod_id") or "")
            mod = storage.data.get("mods", {}).get(mid)
            if not mod:
                return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
            result = mod_json(mid, mod, set())
            result["name"] = mod.get("name") or ""
            result["description"] = mod.get("description") or ""
            result["link"] = "https://t.me/%s?start=%s" % (config.BOT_USERNAME, mid)
            return self._json({"ok": True, "mod": result})

        if action == "mod_edit":
            return self._admin_mod_edit(payload, files, user)

        if action == "mod_visibility":
            mid = str(payload.get("mod_id") or "")
            mod = storage.data.get("mods", {}).get(mid)
            if not mod:
                return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
            if not isinstance(payload.get("hidden"), bool):
                return self._json({"ok": False, "error": "Noto'g'ri holat"}, 400)
            mod["hidden"] = payload["hidden"]
            storage.save_data()
            favs = set((storage.get_user(user["id"]) or {}).get("favorites", []))
            return self._json({"ok": True, "mod": mod_json(mid, mod, favs, user_lang(user["id"]))})

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

    def _admin_mod_edit(self, payload, files, user):
        mid = str(payload.get("mod_id") or "")
        mod = storage.data.get("mods", {}).get(mid)
        if not mod:
            return self._json({"ok": False, "error": "Mod topilmadi"}, 404)
        updates = {}
        if "name" in payload:
            name = str(payload.get("name") or "").strip()[:120]
            if not name:
                return self._json({"ok": False, "error": "Mod nomini kiriting"}, 400)
            updates["name"] = name
        if "description" in payload:
            updates["description"] = str(payload.get("description") or "").strip()[:2000]
        if "category" in payload:
            cat = str(payload.get("category") or "")
            if cat not in config.MOD_CATEGORY_IDS:
                return self._json({"ok": False, "error": "Kategoriyani tanlang"}, 400)
            updates["category"] = cat
        photos_in = [f for f in files if f["field"] == "photos" and f["filename"]]
        files_in = [f for f in files if f["field"] == "files" and f["filename"]]
        if len(photos_in) > config.MAX_UPLOAD_PHOTOS or len(files_in) > config.MAX_MOD_FILES:
            return self._json({"ok": False, "error": "Ko'pi bilan 5 ta rasm va 10 ta fayl tanlang"}, 400)
        for p in photos_in:
            content = p["content"]
            if len(content) > MAX_PHOTO_BYTES:
                return self._json({"ok": False, "error": "Har bir rasm 12MB dan kichik bo'lsin"}, 400)
            if content.startswith(b"\xff\xd8\xff"):
                p["ext"] = ".jpg"
            elif content.startswith(b"\x89PNG\r\n\x1a\n"):
                p["ext"] = ".png"
            elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                p["ext"] = ".webp"
            elif content[:6] in (b"GIF87a", b"GIF89a"):
                p["ext"] = ".gif"
            else:
                return self._json({"ok": False, "error": "JPG, PNG, WebP yoki GIF rasm tanlang"}, 400)
        candidates = []
        duplicates = []
        for f in files_in:
            if not f["content"]:
                return self._json({"ok": False, "error": "Bo'sh mod faylini yuklab bo'lmaydi"}, 400)
            if len(f["content"]) > MAX_FILE_BYTES:
                return self._json({"ok": False, "error": "Har bir fayl 50MB dan kichik bo'lsin"}, 400)
            f["sha256"] = hashlib.sha256(f["content"]).hexdigest()
            candidate = {"sha256": f["sha256"], "file_name": f["filename"]}
            match = storage.find_duplicate_file(candidate, candidates, exclude_mod_id=mid)
            if match:
                duplicates.append(dict(match, uploaded_name=f["filename"]))
            candidates.append(candidate)
        if duplicates and str(payload.get("allow_duplicate") or "") != "1":
            return self._json({"ok": False, "duplicates": duplicates,
                               "error": "Bu mod fayli allaqachon mavjud"}, 409)
        if (photos_in or files_in) and str(payload.get("confirm_replace") or "") != "1":
            return self._json({"ok": False, "confirm_replace": True,
                               "error": "Rasm yoki fayllarni almashtirishni tasdiqlang"}, 409)
        if photos_in:
            photos = []
            for p in photos_in:
                name = os.path.splitext(p["filename"])[0] + p["ext"]
                path = save_uploaded(p["content"], name, mid)
                photos.append({"file_id": "", "path": path})
            updates.update(photos=photos, cover_file=photos[0]["path"], cover_id="",
                           photo_revision=os.urandom(8).hex())
        if files_in:
            file_list = []
            for f in files_in:
                path = save_uploaded(f["content"], f["filename"], mid)
                file_list.append({"file_id": "", "file_unique_id": "", "file_name": f["filename"],
                                  "file_path": path, "sha256": f["sha256"]})
            updates["files"] = file_list
        text_changed = any(updates[key] != mod.get(key, "")
                           for key in ("name", "description") if key in updates)
        if text_changed:
            updates["tr"] = {}
        with storage._lock:
            mod.update(updates)
            storage.save_data()
        if photos_in or files_in:
            threading.Thread(target=self._persist_mod_media, args=(mid, user["id"]),
                             daemon=True).start()
        if text_changed:
            import translate
            translate.translate_mod_later(mid, delay=2)
        channel_updated = sync_mod_posts(mid, media_changed=bool(photos_in))
        favs = set((storage.get_user(user["id"]) or {}).get("favorites", []))
        return self._json({"ok": True, "mod": mod_json(mid, mod, favs, user_lang(user["id"])),
                           "channel_updated": channel_updated})

    def _admin_mod_add(self, payload, files, user):
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

        candidates = []
        duplicates = []
        for f in files_in:
            f["sha256"] = hashlib.sha256(f["content"]).hexdigest()
            candidate = {"sha256": f["sha256"], "file_name": f["filename"]}
            match = storage.find_duplicate_file(candidate, candidates)
            if match:
                duplicates.append(dict(match, uploaded_name=f["filename"]))
            candidates.append(candidate)
        if duplicates and str(payload.get("allow_duplicate") or "") != "1":
            return self._json({"ok": False, "duplicates": duplicates,
                               "error": "Bu mod fayli allaqachon mavjud"}, 409)

        mod_id = "mod_%d_%s" % (int(time.time()), os.urandom(2).hex())
        photos = []
        for p in photos_in:
            path = save_uploaded(p["content"], p["filename"] or "photo.jpg", mod_id)
            photos.append({"file_id": "", "path": path})
        file_list = []
        for f in files_in:
            path = save_uploaded(f["content"], f["filename"] or "file.zip", mod_id)
            file_list.append({"file_id": "", "file_name": f["filename"] or "fayl",
                              "file_path": path, "sha256": f["sha256"]})

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
        storage.save_data()
        threading.Thread(target=self._persist_mod_media, args=(mod_id, user["id"]),
                         daemon=True).start()
        import translate
        translate.translate_mod_later(mod_id, delay=3)

        published = False
        if str(payload.get("publish") or "") in ("1", "true", "on"):
            published = publish_mod(mod_id)
        return self._json({"ok": True, "mod": mod_json(mod_id, mod, set()), "published": published})

    def _persist_mod_media(self, mod_id, admin_id):
        """Yuklangan rasm/fayllarni Telegram'ga nusxalab file_id saqlash (disk tozalansa tiklanadi)."""
        try:
            mod = storage.data.get("mods", {}).get(mod_id)
            if not mod:
                return
            changed = False
            for p in mod.get("photos", []):
                path = p.get("path") or ""
                if p.get("file_id") or not (path and os.path.exists(path)):
                    continue
                res = tg.send_photo(admin_id, path, silent=True)
                sizes = (res.get("result") or {}).get("photo") or []
                if sizes:
                    p["file_id"] = sizes[-1].get("file_id", "")
                    if mod.get("photos") and mod["photos"][0] is p:
                        mod["cover_id"] = p["file_id"]
                    changed = True
            for f in mod.get("files", []):
                path = f.get("file_path") or ""
                if f.get("file_id") or not (path and os.path.exists(path)):
                    continue
                res = tg.send_document(admin_id, path, silent=True)
                document = (res.get("result") or {}).get("document") or {}
                fid = document.get("file_id")
                if fid:
                    f["file_id"] = fid
                    f["file_unique_id"] = document.get("file_unique_id", "")
                    changed = True
            if changed:
                storage.save_data()
        except Exception as e:
            print("Mod fayllarini zaxiralash xatosi:", e)

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
