import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import datetime
import urllib.parse
import uuid

import config

_lock = threading.RLock()
data = {}
_web_visits = {}
_web_lock = threading.Lock()
_dirty = {}
_backup = {"ts": 0}
_restored = {"done": False}


def backup_target():
    if config.BACKUP_CHAT_ID:
        return config.BACKUP_CHAT_ID
    return config.ADMIN_IDS[0] if config.ADMIN_IDS else 0


def was_restored():
    return _restored["done"]


def _default_data():
    return {
        "mods": {},
        "admins": list(config.ADMIN_IDS),
        "states": {},
        "channels": [config.CHANNEL_ID] if config.CHANNEL_ID else [],
        "users": {},
        "groups": {},
        "replies": {},
        "comments": {},
        "blocked": {},
        "messages": {},
    }


def _now():
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M")


def _ts():
    return int(time.time())


def load_data():
    with _lock:
        if os.path.exists(config.DATA_FILE):
            try:
                with open(config.DATA_FILE, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                if content:
                    d = json.loads(content)
                    if isinstance(d, dict):
                        for k, v in _default_data().items():
                            d.setdefault(k, v)
                        return d
            except json.JSONDecodeError:
                print("data.json bo'sh yoki buzuq — yangidan tiklandi.")
            except Exception as e:
                print("Data yuklash ogohlantirish:", e)
    d = _restore_from_telegram()
    if d is not None:
        return d
    return _default_data()


def _restore_from_telegram():
    """Render diski tozalanganda oxirgi zaxirani Telegram'dan qaytarish."""
    if not backup_target() or not config.BOT_TOKEN:
        return None
    try:
        import tg
        res = tg.get_chat(backup_target())
        if not res.get("ok"):
            return None
        msg = (res.get("result") or {}).get("pinned_message") or {}
        fid = (msg.get("document") or {}).get("file_id") or ""
        if not fid:
            return None
        tmp = config.DATA_FILE + ".restore"
        if not tg.download_file(fid, tmp):
            return None
        with open(tmp, "r", encoding="utf-8-sig") as f:
            d = json.loads(f.read())
        if not isinstance(d, dict) or "mods" not in d:
            return None
        for k, v in _default_data().items():
            d.setdefault(k, v)
        os.replace(tmp, config.DATA_FILE)
        _restored["done"] = True
        print("Telegram zaxirasidan tiklandi.")
        return d
    except Exception as e:
        print("Telegram'dan tiklash ogohlantirish:", e)
    return None


def save_data(backup=False):
    with _lock:
        try:
            tmp = config.DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, config.DATA_FILE)
        except Exception as e:
            print("Data saqlash xatosi:", e)
    if backup:
        backup_now()


def backup_now(admin_id=None, caption=None, force=False, wait=False):
    """data.json ni Telegram'ga yuborib pin qilish. 2 daqiqada bir martadan ko'p emas."""
    with _lock:
        now = _ts()
        if not force and now - _backup["ts"] < 120:
            return False
        _backup["ts"] = now
    try:
        save_data()
        import tg
        admin_id = admin_id or backup_target()
        if not admin_id:
            return False
        text = caption or ("💾 <b>ZAXIRA</b> — %s\n📦 Modlar: %d ta | 👥 Foydalanuvchilar: %d ta"
                           % (_now(), len(data.get("mods", {})), len(data.get("users", {}))))

        def _send():
            try:
                res = tg.send_document(admin_id, config.DATA_FILE, caption=text, silent=True)
                if not res.get("ok"):
                    print("Backup yuborilmadi:", res.get("description") or res.get("error"))
                    return False
                mid = (res.get("result") or {}).get("message_id")
                if mid:
                    tg.unpin_all(admin_id)
                    tg.pin_message(admin_id, mid)
                return True
            except Exception as e:
                print("Backup yuborish xatosi:", e)
                return False

        if wait:
            return bool(_send())
        threading.Thread(target=_send, daemon=True).start()
        return True
    except Exception as e:
        print("Backup xatosi:", e)
        return False


