import datetime
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from html import escape

import config
import storage
import tg

PAGE_SIZE = 8
BLOCKED_MSG = "Siz bloklangansiz iltimos admin bilan bo'g'laning : @" + config.SUPPORT_USERNAME

_bot_id = {"id": 0}
_group_admin_cache = {}


def bot_identity():
    if not _bot_id["id"]:
        res = tg.api_request("getMe")
        if res.get("ok"):
            _bot_id["id"] = res["result"].get("id", 0)
    return _bot_id["id"]


def check_bot_admin(chat_id, refresh=False):
    """Bot shu guruhda adminmi? 5 daqiqa kesh, chiqarib yuborilsa darhol o'chadi."""
    key = str(chat_id)
    now = time.time()
    cached = _group_admin_cache.get(key)
    if cached and not refresh and now - cached[0] < 300:
        return cached[1]
    bid = bot_identity()
    if not bid:
        return bool(cached and cached[1])
    res = tg.api_request("getChatMember", {"chat_id": chat_id, "user_id": bid})
    status = (res.get("result") or {}).get("status", "") if res.get("ok") else ""
    if status in ("left", "kicked"):
        storage.untrack_group(chat_id)
        _group_admin_cache.pop(key, None)
        return False
    ok = status in ("administrator", "creator")
    storage.set_group_admin(chat_id, ok)
    _group_admin_cache[key] = (now, ok)
    return ok


def refresh_groups():
    for gid in list(storage.data.get("groups", {}).keys()):
        g = storage.data["groups"].get(gid) or {}
        if g.get("status") != "active":
            continue
        try:
            check_bot_admin(gid, refresh=True)
        except Exception as e:
            print("Guruh tekshiruvi xatosi (%s): %s" % (gid, e))


# ============ KLAVIATURALAR ============
def main_keyboard(admin=False):
    rows = [
        [tg.button(config.B_MODS), tg.button(config.B_HELP)],
        [tg.button(config.B_REF), tg.button(config.B_GUIDE)],
    ]
    if config.WEBAPP_URL:
        rows.append([tg.button("🌐 Saytni ochish", web_app=config.WEBAPP_URL)])
    if admin:
        rows.append([tg.button(config.B_UPLOAD), tg.button(config.B_ADMIN)])
        rows.append([tg.button(config.B_PANEL)])
    return tg.reply_kb(rows)


def cancel_keyboard():
    return tg.reply_kb([[tg.button(config.B_CANCEL)]])


def photos_keyboard():
    return tg.reply_kb([[tg.button(config.B_PHOTOS_DONE), tg.button(config.B_CANCEL)]])


def files_keyboard():
    return tg.reply_kb([[tg.button(config.B_FILE_ADD), tg.button(config.B_FILES_DONE)],
                        [tg.button(config.B_CANCEL)]])


def categories_kb():
    rows = []
    items = config.CATEGORIES
    for i in range(0, len(items), 2):
        row = [tg.button(items[i]["icon"] + " " + items[i]["name"],
                         callback_data="cat_" + items[i]["id"])]
        if i + 1 < len(items):
            row.append(tg.button(items[i + 1]["icon"] + " " + items[i + 1]["name"],
                                 callback_data="cat_" + items[i + 1]["id"]))
        rows.append(row)
    return tg.inline_kb(rows)


def upload_category_kb():
    rows = []
    items = config.MOD_CATEGORIES
    for i in range(0, len(items), 2):
        row = [tg.button(items[i]["icon"] + " " + items[i]["name"],
                         callback_data="cat_select_" + items[i]["id"])]
        if i + 1 < len(items):
            row.append(tg.button(items[i + 1]["icon"] + " " + items[i + 1]["name"],
                                 callback_data="cat_select_" + items[i + 1]["id"]))
        rows.append(row)
    return tg.inline_kb(rows)


def panel_keyboard():
    rows = [
        [tg.button("➕ Admin qo'shish", callback_data="panel_admin_add"),
         tg.button("➖ Admin olib tashlash", callback_data="panel_admin_del")],
        [tg.button("📤 Mod qo'shish", callback_data="panel_mod_add"),
         tg.button("🗑️ Mod olib tashlash", callback_data="panel_mod_del")],
        [tg.button("✏️ Mod Tahrirlash", callback_data="panel_mod_edit"),
         tg.button("📢 Obuna kanallari", callback_data="panel_channels")],
        [tg.button("🚫 Bloklash", callback_data="panel_block"),
         tg.button("✅ Blokdan chiqarish", callback_data="panel_unblock")],
        [tg.button("📢 Xabar tarqatish", callback_data="panel_broadcast"),
         tg.button("📊 Statistika", callback_data="panel_stats")],
        [tg.button("💾 Zaxira olish", callback_data="panel_backup"),
         tg.button("🔄 Yangilash", callback_data="panel_refresh")],
        [tg.button("❌ Yopish", callback_data="panel_close")],
    ]
    return tg.inline_kb(rows)


# ============ MATNLAR ============
def category_name(cat_id):
    c = config.CATEGORY_MAP.get(cat_id)
    return (c["icon"] + " " + c["name"]) if c else cat_id


def panel_text():
    d = storage.data
    total_dl = sum(m.get("downloads", 0) for m in d.get("mods", {}).values())
    info = "🛠️ <b>ADMIN PANEL</b>\n\n"
    info += "📦 Modlar soni: <b>%d ta</b>\n" % len(d.get("mods", {}))
    info += "⬇️ Jami yuklanishlar: <b>%d marta</b>\n" % total_dl
    info += "👤 Adminlar: <b>%d kishi</b>\n" % len(d.get("admins", []))
    info += "👥 Jonli foydalanuvchilar: <b>%d ta</b>\n" % storage.live_users_count()
    info += "🌐 Hozir saytda: <b>%d</b>\n" % storage.web_live_count()
    info += "💬 Jonli guruhlar: <b>%d ta</b>\n" % len(storage.live_groups())
    info += "🚫 Bloklanganlar: <b>%d ta</b>\n" % len(d.get("blocked", {}))
    info += "📢 Obuna kanallari: <b>%d ta</b>\n\n" % len(d.get("channels", []))
    info += "⚙️ <b>Qulay buyruqlar:</b>\n📤 /upload - Mod yuklash\n👤 /admin - Admin qo'shish\n"
    info += "📢 /broadcast - Xabar tarqatish\n📊 /stats - Statistika\n📢 /channels - Obuna kanallari"
    return info


def refresh_user_statuses():
    users = storage.data.get("users", {})
    blocked = storage.data.get("blocked", {})
    targets = [uid for uid in users if uid not in blocked]

    def worker(uid):
        res = tg.get_chat(int(uid), timeout=10)
        if res.get("ok"):
            storage.mark_user_status(uid, "active")
        elif res.get("error_code") == 400 and "user not found" in str(res.get("description", "")).lower():
            storage.mark_user_status(uid, "deleted")

    if targets:
        with ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(worker, targets))


def stats_text():
    d = storage.data
    total_dl = sum(m.get("downloads", 0) for m in d.get("mods", {}).values())
    groups = storage.live_groups()
    counts = storage.user_counts()
    t = "📊 <b>BOT STATISTIKASI</b>\n\n"
    t += "⬛ Foydalanuvchilar: <b>%d</b>\n" % counts["total"]
    t += "⬜ Faol: <b>%d</b>\n" % counts["active"]
    t += "⬜ O'chirilgan: <b>%d</b>\n\n" % counts["deleted"]
    t += "👥 Jonli foydalanuvchilar: <b>%d ta</b>\n" % storage.live_users_count()
    t += "🌐 Hozir saytda: <b>%d</b>\n" % storage.web_live_count()
    t += "💬 Jonli guruhlar: <b>%d ta</b>\n" % len(groups)
    t += "📦 Modlar: <b>%d ta</b>\n" % len(d.get("mods", {}))
    t += "⬇️ Yuklanishlar: <b>%d marta</b>\n" % total_dl
    t += "🚫 Bloklanganlar: <b>%d ta</b>\n\n" % len(d.get("blocked", {}))
    if groups:
        t += "🌐 <b>Bot ishlayotgan guruhlar:</b>\n"
        for g in list(groups.values())[-10:]:
            t += "🔹 %s\n" % escape(g.get("title", "Noma'lum"))
    else:
        t += "🌐 Bot hali guruhlarda ishlamayapti."
    return t


