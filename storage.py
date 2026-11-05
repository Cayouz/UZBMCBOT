import json
import os
import re
import threading
import time
import datetime

import config

_lock = threading.RLock()
data = {}
_web_visits = {}
_web_lock = threading.Lock()
_dirty = {}


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
        return _default_data()


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
        try:
            import tg
            admin_id = config.ADMIN_IDS[0]
            def _bg():
                try:
                    tg.send_document(admin_id, config.DATA_FILE,
                                     caption="💾 <b>ZAXIRA:</b> Barcha modlar va ma'lumotlar saqlandi.")
                except Exception as e2:
                    print("Auto backup error:", e2)
            threading.Thread(target=_bg, daemon=True).start()
        except Exception:
            pass


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
    for k in ("theme", "sound", "bg"):
        if k in settings:
            cur[k] = settings[k]
    save_data()
    return cur


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


def live_groups():
    return {gid: g for gid, g in data.get("groups", {}).items() if g.get("status", "active") == "active"}


def track_group(chat):
    if chat.get("type") not in ("group", "supergroup"):
        return
    gid = str(chat["id"])
    title = chat.get("title", "Noma'lum guruh")
    groups = data.setdefault("groups", {})
    g = groups.get(gid)
    if not g:
        groups[gid] = {"title": title, "date": _now(), "status": "active"}
        save_data()
    elif g.get("title") != title or g.get("status") != "active":
        g["title"] = title
        g["status"] = "active"
        save_data()


def untrack_group(chat_id):
    gid = str(chat_id)
    g = data.get("groups", {}).get(gid)
    if g:
        g["status"] = "removed"
        save_data()


# ---------------- STATES ----------------
def get_state(user_id):
    return data.get("states", {}).get(str(user_id), {})


def set_state(user_id, state, extra=None):
    data.setdefault("states", {})[str(user_id)] = {"state": state, "data": extra or {}}
    save_data()


def clear_state(user_id):
    if str(user_id) in data.get("states", {}):
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