def migrate():
    """Eski botx.py data.json bilan moslik: yangi maydonlarni to'ldirish."""
    changed = False
    users = data.setdefault("users", {})
    for uid, u in users.items():
        if not isinstance(u, dict):
            users[uid] = {"name": str(u)}
            u = users[uid]
            changed = True
        if "last_seen" not in u:
            u["last_seen"] = u.get("date", _now())
            changed = True
        if "favorites" not in u:
            u["favorites"] = []
            changed = True
        if "settings" not in u:
            u["settings"] = {"theme": "dark", "sound": True, "bg": True}
            changed = True
        if "avatar" not in u:
            u["avatar"] = ""
            changed = True
        if "username" not in u:
            u["username"] = ""
            changed = True

    for mid, m in data.setdefault("mods", {}).items():
        if "photos" not in m:
            photos = []
            if m.get("cover_file"):
                photos.append({"file_id": m.get("cover_id", ""), "path": m.get("cover_file", "")})
            elif m.get("cover_id"):
                photos.append({"file_id": m.get("cover_id", ""), "path": ""})
            m["photos"] = photos
            changed = True

    for gid, g in data.setdefault("groups", {}).items():
        if "status" not in g:
            g["status"] = "active"
            changed = True
        if "is_admin" not in g:
            g["is_admin"] = False
            changed = True

    data.setdefault("blocked", {})
    if changed:
        save_data()


data = load_data()
migrate()


def now_str():
    return _now()


def now_ts():
    return _ts()


def parse_ts(date_str):
    try:
        return datetime.datetime.strptime(date_str, "%d.%m.%Y %H:%M").timestamp()
    except Exception:
        return 0


# ---------------- USERS ----------------
def track_user(user_id, name, username=None, inviter_id=None):
    uid = str(user_id)
    users = data.setdefault("users", {})
    user = users.get(uid)
    now = _now()
    if user is None:
        users[uid] = {
            "name": name,
            "username": username or "",
            "date": now,
            "last_seen": now,
            "inviter": inviter_id,
            "invited_count": 0,
            "favorites": [],
            "settings": {"theme": "dark", "sound": True, "bg": True},
            "avatar": "",
        }
        if inviter_id is not None and str(inviter_id) != uid and str(inviter_id) in users:
            inv = users[str(inviter_id)]
            inv["invited_count"] = inv.get("invited_count", 0) + 1
            try:
                import tg
                tg.send_message(int(inviter_id),
                                "🎉 <b>Yangi do'st!</b>\n\n👤 <b>%s</b> sizning havolangiz orqali kirdi!\n👥 Jami: <b>%d kishi</b>"
                                % (name, inv["invited_count"]))
            except Exception:
                pass
        save_data()
        return users[uid]
    user["last_seen"] = now
    if name and user.get("name") != name:
        user["name"] = name
    if username is not None and user.get("username") != username:
        user["username"] = username or ""
    save_data()
    return user


def touch_user(user_id, name=None, username=None):
    """Sayt har bir so'rovida data.json yozmaslik uchun yengil yangilash."""
    uid = str(user_id)
    user = data.get("users", {}).get(uid)
    if user is None:
        return track_user(user_id, name or "Foydalanuvchi", username=username)
    user["last_seen"] = _now()
    if name and user.get("name") != name:
        user["name"] = name
    if username is not None and user.get("username") != (username or ""):
        user["username"] = username or ""
    with _lock:
        now = _ts()
        if now - _dirty.get("ts", 0) >= 20:
            _dirty["ts"] = now
            need_save = True
        else:
            need_save = False
    if need_save:
        save_data()
    return user


def get_user(user_id):
    return data.get("users", {}).get(str(user_id))


def is_admin(user_id):
    try:
        return int(user_id) in data.get("admins", config.ADMIN_IDS)
    except Exception:
        return False


def is_blocked(user_id):
    return str(user_id) in data.get("blocked", {})


def block_user(user_id, name=""):
    uid = str(user_id)
    if int(user_id) in data.get("admins", config.ADMIN_IDS):
        return False
    data.setdefault("blocked", {})[uid] = {"name": name or str(user_id), "date": _now()}
    save_data()
    return True