def show_admin_panel(chat_id, message_id=None):
    if message_id is not None:
        tg.edit_message(chat_id, message_id, panel_text(), panel_keyboard())
    else:
        tg.send_message(chat_id, panel_text(), panel_keyboard())


def show_stats(chat_id, message_id=None):
    refresh_user_statuses()
    rows = [[tg.button("🔄 Yangilash", callback_data="panel_stats")],
            [tg.button("🔙 Panelga qaytish", callback_data="panel_back")]]
    if message_id is not None:
        tg.edit_message(chat_id, message_id, stats_text(), tg.inline_kb(rows))
    else:
        tg.send_message(chat_id, stats_text(), tg.inline_kb(rows))


def show_channels(chat_id, message_id=None):
    d = storage.data
    chans = d.get("channels", [])
    if chans:
        t = "📢 <b>Majburiy obuna kanallari:</b>\n\n"
        for i, ch in enumerate(chans, 1):
            t += "%d. <code>%s</code>\n" % (i, ch)
        t += "\nO'chirish uchun ustiga bosing yoki yangi kanal qo'shing:"
    else:
        t = "📢 Majburiy kanallar belgilanmagan.\n\n➕ Yangi kanal qo'shishingiz mumkin:"
    rows = [[tg.button("🗑️ " + str(ch), callback_data="chdel_" + str(ch))] for ch in chans]
    rows.append([tg.button("➕ Kanal qo'shish", callback_data="channel_add_btn")])
    rows.append([tg.button("🔙 Panelga qaytish", callback_data="panel_back")])
    kb = tg.inline_kb(rows)
    if message_id is not None:
        tg.edit_message(chat_id, message_id, t, kb)
    else:
        tg.send_message(chat_id, t, kb)


def show_blocked_list(chat_id, message_id=None):
    d = storage.data
    blocked = d.get("blocked", {})
    rows = []
    if blocked:
        t = "🚫 <b>Bloklangan foydalanuvchilar:</b>\n\nOlib tashlash uchun ustiga bosing:"
        for uid, b in list(blocked.items())[-30:]:
            rows.append([tg.button("✅ %s — %s" % (b.get("name", ""), uid),
                                   callback_data="unblock_" + str(uid))])
    else:
        t = "✅ Bloklangan foydalanuvchilar yo'q."
    rows.append([tg.button("🔙 Panelga qaytish", callback_data="panel_back")])
    kb = tg.inline_kb(rows)
    if message_id is not None:
        tg.edit_message(chat_id, message_id, t, kb)
    else:
        tg.send_message(chat_id, t, kb)


# ============ OBUNA ============
def check_channels(user_id):
    missing = []
    for ch in storage.data.get("channels", []):
        res = tg.api_request("getChatMember", {"chat_id": ch, "user_id": user_id})
        if res.get("ok"):
            st = res.get("result", {}).get("status", "")
            if st not in ("member", "administrator", "creator"):
                missing.append(ch)
        else:
            missing.append(ch)
    return missing


def is_subscribed(user_id):
    if storage.is_admin(user_id):
        return True
    return len(check_channels(user_id)) == 0


def subscription_keyboard(missing):
    rows = []
    for ch in missing:
        s = str(ch)
        url = "https://t.me/" + (s[1:] if s.startswith("@") else s)
        rows.append([tg.button("📢 " + s, url=url)])
    rows.append([tg.button("Obunani tekshirish ♻️", callback_data="check_subscription")])
    return tg.inline_kb(rows)


def send_subscription_warning(chat_id, missing):
    t = "⚠️ <b>Siz kanallarga obuna bo'lmagansiz</b> ⚠️\n\n"
    t += "❗️ <b>Iltimos obuna bo'lib quyidagi tugmani bosing</b> ❗️"
    tg.send_message(chat_id, t, subscription_keyboard(missing))


# ============ MODLAR KO'RINISHI ============
def category_items(user_id, cat_id):
    d = storage.data
    mods = {mid: mod for mid, mod in d.get("mods", {}).items() if storage.mod_visible(mod, user_id)}
    if cat_id == "favorites":
        favs = (storage.get_user(user_id) or {}).get("favorites", [])
        return [(mid, m) for mid, m in mods.items() if mid in favs]
    if cat_id == "all":
        return list(mods.items())
    return [(mid, m) for mid, m in mods.items() if m.get("category") == cat_id]


def show_categories(chat_id, message_id=None):
    t = "📦 <b>Modlar bo'limi</b>\n\nKategoriyani tanlang:"
    if message_id is not None:
        tg.edit_message(chat_id, message_id, t, categories_kb())
    else:
        tg.send_message(chat_id, t, categories_kb())


def show_category(chat_id, user_id, cat_id, page=0, message_id=None):
    items = category_items(user_id, cat_id)
    items = list(reversed(items))
    total = len(items)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    title = category_name(cat_id)
    t = "%s <b>%s</b>\n\n" % (title, "— %d ta mod" % total if total else "— bo'sh")
    if not total:
        t += "📭 Bu kategoriyada hozircha modlar yo'q."
    rows = []
    for mid, m in chunk:
        label = "⬇️ %s (%s)" % (m.get("name", "Nomsiz"), m.get("downloads", 0))
        rows.append([tg.button(label, callback_data="mod_" + mid)])
    nav = []
    if page > 0:
        nav.append(tg.button("◀️", callback_data="catpage_%s_%d" % (cat_id, page - 1)))
    if page < pages - 1:
        nav.append(tg.button("▶️", callback_data="catpage_%s_%d" % (cat_id, page + 1)))
    if nav:
        rows.append(nav)
    rows.append([tg.button("🔙 Kategoriyalar", callback_data="cat_menu")])
    kb = tg.inline_kb(rows)
    if message_id is not None:
        tg.edit_message(chat_id, message_id, t, kb)
    else:
        tg.send_message(chat_id, t, kb)


def send_mod_detail(chat_id, user_id, mod_id):
    d = storage.data
    mod = d.get("mods", {}).get(mod_id)
    if not mod or not storage.mod_visible(mod, user_id):
        tg.send_message(chat_id, "Mod topilmadi.")
        return
    mod["downloads"] = mod.get("downloads", 0) + 1
    storage.save_data()

    photos = storage.mod_photos(mod)
    cat = category_name(mod.get("category", ""))
    caption = "<b>%s</b>\n\n%s\n\n📂 %s\n⬇️ Yuklanishlar: %d" % (
        escape(mod.get("name", "")), escape(mod.get("description", "") or "Tavsif yo'q"),
        cat, mod.get("downloads", 0))
    if photos:
        tg.send_media_group(chat_id, photos, caption)
    else:
        tg.send_message(chat_id, caption)

    favs = (storage.get_user(user_id) or {}).get("favorites", [])
    is_fav = mod_id in favs
    rows = [
        [tg.button("⬇️ Yuklab olish", callback_data="moddl_" + mod_id),
         tg.button("❤️ Saqlangan" if is_fav else "🤍 Saqlash",
                   callback_data="modfav_" + mod_id)],
    ]
    if storage.is_admin(user_id):
        rows.append([tg.button("📢 Kanalga joylash", callback_data="publish_" + mod_id)])
    rows.append([tg.button("🔙 Kategoriyaga qaytish",
                           callback_data="cat_" + mod.get("category", "all"))])
    tg.send_message(chat_id, "📥 Yuklab olish uchun tugmani bosing:", tg.inline_kb(rows))


def send_mod_files(chat_id, mod_id, user_id=None):
    mod = storage.data.get("mods", {}).get(mod_id)
    if not mod or not storage.mod_visible(mod, user_id):
        tg.send_message(chat_id, "Mod topilmadi.")
        return
    files = mod.get("files", [])
    if not files:
        tg.send_message(chat_id, "📭 Bu modda fayllar yo'q.")
        return
    for f in files:
        path = f.get("file_path") or ""
        fid = f.get("file_id") or ""
        name = f.get("file_name", "fayl")
        if path and os.path.exists(path):
            tg.send_document(chat_id, path, "📦 " + escape(name))
        elif fid:
            tg.send_document(chat_id, fid, "📦 " + escape(name))


