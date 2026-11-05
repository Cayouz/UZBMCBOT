import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception as e:
        print("Env yuklash ogohlantirish:", e)


_load_env()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "7667103099").split(",") if x.strip()]
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "UZBMINECRAFTMODLAR")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@UZBMINECRAFTMODLAR")
# Ixtiyoriy: zaxira saqlanadigan yopiq guruh (bot admin bo'lishi shart).
# Bo'sh bo'lsa zaxira ADMIN_IDS[0] ga yuboriladi.
BACKUP_CHAT_ID = os.environ.get("BACKUP_CHAT_ID", "").strip()
BOT_USERNAME = os.environ.get("BOT_USERNAME", "UZBMCBOT")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "Cayouz")
WEBAPP_URL = (os.environ.get("WEBAPP_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
API_URL = "https://api.telegram.org/bot" + BOT_TOKEN + "/"

DATA_FILE = os.path.join(BASE_DIR, "data.json")
MODS_DIR = os.path.join(BASE_DIR, "mods")
AVATARS_DIR = os.path.join(BASE_DIR, "avatars")
STATIC_DIR = os.path.join(BASE_DIR, "static")

PORT = int(os.environ.get("PORT", "8080"))
DISABLE_BOT = os.environ.get("DISABLE_BOT", "0") == "1"
DEV_ADMIN_IDS = [int(x) for x in os.environ.get("DEV_ADMIN_IDS", "").split(",") if x.strip()]

LIVE_USER_DAYS = int(os.environ.get("LIVE_USER_DAYS", "7"))
WEB_LIVE_SECONDS = 300
MAX_UPLOAD_PHOTOS = 5
MAX_MOD_FILES = 10

for _d in (MODS_DIR, AVATARS_DIR, os.path.join(STATIC_DIR, "assets")):
    os.makedirs(_d, exist_ok=True)

CATEGORIES = [
    {"id": "all", "name": "Barchasi", "icon": "\u26a1"},
    {"id": "favorites", "name": "Saqlanganlar", "icon": "\u2764\ufe0f"},
    {"id": "cars", "name": "Avtomobillar", "icon": "\U0001f697"},
    {"id": "guns", "name": "Qurollar", "icon": "\u2694\ufe0f"},
    {"id": "shaders", "name": "Shaderlar", "icon": "\u2728"},
    {"id": "horror", "name": "Horror (Qo'rqinchli)", "icon": "\U0001f47b"},
    {"id": "worlds", "name": "Dunyolar", "icon": "\U0001f30d"},
    {"id": "minecraft", "name": "MINECRAFT", "icon": "\u26cf\ufe0f"},
    {"id": "addons", "name": "Addonlar (Qo'shimchalar)", "icon": "\U0001f9e9"},
    {"id": "textures", "name": "TEKSTURALAR", "icon": "\U0001f3a8"},
]
CATEGORY_MAP = {c["id"]: c for c in CATEGORIES}
MOD_CATEGORIES = [c for c in CATEGORIES if c["id"] not in ("all", "favorites")]
MOD_CATEGORY_IDS = {c["id"] for c in MOD_CATEGORIES}

B_MODS = "\U0001f4e6 Modlar"
B_HELP = "\U0001f4dd Yordam (Adminga yozish)"
B_UPLOAD = "\U0001f4e4 Kontent yuborish"
B_ADMIN = "\U0001f464 Admin qo'shish"
B_PANEL = "\U0001f6e0\ufe0f Panel"
B_CANCEL = "\u274c Bekor qilish"
B_PHOTOS_DONE = "\u2705 Rasmlar tayyor"
B_FILES_DONE = "\u2705 Fayllar tayyor"
B_FILE_ADD = "Fayl qo'shish"
B_REF = "\U0001f381 Taklifnoma (Do'stlarni taklif qilish)"
B_GUIDE = "\U0001f4d6 Qo'llanma (O'rnatish yo'riqnomasi)"