def unblock_user(user_id):
    uid = str(user_id)
    if uid in data.get("blocked", {}):
        del data["blocked"][uid]
        save_data()
        return True
    return False


def toggle_favorite(user_id, mod_id):
    user = get_user(user_id)
    if not user:
        return False
    favs = user.setdefault("favorites", [])
    if mod_id in favs:
        favs.remove(mod_id)
        saved = False
    else:
        favs.append(mod_id)
        saved = True
    save_data()
    return saved


def set_settings(user_id, settings):
    user = get_user(user_id)
    if not user:
        return None
    cur = user.setdefault("settings", {"theme": "dark", "sound": True, "bg": True})
    for k in ("theme", "sound", "bg", "lang", "font"):
        if k in settings and settings[k] is not None:
            cur[k] = settings[k]
    save_data()
    return cur


# ---------------- XABARLAR (site chat) ----------------
def add_message(user_id, frm, text, photo=None):
    box = data.setdefault("messages", {}).setdefault(str(user_id), [])
    item = {"id": uuid.uuid4().hex, "from": frm, "text": str(text)[:1500],
            "date": _now(), "read": frm == "user"}
    if photo is not None:
        item["photo"] = {"file_id": photo.get("file_id") or "", "path": photo.get("path") or ""}
    box.append(item)
    save_data()
    return item


def get_messages(user_id):
    return list(data.get("messages", {}).get(str(user_id), []))


def unread_messages(user_id):
    return sum(1 for m in data.get("messages", {}).get(str(user_id), [])
               if m.get("from") == "admin" and not m.get("read"))


def mark_messages_read(user_id):
    box = data.get("messages", {}).get(str(user_id))
    if not box:
        return
    changed = False
    for m in box:
        if m.get("from") == "admin" and not m.get("read"):
            m["read"] = True
            changed = True
    if changed:
        save_data()


def find_avatar_file_id(file_name):
    """Avatar fayli diskdan o'chgan bo'lsa, Telegram'dagi nusxasini topish."""
    name = os.path.basename(file_name or "")
    if not name:
        return ""
    for u in data.get("users", {}).values():
        if os.path.basename(u.get("avatar") or "") == name:
            return u.get("avatar_file_id") or ""
    return ""


def live_users_count(days=None):
    days = days if days is not None else config.LIVE_USER_DAYS
    cutoff = time.time() - days * 86400
    blocked = data.get("blocked", {})
    cnt = 0
    for uid, u in data.get("users", {}).items():
        if uid in blocked:
            continue
        if parse_ts(u.get("last_seen", "")) >= cutoff:
            cnt += 1
    return cnt


def user_counts():
    users = data.get("users", {})
    blocked = data.get("blocked", {})
    deleted = sum(1 for uid, u in users.items()
                  if uid not in blocked and u.get("tg_status") == "deleted")
    active = sum(1 for uid, u in users.items()
                 if uid not in blocked and u.get("tg_status") != "deleted")
    return {"total": len(users), "active": active, "deleted": deleted}


def mark_user_status(user_id, status, save=True):
    user = data.get("users", {}).get(str(user_id))
    if user is None or user.get("tg_status") == status:
        return
    user["tg_status"] = status
    if save:
        save_data()


def live_groups():
    return {gid: g for gid, g in data.get("groups", {}).items()
            if g.get("status", "active") == "active" and g.get("is_admin")}


def track_group(chat, is_admin=None):
    if chat.get("type") not in ("group", "supergroup"):
        return
    gid = str(chat["id"])
    title = chat.get("title", "Noma'lum guruh")
    groups = data.setdefault("groups", {})
    g = groups.get(gid)
    if not g:
        groups[gid] = {"title": title, "date": _now(), "status": "active",
                       "is_admin": bool(is_admin)}
        save_data()
        return
    changed = False
    if g.get("title") != title:
        g["title"] = title
        changed = True
    if g.get("status") != "active":
        g["status"] = "active"
        changed = True
    if is_admin is not None and g.get("is_admin") != bool(is_admin):
        g["is_admin"] = bool(is_admin)
        changed = True
    if changed:
        save_data()