# ============ QO'LLANMA / REF / HELP ============
def send_guide(chat_id):
    guide_msg = (
        "📖 <b>MINECRAFT MODLARINI O'RNATISH QO'LLANMASI</b>\n\n"
        "📱 <b>Android:</b>\n"
        "1. Mod faylini (<code>.mcaddon</code> / <code>.mcpack</code>) yuklab oling.\n"
        "2. ZArchiver orqali faylni bosing ➔ <i>'Minecraft bilan ochish'</i>.\n"
        "3. O'yin avtomatik o'rnatadi.\n"
        "<i>💡 Fayl <code>.zip</code> bo'lsa, nomini <code>.mcaddon</code> qiling.</i>\n\n"
        "🍎 <b>iOS:</b>\n1. Faylni 'Fayllar' ilovasiga saqlang.\n"
        "2. Uzoq bosib <i>'Uzatish'</i> ➔ Minecraft.\n\n"
        "💻 <b>PC:</b>\n1. <code>.mcaddon</code> fayl ustiga 2 marta bosing."
    )
    tg.send_message(chat_id, guide_msg)


def send_ref(chat_id, user_id):
    u = storage.get_user(user_id) or {}
    cnt = u.get("invited_count", 0)
    ref_link = "https://t.me/%s?start=ref_%s" % (config.BOT_USERNAME, user_id)
    msg = ("🎁 <b>TAKLIFA HAVOLASI</b>\n\n"
           "👤 <b>Sizning ID:</b> <code>%s</code>\n"
           "👥 <b>Taklif qilganlaringiz:</b> <b>%d kishi</b>\n\n"
           "🔗 <b>Havolangiz:</b>\n<code>%s</code>\n\n"
           "💡 <i>Havolani do'stlaringizga yuboring — ular botga kirsa sizga xabar keladi!</i>"
           % (user_id, cnt, ref_link))
    share_url = ("https://t.me/share/url?url=%s&text=%s" % (
        ref_link, "Minecraft modlarini bepul yuklab oling! 🚀"))
    tg.send_message(chat_id, msg, tg.inline_kb([[tg.button("📋 Ulashish", url=share_url)]]))


def send_welcome(chat_id, user_id, user_name):
    welcome = ("Salom, <b>%s</b> 👋!\n"
               "🎉 <b>Minecraft Mod Botga xush kelibsiz!</b>\n\n"
               "🤖 <b>Buyruqlar:</b>\n"
               "/start - Qayta boshlash ♻️\n"
               "/mods - Modlar bo'limi 📦\n"
               "/guide - O'rnatish qo'llanmasi 📖\n"
               "/ref - Do'stlarni taklif qilish 🎁\n"
               "/help - Adminga yozish 📝\n" % escape(user_name))
    if storage.is_admin(user_id):
        welcome += ("/upload - Mod yuklash 📤\n/admin - Admin qo'shish 👤\n"
                    "/broadcast - Xabar tarqatish 📢\n/panel - Admin panel 🛠️\n")
    welcome += "\n🌐 Kanal: @%s" % config.CHANNEL_USERNAME
    tg.send_message(chat_id, welcome, main_keyboard(storage.is_admin(user_id)))


def process_start_payload(chat_id, user_id, user_name, param):
    if param.startswith("ref_"):
        try:
            inv = int(param.replace("ref_", ""))
        except ValueError:
            inv = None
        storage.track_user(user_id, user_name, inviter_id=inv)
        return False
    if param.startswith("mod_"):
        send_mod_detail(chat_id, user_id, param)
        return True
    return False


# ============ UPLOAD ============
def start_upload(chat_id, user_id):
    storage.set_state(user_id, "upload_photos", {"photos": [], "files": []})
    tg.send_message(chat_id,
                    "📬 <b>Yangi mod qo'shish</b>\n\n"
                    "<b>1-qadam: Rasmlarni yuboring (1 tadan %d tagacha).</b>\n"
                    "Tayyor bo'lgach <b>%s</b> tugmasini bosing." % (
                        config.MAX_UPLOAD_PHOTOS, config.B_PHOTOS_DONE),
                    photos_keyboard())


def download_photo(file_id, user_id, idx):
    path = os.path.join(config.MODS_DIR, "photo_%s_%d_%d.jpg" % (
        user_id, int(time.time()), idx))
    if tg.download_file(file_id, path):
        return path
    return ""


def add_link_file(chat_id, user_id, sd, url):
    if len(sd.get("files", [])) >= config.MAX_MOD_FILES:
        tg.send_message(chat_id, "⚠️ Maksimum %d ta fayl." % config.MAX_MOD_FILES)
        return
    if sd.get("pending_duplicate"):
        tg.send_message(chat_id, "Avval takroriy fayl uchun qaror qiling yoki yuklashni yakunlang.")
        return
    token = uuid.uuid4().hex
    fp = os.path.join(config.MODS_DIR, "upload_%s_link" % token)
    ok, result = storage.download_link_file(url, fp)
    if not ok:
        tg.send_message(chat_id, "❌ %s" % result, files_keyboard())
        return
    candidate = {"file_id": "", "file_unique_id": "", "file_name": result, "file_path": fp}
    if not storage.file_sha256(candidate):
        tg.send_message(chat_id, "❌ Fayl yuklab olinmadi. Qayta yuboring.", files_keyboard())
        return
    duplicate = storage.find_duplicate_file(candidate, sd.get("files") or [])
    if duplicate:
        sd["pending_duplicate"] = {"token": token, "file": candidate}
        storage.set_state(user_id, "upload_files", sd)
        kb = tg.inline_kb([[tg.button("Baribir qo‘shish", callback_data="dup_add_" + token),
                            tg.button("Qo‘shmaslik", callback_data="dup_skip_" + token)]])
        tg.send_message(chat_id, "Bu fayl allaqachon mavjud: <b>%s</b> (<code>%s</code>).\n"
                        "Baribir qo‘shilsinmi?" % (escape(duplicate["name"]), escape(duplicate["file_name"])), kb)
        return
    sd.setdefault("files", []).append(candidate)
    storage.set_state(user_id, "upload_files", sd)
    tg.send_message(chat_id, "✅ Fayl qo'shildi (%d ta): <b>%s</b>\n\nYana yuboring yoki <b>%s</b> ni bosing."
                    % (len(sd["files"]), escape(result), config.B_FILES_DONE), files_keyboard())


def finish_upload(chat_id, user_id, sd):
    storage.clear_state(user_id)
    mod_id = "mod_%d" % int(time.time())
    photos = sd.get("photos", [])
    files = sd.get("files", [])
    mod = {
        "id": mod_id,
        "name": sd.get("name", "Nomsiz"),
        "description": sd.get("description", ""),
        "category": sd.get("category", "minecraft"),
        "photos": photos,
        "cover_file": photos[0].get("path", "") if photos else "",
        "cover_id": photos[0].get("file_id", "") if photos else "",
        "files": files,
        "uploader": user_id,
        "date": storage.now_str(),
        "downloads": 0,
    }
    storage.data.setdefault("mods", {})[mod_id] = mod
    storage.save_data(backup=False)
    import translate
    translate.translate_mod_later(mod_id, delay=3)

    caption = "<b>%s</b>\n\n%s\n\n📂 %s\n📱 @%s" % (
        escape(mod["name"]), escape(mod["description"] or "Tavsif yo'q"),
        category_name(mod["category"]), config.CHANNEL_USERNAME)
    if photos:
        tg.send_media_group(chat_id, photos, caption)
    else:
        tg.send_message(chat_id, caption)
    kb = tg.inline_kb([[tg.button("📢 Kanalga joylash", callback_data="publish_" + mod_id)]])
    tg.send_message(chat_id, "✅ <b>Mod saqlandi!</b>\n\nKanalga joylash uchun tugmani bosing:", kb)
    tg.send_message(chat_id, "Asosiy menyu:", main_keyboard(True))


# ============ BROADCAST (TEZ) ============
def broadcast_text(text, limit_users=None):
    d = storage.data
    blocked = d.get("blocked", {})
    targets = [uid for uid in d.get("users", {}).keys() if uid not in blocked]
    if limit_users is not None:
        targets = targets[:limit_users]
    total = len(targets)
    ok = 0
    fail = 0
    counter_lock = threading.Lock()
    body = "📢 <b>XABAR:</b>\n\n" + text

    def worker(uid):
        nonlocal ok, fail
        try:
            res = tg.send_message(int(uid), body)
        except Exception:
            res = {"ok": False}
        if res.get("ok"):
            storage.mark_user_status(uid, "active")
        elif res.get("error_code") == 403:
            storage.mark_user_status(uid, "deleted")
        with counter_lock:
            if res.get("ok"):
                ok += 1
            else:
                fail += 1

    if total:
        with ThreadPoolExecutor(max_workers=20) as ex:
            list(ex.map(worker, targets))
    return total, ok, fail


# ============ ODDIY HANDLERLAR ============
def handle_message(message):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    frm = message.get("from", {})
    user_id = frm.get("id")
    text = message.get("text", "")
    user_name = frm.get("first_name") or "Foydalanuvchi"
    username = frm.get("username") or ""
    is_private = chat.get("type") == "private"

    if is_private:
        storage.track_user(user_id, user_name, username=username)
    else:
        storage.track_group(chat, check_bot_admin(chat_id))

    if not is_private and not text:
        return

    if is_private and storage.is_blocked(user_id) and not storage.is_admin(user_id):
        tg.send_message(chat_id, BLOCKED_MSG)
        return

    if is_private and not is_subscribed(user_id):
        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                storage.set_state(user_id, "pending_start", {"param": parts[1]})
        send_subscription_warning(chat_id, check_channels(user_id))
        return

    state_info = storage.get_state(user_id)
    cur = state_info.get("state", "")
    sd = state_info.get("data", {})

    if text == config.B_CANCEL:
        storage.clear_state(user_id)
        tg.send_message(chat_id, "❌ Amaliyot bekor qilindi.", main_keyboard(storage.is_admin(user_id)))
        return

    # Admin javob tizimi
    if storage.is_admin(user_id) and cur == "" and message.get("reply_to_message"):
        rep = storage.get_reply(message)
        if rep is not None:
            out = "💬 <b>Admindan javob keldi:</b>\n\n%s" % escape(text)
            storage.add_message(rep["user_id"], "admin", text)
            res = tg.send_message(rep["chat_id"], out)
            if res.get("ok"):
                tg.send_message(chat_id, "✅ Javob <b>%s</b> ga yuborildi!" % escape(rep["user_name"]))
            else:
                tg.send_message(chat_id, "❌ Javob yuborishda xatolik.")
            return

    if text.startswith("/start"):
        storage.clear_state(user_id)
        parts = text.split()
        if len(parts) > 1:
            if process_start_payload(chat_id, user_id, user_name, parts[1]):
                return
        send_welcome(chat_id, user_id, user_name)
        return

    if text in (config.B_REF, "/ref"):
        send_ref(chat_id, user_id)
        return

    if text in (config.B_GUIDE, "/guide"):
        send_guide(chat_id)
        return

    if text in (config.B_MODS, "/mods"):
        show_categories(chat_id)
        return

    if text in ("/help", config.B_HELP):
        storage.set_state(user_id, "help")
        tg.send_message(chat_id, "📩 <b>Adminga xabaringizni yozib yuboring:</b>\n\nBekor qilish uchun tugmani bosing:",
                        cancel_keyboard())
        return

    if text in ("/upload", config.B_UPLOAD):
        if not storage.is_admin(user_id):
            tg.send_message(chat_id, "❌ Faqat admin mod yuklashi mumkin!")
            return
        start_upload(chat_id, user_id)
        return

    if text in ("/admin", config.B_ADMIN):
        if not storage.is_admin(user_id):
            tg.send_message(chat_id, "❌ Sizda admin huquqi yo'q!")
            return
        storage.set_state(user_id, "admin_add")
        tg.send_message(chat_id, "👤 <b>Yangi admin ID sini yuboring:</b>", cancel_keyboard())
        return

    if text in ("/panel", config.B_PANEL):
        if not storage.is_admin(user_id):
            tg.send_message(chat_id, "❌ Sizda admin huquqi yo'q!")
            return
        show_admin_panel(chat_id)
        return

    if text == "/broadcast":
        if not storage.is_admin(user_id):
            tg.send_message(chat_id, "❌ Faqat admin xabar tarqatishi mumkin!")
            return
        storage.set_state(user_id, "broadcast")
        tg.send_message(chat_id, "📢 <b>Barcha foydalanuvchilarga yuboriladigan xabarni yozing:</b>", cancel_keyboard())
        return

    if text == "/stats":
        if not storage.is_admin(user_id):
            tg.send_message(chat_id, "❌ Sizda admin huquqi yo'q!")
            return
        show_stats(chat_id)
        return

    if text == "/channels":
        if not storage.is_admin(user_id):
            tg.send_message(chat_id, "❌ Sizda admin huquqi yo'q!")
            return
        show_channels(chat_id)
        return

    # ---- STATES ----
    if cur == "help":
        storage.clear_state(user_id)
        storage.add_message(user_id, "user", text)
        for admin_id in storage.data.get("admins", []):
            user_link = '<a href="tg://user?id=%s"><b>%s</b></a>' % (user_id, escape(user_name))
            msg = ("📩 <b>Yangi Yordam Xabari</b>\n\n"
                   "👤 <b>Foydalanuvchi:</b> %s (ID: <code>%s</code>)\n"
                   "💬 <b>Xabar:</b> %s\n"
                   "📅 <b>Vaqt:</b> %s\n\n"
                   "💡 <i>Ushbu xabarga 'Reply' qilib javob yozsangiz, javob foydalanuvchiga boradi!</i>"
                   % (user_link, user_id, escape(text), storage.now_str()))
            kb = tg.inline_kb([[tg.button("👤 Profil", url="tg://user?id=%s" % user_id)]])
            res_msg = tg.send_message(admin_id, msg, kb)
            if res_msg.get("ok"):
                storage.register_reply(res_msg["result"]["message_id"], chat_id, user_id, user_name)
        tg.send_message(chat_id, "✅ Xabaringiz adminga yuborildi! Rahmat.",
                        main_keyboard(storage.is_admin(user_id)))
        return

    if cur == "admin_add":
        storage.clear_state(user_id)
        if text.isdigit() and not text.startswith("-"):
            new_id = int(text)
            if new_id not in storage.data["admins"]:
                storage.data["admins"].append(new_id)
                storage.save_data()
                tg.send_message(chat_id, "✅ Yangi admin qo'shildi: <code>%d</code>" % new_id,
                                main_keyboard(True))
            else:
                tg.send_message(chat_id, "ℹ️ Bu admin allaqachon mavjud.")
        else:
            tg.send_message(chat_id, "❌ Noto'g'ri ID. Faqat raqam yuboring.")
        return

    if cur == "channel_add":
        storage.clear_state(user_id)
        ch = text.strip()
        if not ch.startswith("@") and not ch.startswith("-"):
            tg.send_message(chat_id, "❌ Kanal @username yoki ID ko'rinishida bo'lsin.")
            return
        if ch not in storage.data.get("channels", []):
            storage.data.setdefault("channels", []).append(ch)
            storage.save_data()
            tg.send_message(chat_id, "✅ Kanal qo'shildi: <b>%s</b>" % ch, main_keyboard(True))
        else:
            tg.send_message(chat_id, "ℹ️ Bu kanal allaqachon mavjud.")
        return

    if cur == "block_input":
        storage.clear_state(user_id)
        target = None
        if message.get("reply_to_message"):
            target = message["reply_to_message"].get("from", {}).get("id")
        elif text.strip().isdigit():
            target = int(text.strip())
        if not target:
            tg.send_message(chat_id, "❌ Foydalanuvchi ID raqamini yuboring yoki xabariga javob bering.")
            return
        if storage.is_admin(target):
            tg.send_message(chat_id, "⚠️ Adminni bloklab bo'lmaydi!", main_keyboard(True))
            return
        target_user = storage.get_user(target) or {}
        storage.block_user(target, target_user.get("name", str(target)))
        try:
            tg.send_message(target, BLOCKED_MSG)
        except Exception:
            pass
        tg.send_message(chat_id, "🚫 Foydalanuvchi bloklandi: <code>%d</code>" % target,
                        main_keyboard(True))
        return

    if cur == "broadcast":
        storage.clear_state(user_id)
        users_count = len([u for u in storage.data.get("users", {}) if u not in storage.data.get("blocked", {})])
        note = tg.send_message(chat_id, "⏳ <b>%d kishiga xabar yuborilmoqda...</b>" % users_count)
        total, ok, fail = broadcast_text(text)
        result = ("✅ <b>Xabar tarqatish yakunlandi!</b>\n\n"
                  "👥 Jami: <b>%d ta</b>\n🟢 Yetib bordi: <b>%d ta</b>\n🔴 Yetib bormadi: <b>%d ta</b>"
                  % (total, ok, fail))
        try:
            if note.get("ok"):
                tg.edit_message(chat_id, note["result"]["message_id"], result, main_keyboard(True))
            else:
                tg.send_message(chat_id, result, main_keyboard(True))
        except Exception:
            tg.send_message(chat_id, result, main_keyboard(True))
        return

    if cur == "upload_title":
        sd["name"] = text.strip()
        storage.set_state(user_id, "upload_category", sd)
        tg.send_message(chat_id, "✅ Nomi qabul qilindi: <b>%s</b>\n\n<b>3-qadam: Kategoriyani tanlang:</b>"
                        % escape(sd["name"]), upload_category_kb())
        return

    if cur == "upload_desc":
        desc = "" if text == "/skip" else text.strip()
        sd["description"] = desc
        storage.set_state(user_id, "upload_files", sd)
        tg.send_message(chat_id,
                        "<b>5-qadam: Yuklanadigan fayllarni yuboring</b> (.zip, .mcpack, .mcaddon va h.k.).\n"
                        "Bir nechta fayl yuborishingiz mumkin. Yoki to'g'ridan-to'g'ri fayl havolasini (https://...) yuboring.\n"
                        "Tayyor bo'lgach <b>%s</b> ni bosing."
                        % config.B_FILES_DONE, files_keyboard())
        return

    if cur == "upload_photos" and text == config.B_PHOTOS_DONE:
        if not sd.get("photos"):
            tg.send_message(chat_id, "⚠️ Hali rasm yubormadingiz! Kamida 1 ta rasm yuboring.")
            return
        storage.set_state(user_id, "upload_title", sd)
        tg.send_message(chat_id, "<b>2-qadam: Mod nomini yozing:</b>", cancel_keyboard())
        return

    if cur == "upload_files" and text == config.B_FILE_ADD:
        tg.send_message(chat_id, "📎 Faylni yuboring yoki to'g'ridan-to'g'ri fayl havolasini (https://...) yozing.", files_keyboard())
        return

    if cur == "upload_files" and text == config.B_FILES_DONE:
        if not sd.get("files"):
            tg.send_message(chat_id, "⚠️ Hali fayl yubormadingiz! Kamida 1 ta fayl yuboring.")
            return
        finish_upload(chat_id, user_id, sd)
        return

    if cur == "upload_files" and text.startswith("https://"):
        add_link_file(chat_id, user_id, sd, text.strip())
        return

    if cur == "mod_edit_name":
        m_id = sd.get("mod_id", "")
        if m_id in storage.data.get("mods", {}):
            old = storage.data["mods"][m_id].get("name", "")
            storage.data["mods"][m_id]["name"] = text.strip()
            storage.data["mods"][m_id]["tr"] = {}
            storage.save_data()
            import web
            if web.sync_mod_posts(m_id) is False:
                tg.send_message(chat_id, "Mod saqlandi, lekin kanal posti yangilanmadi. Saytdan qayta saqlab urinib ko'ring.")
            import translate
            translate.translate_mod_later(m_id, delay=2)
            storage.clear_state(user_id)
            tg.send_message(chat_id, "✅ Nom o'zgartirildi!\n\n🔴 Eski: <s>%s</s>\n🟢 Yangi: <b>%s</b>"
                            % (escape(old), escape(text.strip())), main_keyboard(True))
        else:
            storage.clear_state(user_id)
            tg.send_message(chat_id, "❌ Mod topilmadi!", main_keyboard(True))
        return

    if cur == "mod_edit_desc":
        m_id = sd.get("mod_id", "")
        if m_id in storage.data.get("mods", {}):
            storage.data["mods"][m_id]["description"] = text.strip()
            storage.data["mods"][m_id]["tr"] = {}
            storage.save_data()
            import web
            if web.sync_mod_posts(m_id) is False:
                tg.send_message(chat_id, "Mod saqlandi, lekin kanal posti yangilanmadi. Saytdan qayta saqlab urinib ko'ring.")
            import translate
            translate.translate_mod_later(m_id, delay=2)
            storage.clear_state(user_id)
            tg.send_message(chat_id, "✅ Tavsif yangilandi!\n\n📝 <i>%s</i>" % escape(text.strip()),
                            main_keyboard(True))
        else:
            storage.clear_state(user_id)
            tg.send_message(chat_id, "❌ Mod topilmadi!", main_keyboard(True))
        return

    if is_private:
        tg.send_message(chat_id, "🤖 Tushunmadim. Bosh sahifa uchun /start bosing.")