def set_group_admin(chat_id, is_admin):
    g = data.get("groups", {}).get(str(chat_id))
    if g is not None and g.get("is_admin") != bool(is_admin):
        g["is_admin"] = bool(is_admin)
        save_data()


def untrack_group(chat_id):
    gid = str(chat_id)
    g = data.get("groups", {}).get(gid)
    if g:
        g["status"] = "removed"
        g["is_admin"] = False
        save_data()


# ---------------- STATES ----------------
def get_state(user_id):
    return data.get("states", {}).get(str(user_id), {})


def discard_pending_duplicate(sd, keep_files=()):
    pending = sd.get("pending_duplicate") or {}
    token = pending.get("token") or ""
    path = (pending.get("file") or {}).get("file_path") or ""
    if not re.fullmatch(r"[0-9a-f]{32}", token) or not path:
        return
    if (os.path.dirname(os.path.realpath(path)) != os.path.realpath(config.MODS_DIR)
            or not os.path.basename(path).startswith("upload_%s_" % token)):
        return
    retained = list(keep_files) + list(sd.get("files") or [])
    for mod in data.get("mods", {}).values():
        retained.extend(mod.get("files") or [])
    if any(os.path.realpath(f.get("file_path") or "") == os.path.realpath(path) for f in retained):
        return
    try:
        os.remove(path)
    except OSError:
        pass


def set_state(user_id, state, extra=None):
    old = get_state(user_id).get("data", {})
    pending = old.get("pending_duplicate")
    if pending and (state != "upload_files" or pending != (extra or {}).get("pending_duplicate")):
        discard_pending_duplicate(old, (extra or {}).get("files") or [])
    data.setdefault("states", {})[str(user_id)] = {"state": state, "data": extra or {}}
    save_data()


def clear_state(user_id):
    if str(user_id) in data.get("states", {}):
        discard_pending_duplicate(get_state(user_id).get("data", {}))
        del data["states"][str(user_id)]
        save_data()


# ---------------- REPLIES ----------------
def register_reply(admin_msg_id, chat_id, user_id, user_name):
    data.setdefault("replies", {})[str(admin_msg_id)] = {
        "chat_id": chat_id, "user_id": user_id, "user_name": user_name
    }
    save_data()


def get_reply(message):
    rt = message.get("reply_to_message")
    if not rt:
        return None
    return data.get("replies", {}).get(str(rt.get("message_id")))


# ---------------- WEB ONLINE ----------------
def register_web_visit(user_id):
    with _web_lock:
        _web_visits[str(user_id)] = time.time()


def web_live_count():
    cutoff = time.time() - config.WEB_LIVE_SECONDS
    with _web_lock:
        return sum(1 for t in _web_visits.values() if t >= cutoff)


# ---------------- MODS HELPERS ----------------
def mod_visible(mod, user_id=None):
    return not mod.get("hidden") or (user_id is not None and is_admin(user_id))


def mod_link_id(mid, mod):
    return mod.get("link_id") or mid


def mod_link(mid, mod):
    return "https://t.me/%s?start=%s" % (config.BOT_USERNAME, mod_link_id(mid, mod))


def find_mod_by_link(param):
    mods = data.get("mods", {})
    if param in mods:
        return param
    for mid, m in mods.items():
        if m.get("link_id") == param:
            return mid
    return None


def mod_editions(mod):
    editions = set()
    for text in (mod.get("description") or "", mod.get("name") or ""):
        if re.search(r"\bjava\b", text, re.IGNORECASE):
            editions.add("java")
        if re.search(r"\b(?:bedrock|mcpe|pocket\s+edition)\b", text, re.IGNORECASE):
            editions.add("bedrock")
        if editions:
            break
    if not editions:
        for record in mod.get("files") or []:
            ext = os.path.splitext(record.get("file_name") or record.get("file_path") or "")[1].lower()
            if ext == ".jar":
                editions.add("java")
            elif ext in (".mcaddon", ".mcpack", ".mcworld"):
                editions.add("bedrock")
    return [edition for edition in ("java", "bedrock") if edition in editions]