def handle_photo(message):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    user_id = message.get("from", {}).get("id")
    if chat.get("type") != "private":
        return
    if storage.is_blocked(user_id) and not storage.is_admin(user_id):
        tg.send_message(chat_id, BLOCKED_MSG)
        return
    if not is_subscribed(user_id):
        send_subscription_warning(chat_id, check_channels(user_id))
        return

    state_info = storage.get_state(user_id)
    cur = state_info.get("state", "")
    sd = state_info.get("data", {})
    photos = message.get("photo", [])
    if not photos or not photos[-1].get("file_id"):
        return
    file_id = photos[-1]["file_id"]
    caption = message.get("caption") or ""
    photo = {"file_id": file_id, "path": ""}
    if storage.is_admin(user_id) and cur == "" and message.get("reply_to_message"):
        rep = storage.get_reply(message)
        if rep is not None:
            storage.add_message(rep["user_id"], "admin", caption, photo=photo)
            try:
                res = tg.send_photo(rep["chat_id"], file_id, caption=escape(caption[:1024]))
            except Exception:
                res = {"ok": False}
            if res.get("ok"):
                tg.send_message(chat_id, "Javob <b>%s</b> ga yuborildi!" % escape(rep["user_name"]))
            else:
                tg.send_message(chat_id, "Javob saytda saqlandi, Telegramga yuborilmadi.")
            return
    if cur == "help":
        user_name = message.get("from", {}).get("first_name") or "Foydalanuvchi"
        storage.clear_state(user_id)
        storage.add_message(user_id, "user", caption, photo=photo)
        user_link = '<a href="tg://user?id=%s"><b>%s</b></a>' % (user_id, escape(user_name))
        metadata = ("<b>Yangi yordam xabari</b>\n\n"
                    "<b>Foydalanuvchi:</b> %s (ID: <code>%s</code>)\n"
                    "<b>Xabar:</b> %s\n<b>Vaqt:</b> %s\n\n"
                    "Rasmga yoki ushbu xabarga Reply qilib javob bering."
                    % (user_link, user_id, escape(caption), storage.now_str()))
        delivered = False
        for admin_id in storage.data.get("admins", []):
            try:
                res_photo = tg.send_photo(admin_id, file_id, caption=escape(caption[:1024]))
            except Exception:
                res_photo = {"ok": False}
            try:
                res_message = tg.send_message(admin_id, metadata)
            except Exception:
                res_message = {"ok": False}
            for result in (res_photo, res_message):
                if result.get("ok"):
                    delivered = True
                    mid = (result.get("result") or {}).get("message_id")
                    if mid:
                        storage.register_reply(mid, chat_id, user_id, user_name)
        tg.send_message(chat_id, "Xabaringiz adminga yuborildi! Rahmat." if delivered
                        else "Xabaringiz saytda saqlandi, Telegramga yuborilmadi.",
                        main_keyboard(storage.is_admin(user_id)))
        return
    if cur != "upload_photos" or not storage.is_admin(user_id):
        return
    if len(sd.get("photos", [])) >= config.MAX_UPLOAD_PHOTOS:
        tg.send_message(chat_id, "⚠️ Maksimum %d ta rasm. <b>%s</b> tugmasini bosing."
                        % (config.MAX_UPLOAD_PHOTOS, config.B_PHOTOS_DONE))
        return
    idx = len(sd.get("photos", [])) + 1
    path = download_photo(file_id, user_id, idx)
    sd.setdefault("photos", []).append({"file_id": file_id, "path": path})
    storage.set_state(user_id, "upload_photos", sd)
    tg.send_message(chat_id, "✅ Rasm qo'shildi (%d/%d). Yana yuboring yoki <b>%s</b> ni bosing."
                    % (len(sd["photos"]), config.MAX_UPLOAD_PHOTOS, config.B_PHOTOS_DONE),
                    photos_keyboard())


def handle_document(message):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    user_id = message.get("from", {}).get("id")
    doc = message.get("document", {})
    if chat.get("type") != "private":
        return
    if storage.is_blocked(user_id) and not storage.is_admin(user_id):
        tg.send_message(chat_id, BLOCKED_MSG)
        return

    # Zaxira tiklash
    if storage.is_admin(user_id) and doc.get("file_name", "").endswith(".json"):
        file_id = doc.get("file_id")
        if tg.download_file(file_id, config.DATA_FILE):
            storage.data = storage.load_data()
            storage.migrate()
            tg.send_message(chat_id, "✅ <b>Zaxira muvaffaqiyatli tiklandi!</b>\n📦 Modlar: <b>%d ta</b>"
                            % len(storage.data.get("mods", {})), main_keyboard(True))
        return

    if not is_subscribed(user_id):
        send_subscription_warning(chat_id, check_channels(user_id))
        return

    state_info = storage.get_state(user_id)
    cur = state_info.get("state", "")
    sd = state_info.get("data", {})
    if cur != "upload_files" or not storage.is_admin(user_id):
        return
    if len(sd.get("files", [])) >= config.MAX_MOD_FILES:
        tg.send_message(chat_id, "⚠️ Maksimum %d ta fayl." % config.MAX_MOD_FILES)
        return
    if sd.get("pending_duplicate"):
        tg.send_message(chat_id, "Avval takroriy fayl uchun qaror qiling yoki yuklashni yakunlang.")
        return
    file_id = doc.get("file_id")
    file_name = doc.get("file_name") or "mod_file"
    safe_name = storage.safe_filename(file_name)
    token = uuid.uuid4().hex
    fp = os.path.join(config.MODS_DIR, "upload_%s_%s" % (token, safe_name))
    candidate = {"file_id": file_id or "", "file_unique_id": doc.get("file_unique_id") or "",
                 "file_name": file_name, "file_path": fp}
    try:
        downloaded = bool(file_id and tg.download_file(file_id, fp))
    except Exception:
        downloaded = False
    if not downloaded or not storage.file_sha256(candidate):
        storage.discard_pending_duplicate({"pending_duplicate": {"token": token, "file": candidate}})
        tg.send_message(chat_id, "Fayl yuklab olinmadi. Qayta yuboring.", files_keyboard())
        return
    duplicate = storage.find_duplicate_file(candidate, sd.get("files") or [])
    if duplicate:
        sd["pending_duplicate"] = {"token": token, "file": candidate}
        storage.set_state(user_id, "upload_files", sd)
        kb = tg.inline_kb([[tg.button("Baribir qo‘shish", callback_data="dup_add_" + token),
                            tg.button("Qo‘shmaslik", callback_data="dup_skip_" + token)]])
        tg.send_message(chat_id, "Bu fayl allaqachon mavjud: <b>%s</b> (<code>%s</code>).\n"
                        "Baribir qo‘shilsinmi?" % (escape(duplicate["name"]), escape(duplicate["file_name"])), kb)
        return
    sd.setdefault("files", []).append(candidate)
    storage.set_state(user_id, "upload_files", sd)
    tg.send_message(chat_id, "✅ Fayl qo'shildi (%d ta): <b>%s</b>\n\nYana yuboring yoki <b>%s</b> ni bosing."
                    % (len(sd["files"]), escape(file_name), config.B_FILES_DONE), files_keyboard())


def handle_my_chat_member(upd):
    chat = upd.get("chat", {})
    new = upd.get("new_chat_member", {})
    status = new.get("status", "")
    if chat.get("type") not in ("group", "supergroup"):
        return
    chat_id = chat.get("id")
    if status in ("left", "kicked"):
        storage.untrack_group(chat_id)
        _group_admin_cache.pop(str(chat_id), None)
        return
    ok = status in ("administrator", "creator")
    storage.track_group(chat, ok)
    _group_admin_cache[str(chat_id)] = (time.time(), ok)