def file_sha256(record):
    cached = record.get("sha256") or ""
    if cached:
        return cached
    path = record.get("file_path") or ""
    if not path:
        return ""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        record["sha256"] = digest.hexdigest()
        return record["sha256"]
    except (OSError, TypeError, ValueError):
        return ""


def find_duplicate_file(candidate, pending_files=(), exclude_mod_id=None):
    sha256 = file_sha256(candidate)

    def matches(record):
        for key in ("file_unique_id", "file_id"):
            value = candidate.get(key)
            if value and value == record.get(key):
                return True
        existing_sha256 = file_sha256(record) if sha256 else ""
        return bool(sha256 and existing_sha256 and sha256.lower() == existing_sha256.lower())

    for record in pending_files:
        if matches(record):
            return {"mod_id": "", "name": "Joriy yuklash", "file_name": record.get("file_name") or ""}
    for mod_id, mod in data.get("mods", {}).items():
        if mod_id == exclude_mod_id:
            continue
        for record in mod.get("files") or []:
            if matches(record):
                return {"mod_id": mod_id, "name": mod.get("name") or "Joriy yuklash",
                        "file_name": record.get("file_name") or ""}
    return None


def mod_photos(m):
    photos = m.get("photos") or []
    out = []
    for p in photos:
        if isinstance(p, dict):
            out.append(p)
        elif isinstance(p, str):
            out.append({"file_id": "", "path": p})
    if not out and m.get("cover_file"):
        out.append({"file_id": m.get("cover_id", ""), "path": m.get("cover_file", "")})
    return out


def safe_filename(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "file")


LINK_FILE_EXTS = (".zip", ".mcpack", ".mcaddon", ".mcworld", ".jar", ".rar", ".7z")
LINK_MAX_BYTES = 50 * 1024 * 1024


def _public_ip(ip):
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    pinned_ip = None
    tls_hostname = None

    def connect(self):
        sock = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        self.sock = self._context.wrap_socket(sock, server_hostname=self.tls_hostname)


def download_link_file(url, dest_path, max_bytes=LINK_MAX_BYTES):
    """Havoladagi mod faylini xavfsiz yuklab olish. (True, nom) yoki (False, xato)."""
    try:
        parts = urllib.parse.urlsplit(str(url).strip())
    except ValueError:
        return False, "Havola noto'g'ri"
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return False, "Faqat https fayl havolasi qabul qilinadi"
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False, "Havola manzili topilmadi"
    ips = {info[4][0] for info in infos}
    if not ips or not all(_public_ip(ip) for ip in ips):
        return False, "Bu havolaga ruxsat yo'q"
    path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    conn = _PinnedHTTPSConnection(parts.hostname, parts.port or 443, timeout=30,
                                  context=ssl.create_default_context())
    conn.pinned_ip = sorted(ips)[0]
    conn.tls_hostname = parts.hostname
    ok = False
    try:
        conn.request("GET", path, headers={
            "Host": parts.netloc, "User-Agent": "UZBMCBOT/1.0", "Accept": "*/*"})
        resp = conn.getresponse()
        if resp.status != 200:
            return False, "Havola fayl qaytarmadi (HTTP %d)" % resp.status
        ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if ctype.startswith("text/") or ctype in ("application/json", "application/xhtml+xml"):
            return False, "Havola to'g'ridan-to'g'ri fayl emas"
        name = ""
        disposition = resp.getheader("Content-Disposition") or ""
        match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.IGNORECASE)
        if match:
            name = urllib.parse.unquote(match.group(1).strip().strip('"'))
        if not name:
            name = urllib.parse.unquote(os.path.basename(parts.path))
        name = safe_filename(name)[:120]
        if os.path.splitext(name)[1].lower() not in LINK_FILE_EXTS:
            return False, "Fayl turi mos emas (.mcaddon, .mcpack, .zip, .jar ...)"
        total = 0
        with open(dest_path, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    return False, "Fayl 50MB dan katta"
                out.write(chunk)
        if not total:
            return False, "Havola bo'sh fayl qaytardi"
        ok = True
        return True, name
    except Exception:
        return False, "Fayl yuklab olinmadi"
    finally:
        conn.close()
        if not ok and os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