def handle_callback(cq):
    cb_id = cq["id"]
    user_id = cq["from"]["id"]
    cb = cq.get("data", "")
    msg = cq.get("message", {})
    chat = msg.get("chat", {})
    chat_id = chat.get("id", user_id)
    message_id = msg.get("message_id")
    is_private = chat.get("type") == "private"

    if storage.is_blocked(user_id) and not storage.is_admin(user_id):
        tg.send_message(chat_id, BLOCKED_MSG)
        tg.answer_callback(cb_id)
        return

    if not is_subscribed(user_id):
        tg.answer_callback(cb_id, "❌ Avval kanallarga obuna bo'ling!", alert=True)
        return

    if cb == "cat_menu":
        show_categories(chat_id, message_id)
        tg.answer_callback(cb_id)
        return

    if cb.startswith("catpage_"):
        raw = cb.replace("catpage_", "", 1)
        last_us = raw.rfind("_")
        cat_id, page = raw[:last_us], int(raw[last_us + 1:])
        show_category(chat_id, user_id, cat_id, page, message_id)
        tg.answer_callback(cb_id)
        return

    if cb.startswith("cat_") and not cb.startswith("cat_select_") and not cb.startswith("catpage_"):
        cat_id = cb.replace("cat_", "", 1)
        show_category(chat_id, user_id, cat_id, 0, message_id)
        tg.answer_callback(cb_id)
        return

    if cb.startswith("mod_") and not cb.startswith("mod_edit_"):
        mod_id = cb.replace("mod_", "", 1)
        send_mod_detail(chat_id, user_id, mod_id)
        tg.answer_callback(cb_id)
        return

    if cb.startswith("moddl_"):
        mod_id = cb.replace("moddl_", "", 1)
        mod = storage.data.get("mods", {}).get(mod_id)
        if not mod or not storage.mod_visible(mod, user_id):
            tg.answer_callback(cb_id, "Mod topilmadi.", alert=True)
            return
        if not is_private:
            link = "https://t.me/%s?start=%s" % (config.BOT_USERNAME, mod_id)
            tg.answer_callback(cb_id, "Shaxsiy chatda oching!", alert=True)
            tg.send_message(chat_id, "⬇️ Yuklab olish uchun botga shaxsiy chatda yozing: %s" % link)
            return
        send_mod_files(chat_id, mod_id, user_id)
        tg.answer_callback(cb_id, "⏳ Fayllar yuborilmoqda...")
        return

    if cb.startswith("modfav_"):
        mod_id = cb.replace("modfav_", "", 1)
        mod = storage.data.get("mods", {}).get(mod_id)
        if not mod or not storage.mod_visible(mod, user_id):
            tg.answer_callback(cb_id, "Mod topilmadi.", alert=True)
            return
        saved = storage.toggle_favorite(user_id, mod_id)
        tg.answer_callback(cb_id, "❤️ Saqlandi!" if saved else "🤍 Saqlanganlardan olib tashlandi")
        mod = storage.data.get("mods", {}).get(mod_id, {})
        rows = [
            [tg.button("⬇️ Yuklab olish", callback_data="moddl_" + mod_id),
             tg.button("❤️ Saqlangan" if saved else "🤍 Saqlash", callback_data="modfav_" + mod_id)],
            [tg.button("🔙 Kategoriyaga qaytish",
                       callback_data="cat_" + mod.get("category", "all"))],
        ]
        if message_id:
            tg.edit_message(chat_id, message_id, "📥 Yuklab olish uchun tugmani bosing:", tg.inline_kb(rows))
        return

    if cb.startswith("publish_"):
        if not storage.is_admin(user_id):
            tg.answer_callback(cb_id, "Faqat admin uchun.", alert=True)
            return
        import web
        mod_id = cb.replace("publish_", "", 1)
        ok = web.publish_mod(mod_id)
        message = "Mod kanalga joylandi." if ok else "Kanalga joylash amalga oshmadi."
        tg.answer_callback(cb_id, message, alert=not ok)
        tg.send_message(chat_id, message, main_keyboard(True))
        return

    if cb == "check_subscription":
        missing = check_channels(user_id)
        if not missing:
            tg.answer_callback(cb_id, "✅ Obuna tasdiqlandi!")
            user_name = cq["from"].get("first_name", "Foydalanuvchi")
            state_info = storage.get_state(user_id)
            pending = None
            if state_info.get("state") == "pending_start":
                pending = state_info.get("data", {}).get("param")
            storage.clear_state(user_id)
            handled = False
            if pending:
                handled = process_start_payload(chat_id, user_id, user_name, pending)
            if not handled:
                send_welcome(chat_id, user_id, user_name)
        else:
            tg.answer_callback(cb_id, "❌ Hali barcha kanallarga obuna bo'lmadingiz!", alert=True)
        return

    # ---- UPLOAD CALLBACKS ----
    if cb.startswith(("dup_add_", "dup_skip_")):
        state_info = storage.get_state(user_id)
        sd = dict(state_info.get("data", {}))
        pending = sd.get("pending_duplicate") or {}
        token = cb.split("_", 2)[2]
        if (not is_private or not storage.is_admin(user_id)
                or state_info.get("state") != "upload_files" or not pending.get("token")
                or token != pending["token"]):
            tg.answer_callback(cb_id, "Amaliyot eskirgan yoki ruxsat yo‘q.", alert=True)
            return
        candidate = pending["file"]
        sd.pop("pending_duplicate")
        if cb.startswith("dup_skip_"):
            storage.set_state(user_id, "upload_files", sd)
            tg.answer_callback(cb_id, "Fayl qo‘shilmadi.")
            tg.edit_message(chat_id, message_id, "Takroriy fayl qo‘shilmadi.")
            return
        if len(sd.get("files", [])) >= config.MAX_MOD_FILES:
            storage.set_state(user_id, "upload_files", sd)
            tg.answer_callback(cb_id, "Maksimum %d ta fayl." % config.MAX_MOD_FILES, alert=True)
            tg.edit_message(chat_id, message_id, "Takroriy fayl qo‘shilmadi: fayllar chegarasi.")
            return
        if not os.path.isfile(candidate.get("file_path") or ""):
            storage.set_state(user_id, "upload_files", sd)
            tg.answer_callback(cb_id, "Fayl topilmadi. Qayta yuboring.", alert=True)
            tg.edit_message(chat_id, message_id, "Fayl topilmadi. Qayta yuboring.")
            return
        sd["files"] = list(sd.get("files") or []) + [candidate]
        storage.set_state(user_id, "upload_files", sd)
        tg.answer_callback(cb_id, "Fayl qo‘shildi.")
        tg.edit_message(chat_id, message_id, "Takroriy fayl tasdiqlandi.")
        tg.send_message(chat_id, "✅ Fayl qo'shildi (%d ta): <b>%s</b>\n\nYana yuboring yoki <b>%s</b> ni bosing."
                        % (len(sd["files"]), escape(candidate["file_name"]), config.B_FILES_DONE), files_keyboard())
        return

    if cb.startswith("cat_select_"):
        cat_id = cb.replace("cat_select_", "", 1)
        state_info = storage.get_state(user_id)
        if state_info.get("state") != "upload_category" or not storage.is_admin(user_id):
            tg.answer_callback(cb_id, "❌ Amaliyot eskirgan.")
            return
        sd = state_info.get("data", {})
        sd["category"] = cat_id
        storage.set_state(user_id, "upload_desc", sd)
        tg.answer_callback(cb_id)
        tg.send_message(chat_id, "<b>4-qadam: Tavsif yozing (yoki /skip).</b>", cancel_keyboard())
        return

    # ---- PANEL ----
    if not storage.is_admin(user_id):
        tg.answer_callback(cb_id, "❌ Faqat admin!", alert=True)
        return

    if cb == "panel_mod_add":
        start_upload(chat_id, user_id)
        tg.answer_callback(cb_id)
        return

    if cb == "panel_admin_add":
        storage.set_state(user_id, "admin_add")
        tg.send_message(chat_id, "👤 <b>Yangi admin ID sini yuboring:</b>", cancel_keyboard())
        tg.answer_callback(cb_id)
        return

    if cb == "panel_admin_del":
        rows = [[tg.button("🗑️ ID: %d" % aid, callback_data="admin_del_%d" % aid)]
                for aid in storage.data.get("admins", [])]
        rows.append([tg.button("🔙 Panelga qaytish", callback_data="panel_back")])
        tg.edit_message(chat_id, message_id, "👥 <b>Adminlar:</b>\nOlib tashlash uchun bosing:",
                        tg.inline_kb(rows))
        tg.answer_callback(cb_id)
        return

    if cb.startswith("admin_del_"):
        aid = int(cb.replace("admin_del_", "", 1))
        if aid in config.ADMIN_IDS:
            tg.answer_callback(cb_id, "⚠️ Asosiy adminni o'chirib bo'lmaydi!", alert=True)
            return
        if aid in storage.data.get("admins", []):
            storage.data["admins"].remove(aid)
            storage.save_data()
            tg.answer_callback(cb_id, "✅ Admin olib tashlandi")
        rows = [[tg.button("🗑️ ID: %d" % a, callback_data="admin_del_%d" % a)]
                for a in storage.data.get("admins", [])]
        rows.append([tg.button("🔙 Panelga qaytish", callback_data="panel_back")])
        tg.edit_message(chat_id, message_id, "👥 <b>Adminlar:</b>\nOlib tashlash uchun bosing:",
                        tg.inline_kb(rows))
        return

    if cb == "panel_mod_del":
        mods = storage.data.get("mods", {})
        if not mods:
            tg.answer_callback(cb_id, "📭 Modlar yo'q!", alert=True)
            return
        rows = [[tg.button("🗑️ " + m.get("name", ""), callback_data="mod_del_" + mid)]
                for mid, m in list(mods.items())[-10:]]
        rows.append([tg.button("🔙 Panelga qaytish", callback_data="panel_back")])
        tg.edit_message(chat_id, message_id, "📦 <b>Modlar:</b>\nO'chirish uchun bosing:",
                        tg.inline_kb(rows))
        tg.answer_callback(cb_id)
        return

    if cb.startswith("mod_del_"):
        m_id = cb.replace("mod_del_", "", 1)
        mods = storage.data.get("mods", {})
        if m_id in mods:
            mod = mods[m_id]
            for f in mod.get("files", []):
                fp = f.get("file_path", "")
                if fp and os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
            for p in storage.mod_photos(mod):
                pp = p.get("path", "")
                if pp and os.path.exists(pp):
                    try:
                        os.remove(pp)
                    except Exception:
                        pass
            name = mod.get("name", "")
            del mods[m_id]
            storage.save_data()
            tg.answer_callback(cb_id, "🗑️ O'chirildi: %s" % name)
        rows = [[tg.button("🗑️ " + m2.get("name", ""), callback_data="mod_del_" + mid2)]
                for mid2, m2 in list(mods.items())[-10:]]
        rows.append([tg.button("🔙 Panelga qaytish", callback_data="panel_back")])
        tg.edit_message(chat_id, message_id,
                        "📦 <b>Modlar:</b>\nO'chirish uchun bosing:" if mods else "📭 Modlar yo'q.",
                        tg.inline_kb(rows))
        return

    if cb == "panel_mod_edit":
        mods = storage.data.get("mods", {})
        if not mods:
            tg.answer_callback(cb_id, "📭 Modlar yo'q!", alert=True)
            return
        rows = [[tg.button("✏️ %s [%s]" % (m.get("name", "Nomsiz"), m.get("category", "")),
                           callback_data="mod_edit_sel_" + mid)]
                for mid, m in list(mods.items())[-15:]]
        rows.append([tg.button("🔙 Panelga qaytish", callback_data="panel_back")])
        tg.edit_message(chat_id, message_id, "✏️ <b>Qaysi modni tahrirlash?</b>", tg.inline_kb(rows))
        tg.answer_callback(cb_id)
        return

    if cb.startswith("mod_edit_sel_"):
        m_id = cb.replace("mod_edit_sel_", "", 1)
        mod = storage.data.get("mods", {}).get(m_id)
        if not mod:
            tg.answer_callback(cb_id, "❌ Mod topilmadi!", alert=True)
            return
        t = ("✏️ <b>Tahrirlash: %s</b>\n\n📝 Nomi: <b>%s</b>\n💬 Tavsif: <i>%s</i>\n📂 Kategoriya: <b>%s</b>\n\nNimani o'zgartirmoqchisiz?"
             % (escape(mod.get("name", "")), escape(mod.get("name", "")),
                escape((mod.get("description", "") or "")[:80]), category_name(mod.get("category", ""))))
        rows = [
            [tg.button("📝 Nomini o'zgartirish", callback_data="mod_edit_name_" + m_id)],
            [tg.button("💬 Tavsifini o'zgartirish", callback_data="mod_edit_desc_" + m_id)],
            [tg.button("📂 Kategoriyani o'zgartirish", callback_data="mod_edit_cat_" + m_id)],
            [tg.button("🔙 Orqaga", callback_data="panel_mod_edit")],
        ]
        tg.edit_message(chat_id, message_id, t, tg.inline_kb(rows))
        tg.answer_callback(cb_id)
        return

    if cb.startswith("mod_edit_name_"):
        m_id = cb.replace("mod_edit_name_", "", 1)
        storage.set_state(user_id, "mod_edit_name", {"mod_id": m_id})
        tg.send_message(chat_id, "📝 <b>Yangi nomni yozing:</b>\n\n(Hozirgi: <i>%s</i>)"
                        % escape(storage.data.get("mods", {}).get(m_id, {}).get("name", "")),
                        cancel_keyboard())
        tg.answer_callback(cb_id)
        return

    if cb.startswith("mod_edit_desc_"):
        m_id = cb.replace("mod_edit_desc_", "", 1)
        storage.set_state(user_id, "mod_edit_desc", {"mod_id": m_id})
        tg.send_message(chat_id, "💬 <b>Yangi tavsifni yozing:</b>\n\n(Hozirgi: <i>%s</i>)"
                        % escape((storage.data.get("mods", {}).get(m_id, {}).get("description", "") or "")[:100]),
                        cancel_keyboard())
        tg.answer_callback(cb_id)
        return

    if cb.startswith("mod_edit_cat_"):
        m_id = cb.replace("mod_edit_cat_", "", 1)
        mod = storage.data.get("mods", {}).get(m_id, {})
        rows = []
        items = config.MOD_CATEGORIES
        for i in range(0, len(items), 2):
            row = [tg.button(items[i]["icon"] + " " + items[i]["name"] +
                             (" ✅" if mod.get("category") == items[i]["id"] else ""),
                             callback_data="mod_set_cat_%s_%s" % (m_id, items[i]["id"]))]
            if i + 1 < len(items):
                row.append(tg.button(items[i + 1]["icon"] + " " + items[i + 1]["name"] +
                                     (" ✅" if mod.get("category") == items[i + 1]["id"] else ""),
                                     callback_data="mod_set_cat_%s_%s" % (m_id, items[i + 1]["id"])))
            rows.append(row)
        rows.append([tg.button("🔙 Orqaga", callback_data="mod_edit_sel_" + m_id)])
        tg.edit_message(chat_id, message_id, "📂 <b>Kategoriya tanlang:</b>", tg.inline_kb(rows))
        tg.answer_callback(cb_id)
        return

    if cb.startswith("mod_set_cat_"):
        raw = cb.replace("mod_set_cat_", "", 1)
        last_us = raw.rfind("_")
        m_id, new_cat = raw[:last_us], raw[last_us + 1:]
        if m_id in storage.data.get("mods", {}):
            storage.data["mods"][m_id]["category"] = new_cat
            storage.save_data()
            tg.answer_callback(cb_id, "✅ Kategoriya: %s" % category_name(new_cat), alert=True)
        else:
            tg.answer_callback(cb_id, "❌ Mod topilmadi!", alert=True)
        return

    if cb == "panel_channels":
        show_channels(chat_id, message_id)
        tg.answer_callback(cb_id)
        return

    if cb == "channel_add_btn":
        storage.set_state(user_id, "channel_add")
        tg.send_message(chat_id, "📢 <b>Kanal username (@bilan) yuboring:</b>", cancel_keyboard())
        tg.answer_callback(cb_id)
        return

    if cb.startswith("chdel_"):
        ch = cb.replace("chdel_", "", 1)
        if ch in storage.data.get("channels", []):
            storage.data["channels"].remove(ch)
            storage.save_data()
            tg.answer_callback(cb_id, "🗑️ Kanal olib tashlandi")
        show_channels(chat_id, message_id)
        return

    if cb == "panel_block":
        storage.set_state(user_id, "block_input")
        tg.send_message(chat_id, "🚫 <b>Foydalanuvchi ID raqamini yuboring</b> (yoki xabariga javob bering):",
                        cancel_keyboard())
        tg.answer_callback(cb_id)
        return

    if cb == "panel_unblock":
        show_blocked_list(chat_id, message_id)
        tg.answer_callback(cb_id)
        return

    if cb.startswith("unblock_"):
        uid = cb.replace("unblock_", "", 1)
        if storage.unblock_user(uid):
            tg.answer_callback(cb_id, "✅ Blokdan chiqarildi")
        show_blocked_list(chat_id, message_id)
        return

    if cb == "panel_broadcast":
        storage.set_state(user_id, "broadcast")
        tg.send_message(chat_id, "📢 <b>Barcha foydalanuvchilarga yuboriladigan xabarni yozing:</b>",
                        cancel_keyboard())
        tg.answer_callback(cb_id)
        return

    if cb == "panel_stats":
        show_stats(chat_id, message_id)
        tg.answer_callback(cb_id)
        return

    if cb == "panel_backup":
        ok = storage.backup_now(force=True, wait=True)
        tg.answer_callback(cb_id, "💾 Zaxira yuborildi va pin qilindi!" if ok else "❌ Zaxira yuborilmadi")
        return

    if cb in ("panel_back", "panel_refresh"):
        show_admin_panel(chat_id, message_id)
        tg.answer_callback(cb_id)
        return

    if cb == "panel_close":
        tg.edit_message(chat_id, message_id, "🛠️ Admin Panel yopildi.")
        tg.answer_callback(cb_id)
        return

    tg.answer_callback(cb_id)


# ============ POLLING ============
def run_bot():
    print("Bot polling boshlandi...")
    try:
        tg.set_my_commands()
        if config.WEBAPP_URL:
            tg.set_chat_menu_button(config.WEBAPP_URL)
    except Exception:
        pass
    threading.Thread(target=refresh_groups, daemon=True).start()
    if (not storage.was_restored() and not storage.data.get("mods")
            and not storage.data.get("users")):
        try:
            tg.send_message(config.ADMIN_IDS[0],
                            "⚠️ <b>Ma'lumotlar topilmadi</b>\n\n"
                            "Agar avval zaxira olgan bo'lsangiz, oxirgi <b>data.json</b> "
                            "faylini shu botga forward qiling — hammasi tiklanadi.")
        except Exception:
            pass
    offset = 0
    while True:
        try:
            res = tg.api_request("getUpdates", {"offset": offset, "timeout": 30})
            if res.get("ok"):
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    try:
                        if "message" in upd:
                            m = upd["message"]
                            if "photo" in m:
                                handle_photo(m)
                            elif "document" in m:
                                handle_document(m)
                            elif "text" in m:
                                handle_message(m)
                        elif "callback_query" in upd:
                            handle_callback(upd["callback_query"])
                        elif "my_chat_member" in upd:
                            handle_my_chat_member(upd["my_chat_member"])
                    except Exception as e:
                        print("Update xatosi:", e)
        except Exception as e:
            print("Polling error:", e)
            time.sleep(3)
