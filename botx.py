import os
import sys
import json
import time
import datetime
import re
import requests
import threading
import socketserver
import urllib.parse
from html import escape
from http.server import HTTPServer, BaseHTTPRequestHandler

# UTF-8 console encoding setup
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
        sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

import builtins
_orig_print = builtins.print
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    return _orig_print(*args, **kwargs)

# Thread safety lock for DB operations
db_lock = threading.Lock()

# ================= SOZLAMALAR =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8841481084:AAFMK_CKSyFPGiYYogHMXpCaYU0B0XejajI")
ADMIN_IDS = [7667103099]
CHANNEL_USERNAME = "UZBMINECRAFTMODLAR"
CHANNEL_ID = "@UZBMINECRAFTMODLAR"
BOT_USERNAME = "UZBMCBOT"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODS_DIR = os.path.join(BASE_DIR, "mods")
DATA_FILE = os.path.join(BASE_DIR, "data.json")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Klaviatura Matnlari
B_MODS = "📦 Modlar"
B_HELP = "📝 Yordam (Adminga yozish)"
B_UPLOAD = "📤 Kontent yuborish"
B_ADMIN = "👤 Admin qo'shish"
B_PANEL = "🛠️ Panel"
B_CANCEL = "❌ Bekor qilish"
B_FILES_DONE = "✅ Fayllar tayyor"
B_FILE_ADD = "Fayl qo'shish"
B_WEBAPP = "🌐 Web Sayt"
B_REF = "🎁 Taklifnoma (Do'stlarni taklif qilish)"
B_GUIDE = "📖 Qo'llanma (O'rnatish yo'riqnomasi)"

CATEGORIES = [
    {"id": "all", "name": "Barchasi", "tag": "#all", "icon": "⚡"},
    {"id": "favorites", "name": "Saqlanganlar", "tag": "#fav", "icon": "❤️"},
    {"id": "cars", "name": "Avtomobillar", "tag": "#cars", "icon": "🚗"},
    {"id": "guns", "name": "Qurollar", "tag": "#guns", "icon": "⚔️"},
    {"id": "shaders", "name": "Shaderlar", "tag": "#shaders", "icon": "✨"},
    {"id": "horror", "name": "Horror (Qo'rqinchli)", "tag": "#horror", "icon": "👻"},
    {"id": "worlds", "name": "Dunyolar", "tag": "#addon", "icon": "🌍"},
    {"id": "minecraft", "name": "MINECRAFT", "tag": "#minecraft", "icon": "⛏️"},
    {"id": "addons", "name": "Addonlar (Qo'shimchalar)", "tag": "#addon", "icon": "🧩"},
    {"id": "textures", "name": "TEKSTURALAR", "tag": "#textures", "icon": "🎨"}
]

if not os.path.exists(MODS_DIR):
    os.makedirs(MODS_DIR, exist_ok=True)

# ================= MA'LUMOTLAR BAZASI =================
def load_data():
    default_data = {
        "mods": {},
        "admins": ADMIN_IDS[:],
        "states": {},
        "channels": [CHANNEL_ID],
        "users": {},
        "groups": {},
        "replies": {},
        "comments": {}
    }
    with db_lock:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                    if content:
                        d = json.loads(content)
                        if isinstance(d, dict):
                            for k, v in default_data.items():
                                d.setdefault(k, v)
                            return d
            except json.JSONDecodeError:
                print("Ma'lumotlar bazasi (data.json) bo'sh bo'lgani uchun yangidan tiklandi.")
            except Exception as e:
                print(f"Data yuklashda ogohlantirish: {e}")
    return default_data

def auto_backup_async():
    def _bg():
        try:
            if os.path.exists(DATA_FILE) and ADMIN_IDS:
                admin_id = ADMIN_IDS[0]
                send_document(admin_id, DATA_FILE, caption="💾 <b>ZAXIRA (BACKUP):</b> Barcha modlar va ma'lumotlar saqlandi.\n\n💡 <i>Server qayta tushganda ushbu faylni botga qayta yuborsangiz (Forward), hamma modlar bir zumda tiklanadi!</i>")
        except Exception as e:
            print(f"Auto backup error: {e}")
    threading.Thread(target=_bg, daemon=True).start()

def save_data(backup=False):
    global data
    with db_lock:
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Data saqlashda xato: {e}")
    if backup:
        auto_backup_async()

data = load_data()
save_data()

# ================= WEB APP HTML & API SERVER =================
WEBAPP_HTML = """<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>MINECRAFT MOD HUB</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #10b981;
            --primary-hover: #059669;
            --primary-glow: rgba(16, 185, 129, 0.35);
            --primary-border: rgba(16, 185, 129, 0.25);
            --primary-bg-subtle: rgba(16, 185, 129, 0.12);
            --secondary: #3b82f6;
            --bg-radial: radial-gradient(circle at 50% 0%, #0d1b2a 0%, #090d16 85%);
            --card-bg: rgba(15, 23, 42, 0.85);
            --card-border: rgba(255, 255, 255, 0.08);
            --banner-grad: linear-gradient(135deg, #34d399, #60a5fa);
            --text-main: #ffffff;
            --text-muted: #94a3b8;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; -webkit-tap-highlight-color: transparent; }
        
        body {
            background: #090d16;
            background-image: var(--bg-radial);
            background-attachment: fixed;
            color: var(--text-main);
            min-height: 100vh;
            padding-bottom: 40px;
            overflow-x: hidden;
            transition: background 0.4s ease;
        }

        .container { max-width: 640px; margin: 0 auto; padding: 14px; }

        /* Marquee Announcement Bar */
        .marquee-box {
            background: rgba(234, 179, 8, 0.1);
            border: 1px solid rgba(234, 179, 8, 0.25);
            border-radius: 12px;
            padding: 8px 14px;
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
            backdrop-filter: blur(10px);
        }

        /* Top Header Controls */
        .top-ctrls {
            display: flex;
            justify-content: flex-end;
            align-items: center;
            margin-bottom: 14px;
        }

        .ctrl-btn {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #fff;
            border-radius: 10px;
            padding: 6px 12px;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            outline: none;
            backdrop-filter: blur(10px);
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .ctrl-btn:active { transform: scale(0.95); }

        /* Professional Banner Header */
        .banner {
            background: var(--card-bg);
            border: 1px solid var(--primary-border);
            border-radius: 20px;
            padding: 22px 16px;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5), 0 0 25px var(--primary-glow);
            margin-bottom: 16px;
            backdrop-filter: blur(16px);
            transition: border-color 0.4s ease, box-shadow 0.4s ease;
        }

        .banner-logo {
            font-size: 26px;
            font-weight: 800;
            background: var(--banner-grad);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: 1px;
            margin-bottom: 4px;
            text-transform: uppercase;
        }

        .banner-sub { color: var(--primary); font-size: 12px; font-weight: 700; letter-spacing: 2px; }

        /* Professional Theme Switcher Bar */
        .theme-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 10px 14px;
            margin-bottom: 16px;
            backdrop-filter: blur(12px);
        }
        .theme-dots { display: flex; gap: 8px; }
        .theme-dot {
            width: 24px;
            height: 24px;
            border-radius: 50%;
            border: 2px solid transparent;
            cursor: pointer;
            outline: none;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .theme-dot:active { transform: scale(0.9); }

        /* SEARCH BAR AT THE TOP */
        .search-container {
            margin-bottom: 16px;
            position: sticky;
            top: 10px;
            z-index: 60;
        }

        .search-box-wrap {
            position: relative;
            width: 100%;
        }

        .search-box {
            width: 100%;
            padding: 14px 16px 14px 44px;
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid var(--primary-border);
            border-radius: 16px;
            color: #fff;
            font-size: 14px;
            outline: none;
            backdrop-filter: blur(20px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
            transition: all 0.3s ease;
        }
        .search-box:focus {
            border-color: var(--primary);
            box-shadow: 0 0 20px var(--primary-glow);
        }

        .search-icon {
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 18px;
            color: var(--text-muted);
            pointer-events: none;
        }

        /* Wrapped Category Chips (All Fully Visible at Once) */
        .chips-scroll {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            padding: 4px 0 14px 0;
            margin-bottom: 16px;
            justify-content: flex-start;
        }

        .chip {
            white-space: nowrap;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            color: var(--text-muted);
            padding: 8px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
            backdrop-filter: blur(10px);
        }
        .chip.active {
            background: var(--primary-bg-subtle);
            border-color: var(--primary);
            color: var(--primary);
            box-shadow: 0 0 14px var(--primary-glow);
        }
        .chip:active { transform: scale(0.95); }

        /* Quick Cards Grid */
        .quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px; }
        .q-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 18px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            backdrop-filter: blur(12px);
            transition: transform 0.2s ease, border-color 0.3s ease;
        }
        .q-card:active { transform: scale(0.97); }
        .q-card-icon { font-size: 36px; margin-bottom: 8px; }
        .q-card-title { font-size: 15px; font-weight: 700; margin-bottom: 4px; color: #fff; }
        .q-card-desc { font-size: 11px; color: var(--text-muted); margin-bottom: 12px; flex-grow: 1; line-height: 1.4; }

        /* Buttons */
        .btn {
            width: 100%;
            padding: 11px 14px;
            border-radius: 12px;
            border: none;
            font-weight: 700;
            font-size: 13px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            text-decoration: none;
            transition: all 0.2s ease;
        }
        .btn-primary {
            background: var(--primary);
            color: #000;
            box-shadow: 0 4px 14px var(--primary-glow);
        }
        .btn-primary:active { transform: scale(0.96); background: var(--primary-hover); }

        .btn-secondary {
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
            border: 1px solid rgba(255, 255, 255, 0.12);
        }
        .btn-secondary:active { transform: scale(0.96); background: rgba(255, 255, 255, 0.15); }

        /* Mod List Section Full-Width */
        .section-title {
            font-size: 17px;
            font-weight: 800;
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .mods-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 14px;
        }
        @media (min-width: 500px) {
            .mods-grid { grid-template-columns: 1fr 1fr; }
        }

        .mod-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 18px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            backdrop-filter: blur(12px);
            transition: transform 0.2s ease, border-color 0.3s ease, box-shadow 0.3s ease;
            animation: fadeIn 0.3s ease forwards;
        }
        .mod-card:hover {
            border-color: var(--primary-border);
            box-shadow: 0 8px 24px rgba(0,0,0,0.5), 0 0 20px var(--primary-glow);
        }

        .mod-img { width: 100%; height: 165px; object-fit: cover; background: #1e293b; }
        .mod-body { padding: 14px; display: flex; flex-direction: column; flex-grow: 1; }
        .mod-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
        .mod-title { font-size: 16px; font-weight: 700; color: #fff; }
        .mod-badge { font-size: 11px; background: var(--primary-bg-subtle); color: var(--primary); padding: 3px 8px; border-radius: 12px; font-weight: 700; white-space: nowrap; }
        .mod-desc { font-size: 12px; color: var(--text-muted); line-height: 1.4; margin-bottom: 12px; flex-grow: 1; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }

        /* Favorite Heart Button */
        .fav-btn {
            position: absolute;
            top: 10px; right: 10px;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 50%;
            width: 34px; height: 34px;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            font-size: 16px;
            backdrop-filter: blur(8px);
            transition: transform 0.2s ease, background 0.2s ease;
            z-index: 5;
        }
        .fav-btn:active { transform: scale(0.85); }

        /* Admin Edit Button */
        .edit-btn {
            position: absolute;
            top: 10px; left: 10px;
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 200, 0, 0.35);
            border-radius: 50%;
            width: 34px; height: 34px;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            font-size: 15px;
            backdrop-filter: blur(8px);
            transition: transform 0.2s ease, background 0.2s ease;
            z-index: 5;
        }
        .edit-btn:hover { background: rgba(234, 179, 8, 0.18); border-color: #fbbf24; }
        .edit-btn:active { transform: scale(0.85); }

        /* Toast Notification */
        .toast {
            position: fixed;
            bottom: 28px;
            left: 50%;
            transform: translateX(-50%) translateY(20px);
            background: #0f172a;
            border: 1px solid var(--primary-border);
            color: #fff;
            padding: 12px 24px;
            border-radius: 50px;
            font-size: 13px;
            font-weight: 700;
            z-index: 99998;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease, transform 0.3s ease;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
            backdrop-filter: blur(12px);
        }
        .toast.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }

        /* Edit modal select custom arrow */
        #editModCategory {
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2394a3b8' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 14px center;
        }

        /* Modal Overlays & Animations */
        .modal {
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.85);
            backdrop-filter: blur(12px);
            z-index: 100;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 16px;
            animation: fadeIn 0.25s ease;
        }

        .modal-content {
            background: #0f172a;
            border: 1px solid var(--primary-border);
            border-radius: 24px;
            padding: 22px;
            width: 100%;
            max-width: 480px;
            max-height: 85vh;
            overflow-y: auto;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8), 0 0 30px var(--primary-glow);
            animation: slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }

        /* Fullscreen Subscription Lock Overlay (Matching Image) */
        .lock-screen-overlay {
            position: fixed;
            top: 0; left: 0; width: 100vw; height: 100vh;
            background: rgba(9, 13, 22, 0.96);
            backdrop-filter: blur(20px);
            z-index: 99999;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .lock-card {
            background: #0f172a;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 28px;
            padding: 32px 24px;
            width: 100%;
            max-width: 420px;
            text-align: center;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
        }

        .lock-icon-box {
            width: 72px;
            height: 72px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 20px auto;
        }

        .lock-emoji { font-size: 36px; }

        .lock-title {
            font-size: 20px;
            font-weight: 800;
            color: #ffffff;
            margin-bottom: 8px;
            letter-spacing: -0.3px;
        }

        .lock-subtitle {
            font-size: 13px;
            color: #94a3b8;
            margin-bottom: 24px;
            line-height: 1.4;
        }

        .lock-channels-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 24px;
        }

        .channel-btn {
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid #10b981;
            border-radius: 14px;
            padding: 14px 16px;
            color: #ffffff;
            font-weight: 700;
            font-size: 13px;
            text-decoration: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            transition: all 0.2s ease;
        }
        .channel-btn:hover { background: rgba(16, 185, 129, 0.1); transform: translateY(-1px); }

        .btn-check-sub {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%);
            color: #000000;
            border: none;
            border-radius: 16px;
            font-weight: 800;
            font-size: 15px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            box-shadow: 0 0 25px rgba(6, 182, 212, 0.4);
            transition: all 0.2s ease;
        }
        .btn-check-sub:active { transform: scale(0.97); }

        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes slideUp { from { opacity: 0; transform: translateY(30px) scale(0.95); } to { opacity: 1; transform: translateY(0) scale(1); } }

        /* Empty State */
        .empty-box {
            text-align: center;
            padding: 40px 16px;
            background: var(--card-bg);
            border: 1px dashed var(--card-border);
            border-radius: 18px;
            color: var(--text-muted);
            font-size: 14px;
            grid-column: 1 / -1;
        }

        /* Footer */
        .footer {
            margin-top: 32px;
            padding-top: 18px;
            border-top: 1px solid var(--card-border);
            display: flex;
            align-items: center;
            justify-content: space-around;
            font-size: 11px;
            color: var(--text-muted);
            font-weight: 600;
        }
        .footer a { color: var(--primary); text-decoration: none; font-weight: 700; }
    </style>
</head>
<body>
    <!-- Fullscreen Subscription Lock Overlay (Matching Image Exactly) -->
    <div class="lock-screen-overlay" id="subModal">
        <div class="lock-card">
            <div class="lock-icon-box">
                <div class="lock-emoji">🔒</div>
            </div>
            <h2 class="lock-title">Davom etish uchun obuna bo'ling</h2>
            <p class="lock-subtitle">Ilovadan foydalanish uchun quyidagi kanallarga qo'shiling</p>

            <div id="subChannelsList" class="lock-channels-list"></div>

            <button class="btn-check-sub" onclick="checkSubAgain()">
                <span style="font-size: 16px;">☑️</span> Obunani tekshirish
            </button>
        </div>
    </div>

    <div class="container">
        <!-- Marquee Announcement Bar -->
        <div class="marquee-box">
            <span style="font-size: 14px;">📢</span>
            <marquee behavior="scroll" direction="left" scrollamount="4" style="font-size: 13px; font-weight: 600; color: #fde047;">
                @UZBMINECRAFTMODLAR rasmiy saytiga xush kelibsiz! Eng so'nggi Minecraft modlari, shaderlar va horror dunyolar bu yerda!
            </marquee>
        </div>

        <!-- Header Top Controls -->
        <div class="top-ctrls">
            <button class="ctrl-btn" id="soundToggleBtn" onclick="toggleSound()">🔊 Ovoz: Yoqilgan</button>
        </div>

        <!-- Banner Header -->
        <div class="banner">
            <div class="banner-logo">@UZBMINECRAFTMODLAR</div>
            <div class="banner-sub" id="bannerSubText">KANALI RASMIY MOD HUB SAYTI</div>
        </div>

        <!-- Professional Theme Selector -->
        <div class="theme-bar">
            <div style="font-size: 13px; font-weight: 700; color: #cbd5e1; display: flex; align-items: center; gap: 6px;" id="themeLabelText">
                🎨 Mavzu (Theme Engine):
            </div>
            <div class="theme-dots">
                <button class="theme-dot" onclick="setTheme('green')" id="dot-green" title="Emerald Green" style="background: #22c55e; border-color: #fff;"></button>
                <button class="theme-dot" onclick="setTheme('blue')" id="dot-blue" title="Diamond Blue" style="background: #3b82f6;"></button>
                <button class="theme-dot" onclick="setTheme('red')" id="dot-red" title="Nether Red" style="background: #ef4444;"></button>
                <button class="theme-dot" onclick="setTheme('purple')" id="dot-purple" title="Ender Purple" style="background: #a855f7;"></button>
            </div>
        </div>

        <!-- SEARCH BAR AT THE TOP -->
        <div class="search-container">
            <div class="search-box-wrap">
                <span class="search-icon">🔍</span>
                <input type="text" class="search-box" id="searchInput" placeholder="Modlarni qidirish..." oninput="debouncedFilter()">
            </div>
        </div>

        <!-- Wrapped Category Filter Chips (All Fully Visible at Once) -->
        <div class="chips-scroll" id="chipsContainer"></div>

        <!-- Quick Action Cards Grid -->
        <div class="quick-grid">
            <div class="q-card">
                <div class="q-card-icon">💬</div>
                <div class="q-card-title" id="qContactTitle">Adminga yozish</div>
                <div class="q-card-desc" id="qContactDesc">Savol va takliflar bo'lsa adminga xabar qoldiring.</div>
                <button class="btn btn-primary" onclick="openAdminHelp()" id="qContactBtn">Yozish &rsaquo;</button>
            </div>
            <div class="q-card">
                <div class="q-card-icon">🎁</div>
                <div class="q-card-title" id="qRefTitle">Do'stlarni taklif qilish</div>
                <div class="q-card-desc" id="qRefDesc">Havolangizni ulashing va do'stlarni chorlang.</div>
                <button class="btn btn-secondary" onclick="copyRefLink()" id="qRefBtn">📋 Havolani nusxalash</button>
            </div>
        </div>

        <!-- Mod List Section -->
        <div class="section-title">
            <span id="modSectionTitle">📦 Barcha Modlar</span>
            <span id="modCountBadge" style="font-size: 12px; color: var(--primary); font-weight: 700;">0 ta</span>
        </div>

        <div class="mods-grid" id="modsContainer">
            <div class="empty-box">⏳ Modlar yuklanmoqda...</div>
        </div>

        <!-- Footer -->
        <div class="footer">
            <span>📦 BIZ BILAN BO'LING</span>
            <a href="https://t.me/UZBMINECRAFTMODLAR" target="_blank">✈️ TELEGRAM KANAL</a>
            <span>❤️ MINECRAFT MODS</span>
        </div>
    </div>

    <!-- Mod Details Modal -->
    <div class="modal" id="modModal">
        <div class="modal-content">
            <div id="modalBody"></div>
            <button class="btn btn-secondary" style="margin-top: 14px;" onclick="closeModal()">Yopish</button>
        </div>
    </div>

    <!-- Edit Mod Modal (Admin only) -->
    <div class="modal" id="editModModal">
        <div class="modal-content">
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:16px;">
                <h3 style="font-size:18px; font-weight:800; color:var(--primary);">✏️ Modni Tahrirlash</h3>
                <button onclick="closeEditModal()" style="background:none; border:none; color:var(--text-muted); font-size:20px; cursor:pointer;">✕</button>
            </div>

            <input type="hidden" id="editModId">

            <label style="font-size:12px; font-weight:700; color:var(--text-muted); display:block; margin-bottom:6px;">📝 Nomi</label>
            <input type="text" id="editModName" placeholder="Mod nomi..." style="width:100%; padding:12px 14px; background:rgba(15,23,42,0.95); border:1px solid var(--primary-border); border-radius:12px; color:#fff; font-size:14px; outline:none; margin-bottom:14px;">

            <label style="font-size:12px; font-weight:700; color:var(--text-muted); display:block; margin-bottom:6px;">💬 Tavsifi</label>
            <textarea id="editModDesc" rows="4" placeholder="Mod haqida qisqacha..." style="width:100%; padding:12px 14px; background:rgba(15,23,42,0.95); border:1px solid var(--primary-border); border-radius:12px; color:#fff; font-size:13px; outline:none; resize:none; margin-bottom:14px;"></textarea>

            <label style="font-size:12px; font-weight:700; color:var(--text-muted); display:block; margin-bottom:6px;">📂 Kategoriya</label>
            <select id="editModCategory" style="width:100%; padding:12px 14px; background:rgba(15,23,42,0.98); border:1px solid var(--primary-border); border-radius:12px; color:#fff; font-size:14px; outline:none; margin-bottom:18px; appearance:none; cursor:pointer;">
            </select>

            <div id="editStatusMsg" style="font-size:13px; margin-bottom:12px; display:none; border-radius:10px; padding:10px 14px;"></div>

            <div style="display:flex; gap:10px;">
                <button class="btn btn-primary" id="saveEditBtn" onclick="saveModChanges()" style="flex:1;">💾 Saqlash</button>
                <button class="btn btn-secondary" style="width:auto; padding:0 18px;" onclick="closeEditModal()">Bekor</button>
            </div>
        </div>
    </div>

    <!-- Contact Admin Modal (Sends to WebApp API) -->
    <div class="modal" id="contactModal">
        <div class="modal-content">
            <h3 style="font-size: 18px; font-weight: 700; margin-bottom: 10px;">💬 Adminga xabar yuborish</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">Savol yoki taklifingizni yozib qoldiring (Web App orqali yuboriladi):</p>
            <textarea id="contactMsgText" style="width: 100%; height: 110px; background: rgba(15, 23, 42, 0.95); border: 1px solid var(--primary-border); border-radius: 14px; padding: 12px; color: #fff; font-size: 14px; outline: none; margin-bottom: 12px; resize: none;" placeholder="Xabaringizni yozing..."></textarea>
            <div id="contactStatusMsg" style="font-size: 13px; margin-bottom: 10px; display: none;"></div>
            <div style="display: flex; gap: 10px;">
                <button class="btn btn-primary" id="sendHelpBtn" onclick="submitAdminHelp()" style="flex: 1;">🚀 Yuborish</button>
                <button class="btn btn-secondary" style="width: auto; padding: 0 16px;" onclick="closeContactModal()">Bekor qilish</button>
            </div>
        </div>
    </div>

    <!-- Installation Guide Modal -->
    <div class="modal" id="guideModal">
        <div class="modal-content">
            <h3 style="font-size: 18px; font-weight: 700; margin-bottom: 12px; color: var(--primary);">📖 Modlarni O'rnatish Qo'llanmasi</h3>
            
            <div style="display: flex; gap: 6px; margin-bottom: 14px; background: rgba(15,23,42,0.8); padding: 4px; border-radius: 10px;">
                <button class="btn btn-primary" id="tabAndroid" onclick="switchGuideTab('android')" style="flex:1; padding: 8px; font-size: 12px;">📱 Android</button>
                <button class="btn btn-secondary" id="tabIos" onclick="switchGuideTab('ios')" style="flex:1; padding: 8px; font-size: 12px;">🍎 iOS</button>
                <button class="btn btn-secondary" id="tabPc" onclick="switchGuideTab('pc')" style="flex:1; padding: 8px; font-size: 12px;">💻 PC</button>
            </div>

            <div id="guideAndroid" style="font-size: 13px; color: #cbd5e1; line-height: 1.6;">
                <p><b>1.</b> Mod faylini (<code>.mcaddon</code> / <code>.mcpack</code>) yuklab oling.</p>
                <p><b>2.</b> ZArchiver orqali faylni bosing va <b>"Minecraft bilan ochish"</b> ni tanlang.</p>
                <p><b>3.</b> O'yin avtomatik ochilib, mod yuklanadi.</p>
            </div>

            <div id="guideIos" style="display: none; font-size: 13px; color: #cbd5e1; line-height: 1.6;">
                <p><b>1.</b> Faylni yuklab olgach, <b>Fayllar (Files)</b> ilovasiga saqlang.</p>
                <p><b>2.</b> Faylni uzoq bosib <b>"Uzatish" (Share)</b> ➔ <b>Minecraft</b> ni tanlang.</p>
            </div>

            <div id="guidePc" style="display: none; font-size: 13px; color: #cbd5e1; line-height: 1.6;">
                <p><b>1.</b> <code>.mcaddon</code> faylini yuklab oling.</p>
                <p><b>2.</b> Fayl ustiga <b>2 marta bosing</b> — Minecraft avtomatik o'rnatadi.</p>
            </div>

            <button class="btn btn-primary" style="margin-top: 16px;" onclick="closeGuideModal()">Tushunarli &rsaquo;</button>
        </div>
    </div>

    <script>
        const tg = window.Telegram?.WebApp;
        if(tg) tg.expand();

        let currentCategory = 'all';
        let allMods = [];
        let searchTimeout = null;
        let audioCtx = null;
        let soundEnabled = true;

        /* Category Items with Favorites, Shader & Horror Added */
        const categories = [
            {"id": "all", "name": "Barchasi", "tag": "#all", "icon": "⚡"},
            {"id": "favorites", "name": "Saqlanganlar", "tag": "#fav", "icon": "❤️"},
            {"id": "cars", "name": "Avtomobillar", "tag": "#cars", "icon": "🚗"},
            {"id": "guns", "name": "Qurollar", "tag": "#guns", "icon": "⚔️"},
            {"id": "shaders", "name": "Shaderlar", "tag": "#shaders", "icon": "✨"},
            {"id": "horror", "name": "Horror (Qo'rqinchli)", "tag": "#horror", "icon": "👻"},
            {"id": "worlds", "name": "Dunyolar", "tag": "#addon", "icon": "🌍"},
            {"id": "minecraft", "name": "MINECRAFT", "tag": "#minecraft", "icon": "⛏️"},
            {"id": "addons", "name": "Addonlar (Qo'shimchalar)", "tag": "#addon", "icon": "🧩"},
            {"id": "textures", "name": "TEKSTURALAR", "tag": "#textures", "icon": "🎨"}
        ];

        /* Favorites LocalStorage Helpers */
        function getFavorites() {
            try {
                return JSON.parse(localStorage.getItem('mc_favs') || '[]');
            } catch(e) { return []; }
        }

        function toggleFavorite(modId, event) {
            if(event) event.stopPropagation();
            let favs = getFavorites();
            if(favs.includes(modId)) {
                favs = favs.filter(id => id !== modId);
            } else {
                favs.push(modId);
            }
            try { localStorage.setItem('mc_favs', JSON.stringify(favs)); } catch(e) {}
            filterMods();
            const modal = document.getElementById('modModal');
            if(modal && modal.style.display === 'flex') {
                showModDetail(modId);
            }
        }

        /* CSS Variables Theme Engine */
        const themePalettes = {
            green: {
                primary: '#10b981', primaryHover: '#059669', primaryGlow: 'rgba(16, 185, 129, 0.35)',
                primaryBorder: 'rgba(16, 185, 129, 0.3)', primaryBgSubtle: 'rgba(16, 185, 129, 0.12)',
                secondary: '#60a5fa', bgRadial: 'radial-gradient(circle at 50% 0%, #064e3b 0%, #090d16 85%)',
                bannerGrad: 'linear-gradient(135deg, #34d399, #60a5fa)'
            },
            blue: {
                primary: '#3b82f6', primaryHover: '#2563eb', primaryGlow: 'rgba(59, 130, 246, 0.35)',
                primaryBorder: 'rgba(96, 165, 250, 0.3)', primaryBgSubtle: 'rgba(59, 130, 246, 0.12)',
                secondary: '#a855f7', bgRadial: 'radial-gradient(circle at 50% 0%, #1e3a8a 0%, #090d16 85%)',
                bannerGrad: 'linear-gradient(135deg, #60a5fa, #a855f7)'
            },
            red: {
                primary: '#ef4444', primaryHover: '#dc2626', primaryGlow: 'rgba(239, 68, 68, 0.35)',
                primaryBorder: 'rgba(248, 113, 113, 0.3)', primaryBgSubtle: 'rgba(239, 68, 68, 0.12)',
                secondary: '#fbbf24', bgRadial: 'radial-gradient(circle at 50% 0%, #7f1d1d 0%, #090d16 85%)',
                bannerGrad: 'linear-gradient(135deg, #f87171, #fbbf24)'
            },
            purple: {
                primary: '#a855f7', primaryHover: '#9333ea', primaryGlow: 'rgba(168, 85, 247, 0.35)',
                primaryBorder: 'rgba(192, 132, 252, 0.3)', primaryBgSubtle: 'rgba(168, 85, 247, 0.12)',
                secondary: '#f472b6', bgRadial: 'radial-gradient(circle at 50% 0%, #581c87 0%, #090d16 85%)',
                bannerGrad: 'linear-gradient(135deg, #c084fc, #f472b6)'
            }
        };

        function setTheme(tName) {
            const p = themePalettes[tName] || themePalettes.green;
            const root = document.documentElement;
            root.style.setProperty('--primary', p.primary);
            root.style.setProperty('--primary-hover', p.primaryHover);
            root.style.setProperty('--primary-glow', p.primaryGlow);
            root.style.setProperty('--primary-border', p.primaryBorder);
            root.style.setProperty('--primary-bg-subtle', p.primaryBgSubtle);
            root.style.setProperty('--secondary', p.secondary);
            root.style.setProperty('--bg-radial', p.bgRadial);
            root.style.setProperty('--banner-grad', p.bannerGrad);

            ['green', 'blue', 'red', 'purple'].forEach(k => {
                const btn = document.getElementById('dot-' + k);
                if(btn) btn.style.borderColor = (k === tName) ? '#ffffff' : 'transparent';
            });
            try { localStorage.setItem('mc_theme', tName); } catch(e) {}
        }

        /* Sound FX */
        function toggleSound() {
            soundEnabled = !soundEnabled;
            const btn = document.getElementById('soundToggleBtn');
            if(btn) {
                btn.innerText = soundEnabled ? "🔊 Ovoz: Yoqilgan" : "🔇 Ovoz: O'chirilgan";
                btn.style.color = soundEnabled ? "var(--primary)" : "#ef4444";
            }
        }

        function playMinecraftClick() {
            if(!soundEnabled) return;
            try {
                if(!audioCtx) {
                    const AudioCtx = window.AudioContext || window.webkitAudioContext;
                    if(AudioCtx) audioCtx = new AudioCtx();
                }
                if(audioCtx && audioCtx.state === 'suspended') {
                    audioCtx.resume();
                }
                if(!audioCtx) return;

                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(170, audioCtx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(35, audioCtx.currentTime + 0.045);
                gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.045);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start();
                osc.stop(audioCtx.currentTime + 0.045);
            } catch(e) {}
        }

        document.addEventListener('click', function(e) {
            if(e.target.closest('button, .chip, .mod-card, a')) {
                playMinecraftClick();
            }
        });

        /* Category Chips Render */
        function renderChips() {
            const container = document.getElementById('chipsContainer');
            container.innerHTML = categories.map(c => `
                <div class="chip ${c.id === currentCategory ? 'active' : ''}" onclick="selectCategory('${c.id}')">
                    <span>${c.icon}</span>
                    <span>${c.name}</span>
                </div>
            `).join('');
        }

        function selectCategory(catId) {
            currentCategory = catId;
            renderChips();
            filterMods();
        }

        /* Fast Debounced Search Filter */
        function debouncedFilter() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                filterMods();
            }, 120);
        }

        function filterMods() {
            const q = document.getElementById('searchInput').value.trim().toLowerCase();
            let filtered = allMods;

            if(currentCategory === 'favorites') {
                const favs = getFavorites();
                filtered = filtered.filter(m => favs.includes(m.id));
            } else if(currentCategory !== 'all') {
                filtered = filtered.filter(m => 
                    m.category === currentCategory || 
                    (currentCategory === 'addons' && (m.category === 'addon' || m.category === 'addons')) ||
                    (currentCategory === 'worlds' && (m.category === 'world' || m.category === 'worlds')) ||
                    (currentCategory === 'shaders' && (m.category === 'shader' || m.category === 'shaders')) ||
                    (currentCategory === 'horror' && (m.category === 'horror' || m.category === 'scary'))
                );
            }

            if(q) {
                filtered = filtered.filter(m => 
                    (m.name && m.name.toLowerCase().includes(q)) || 
                    (m.description && m.description.toLowerCase().includes(q)) ||
                    (m.category && m.category.toLowerCase().includes(q))
                );
            }

            renderMods(filtered);
        }

        function renderMods(list) {
            const container = document.getElementById('modsContainer');
            const badge = document.getElementById('modCountBadge');
            badge.innerText = list.length + ' ta';

            if(list.length === 0) {
                if(currentCategory === 'favorites') {
                    container.innerHTML = `
                        <div class="empty-box">
                            ❤️ Hali hech qanday mod saqlanmagan!<br>O'zingizga yoqqan modlardagi ❤️ tugmasini bosing.
                        </div>
                    `;
                } else {
                    container.innerHTML = `
                        <div class="empty-box">
                            📭 Hech qanday mod topilmadi!<br>Qidiruvni o'zgartiring yoki boshqa kategoriyani tanlang.
                        </div>
                    `;
                }
                return;
            }

            const favs = getFavorites();
            container.innerHTML = list.map(m => {
                const isFav = favs.includes(m.id);
                return `
                <div class="mod-card">
                    <div style="position:relative;">
                        ${m.cover_url ? `<img class="mod-img" src="${m.cover_url}" alt="${m.name}" loading="lazy" onerror="this.onerror=null; this.style.display='none';">` : ''}
                        <button class="fav-btn" onclick="toggleFavorite('${m.id}', event)" title="Saqlash">
                            ${isFav ? '❤️' : '🤍'}
                        </button>
                        ${window.isAdmin ? `<button class="edit-btn" onclick="openEditModal('${m.id}', event)" title="Tahrirlash">✏️</button>` : ''}
                    </div>
                    <div class="mod-body">
                        <div class="mod-header">
                            <div class="mod-title">${m.name}</div>
                            <div class="mod-badge">⬇️ ${m.downloads || 0}</div>
                        </div>
                        <div class="mod-desc">${m.description || 'Tavsif mavjud emas.'}</div>
                        <button class="btn btn-primary" onclick="showModDetail('${m.id}')">Batafsil &rsaquo;</button>
                    </div>
                </div>
            `;
            }).join('');
        }

        async function loadMods() {
            try {
                const res = await fetch('/api/mods');
                allMods = await res.json();
            } catch(e) {
                console.error(e);
            }
            renderChips();
            filterMods();
        }

        /* Referral Link Copy Functionality */
        function copyRefLink() {
            const uid = tg?.initDataUnsafe?.user?.id || 0;
            const link = 'https://t.me/UZBMCBOT?start=ref_' + uid;
            
            if(navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(link).then(() => {
                    const btn = document.getElementById('qRefBtn');
                    btn.innerText = '✅ Havola Nusxalandi!';
                    setTimeout(() => { btn.innerText = '📋 Havolani nusxalash'; }, 2000);
                }).catch(() => {
                    openTelegramShare(link);
                });
            } else {
                openTelegramShare(link);
            }
        }

        function openTelegramShare(link) {
            if(tg && tg.openTelegramLink) {
                tg.openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(link) + '&text=' + encodeURIComponent('Minecraft modlarini ushbu botdan bepul yuklab oling! 🚀'));
            } else {
                window.open('https://t.me/share/url?url=' + encodeURIComponent(link), '_blank');
            }
        }

        /* Mod Detail Modal */
        function showModDetail(modId) {
            const m = allMods.find(x => x.id === modId);
            if(!m) return;
            
            const favs = getFavorites();
            const isFav = favs.includes(m.id);

            const modalBody = document.getElementById('modalBody');
            modalBody.innerHTML = `
                <div style="position:relative;">
                    ${m.cover_url ? `<img src="${m.cover_url}" style="width:100%; height:200px; object-fit:cover; border-radius:16px; margin-bottom:14px;" onerror="this.onerror=null; this.style.display='none';">` : ''}
                    <button class="fav-btn" onclick="toggleFavorite('${m.id}', event)" style="top:12px; right:12px;">
                        ${isFav ? '❤️' : '🤍'}
                    </button>
                </div>
                <h3 style="font-size:20px; font-weight:700; margin-bottom:6px; color:#fff;">${m.name}</h3>
                <p style="font-size:13px; color:var(--text-muted); line-height:1.5; margin-bottom:16px; white-space:pre-line;">${m.description}</p>
                
                <div style="display:flex; gap:10px; margin-bottom:16px;">
                    <a href="https://t.me/UZBMCBOT?start=${m.id}" class="btn btn-primary" style="text-decoration:none; flex:1;">⬇️ Yuklab olish</a>
                    <button class="btn btn-secondary" style="width:auto;" onclick="openGuideModal()">📖 Yo'riqnoma</button>
                </div>

                <div style="border-top: 1px solid var(--card-border); padding-top: 14px; margin-top: 14px;">
                    <h4 style="font-size: 15px; font-weight: 700; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;">
                        <span>💬 Izohlar</span>
                        <span id="commentCountBadge" style="font-size: 11px; background: var(--primary-bg-subtle); color: var(--primary); padding: 2px 8px; border-radius: 10px;">0 ta</span>
                    </h4>
                    
                    <div style="display:flex; gap:8px; margin-bottom:12px;">
                        <input type="text" id="newCommentInput" placeholder="Izoh yozing..." style="flex:1; background:rgba(15,23,42,0.9); border:1px solid var(--primary-border); border-radius:10px; padding:8px 12px; color:#fff; font-size:13px; outline:none;">
                        <button class="btn btn-primary" style="width:auto; padding:8px 14px;" onclick="postComment('${m.id}')">Yuborish</button>
                    </div>

                    <div id="commentsList" style="display:flex; flex-direction:column; gap:8px; max-height:180px; overflow-y:auto;">
                        <div style="font-size:12px; color:var(--text-muted); text-align:center;">Yuklanmoqda...</div>
                    </div>
                </div>
            `;
            document.getElementById('modModal').style.display = 'flex';
            loadComments(modId);
        }

        async function loadComments(modId) {
            try {
                const res = await fetch('/api/comments?mod_id=' + modId);
                const comments = await res.json();
                const list = document.getElementById('commentsList');
                const badge = document.getElementById('commentCountBadge');
                if(badge) badge.innerText = comments.length + ' ta';
                
                if(comments.length === 0) {
                    list.innerHTML = `<div style="font-size:12px; color:var(--text-muted); text-align:center; padding:10px;">Birinchi bo'lib izoh qoldiring! 💬</div>`;
                } else {
                    list.innerHTML = comments.map(c => `
                        <div style="background:rgba(255,255,255,0.03); border:1px solid var(--card-border); border-radius:10px; padding:8px 10px;">
                            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
                                <span style="font-size:12px; font-weight:700; color:var(--primary);">👤 ${c.user_name}</span>
                                <span style="font-size:10px; color:var(--text-muted);">${c.date}</span>
                            </div>
                            <div style="font-size:12px; color:#e2e8f0; line-height:1.4;">${c.text}</div>
                        </div>
                    `).join('');
                }
            } catch(e) {}
        }

        async function postComment(modId) {
            const input = document.getElementById('newCommentInput');
            const txt = input ? input.value.trim() : '';
            if(!txt) return;
            
            const user = tg?.initDataUnsafe?.user || {};
            const payload = {
                mod_id: modId,
                user_id: user.id || 0,
                user_name: (user.first_name || 'Foydalanuvchi') + (user.last_name ? ' ' + user.last_name : ''),
                text: txt
            };

            input.value = '';
            try {
                const res = await fetch('/api/comments', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const d = await res.json();
                if(d.ok) loadComments(modId);
            } catch(e) {}
        }

        function closeModal() { document.getElementById('modModal').style.display = 'none'; }
        function openAdminHelp() {
            document.getElementById('contactMsgText').value = '';
            document.getElementById('contactStatusMsg').style.display = 'none';
            document.getElementById('contactModal').style.display = 'flex';
        }
        function closeContactModal() { document.getElementById('contactModal').style.display = 'none'; }

        async function submitAdminHelp() {
            const txt = document.getElementById('contactMsgText').value.trim();
            const statusDiv = document.getElementById('contactStatusMsg');
            if(!txt) {
                statusDiv.style.color = '#ef4444';
                statusDiv.style.display = 'block';
                statusDiv.innerText = '⚠️ Iltimos, xabaringizni yozing!';
                return;
            }

            const user = tg?.initDataUnsafe?.user || {};
            const payload = {
                user_id: user.id || 0,
                user_name: (user.first_name || 'Foydalanuvchi') + (user.last_name ? ' ' + user.last_name : ''),
                text: txt
            };

            document.getElementById('sendHelpBtn').innerText = '⏳ Yuborilmoqda...';
            document.getElementById('sendHelpBtn').disabled = true;

            try {
                const res = await fetch('/api/contact', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const d = await res.json();
                if(d.ok) {
                    statusDiv.style.color = 'var(--primary)';
                    statusDiv.style.display = 'block';
                    statusDiv.innerText = '✅ Xabaringiz Web App orqali adminga yuborildi!';
                    setTimeout(() => {
                        closeContactModal();
                        document.getElementById('sendHelpBtn').innerText = '🚀 Yuborish';
                        document.getElementById('sendHelpBtn').disabled = false;
                    }, 1500);
                } else throw new Error();
            } catch(e) {
                statusDiv.style.color = '#ef4444';
                statusDiv.style.display = 'block';
                statusDiv.innerText = '❌ Xabar yuborishda xatolik!';
                document.getElementById('sendHelpBtn').innerText = '🚀 Yuborish';
                document.getElementById('sendHelpBtn').disabled = false;
            }
        }

        function openGuideModal() { document.getElementById('guideModal').style.display = 'flex'; }
        function closeGuideModal() { document.getElementById('guideModal').style.display = 'none'; }
        function switchGuideTab(tab) {
            ['Android', 'Ios', 'Pc'].forEach(t => {
                const el = document.getElementById('guide' + t);
                if(el) el.style.display = (t.toLowerCase() === tab) ? 'block' : 'none';
                const btn = document.getElementById('tab' + t);
                if(btn) {
                    if(t.toLowerCase() === tab) {
                        btn.className = "btn btn-primary";
                    } else {
                        btn.className = "btn btn-secondary";
                    }
                }
            });
        }

        /* Mandatory Channel Subscription Check Matching Image Exactly */
        async function checkSub() {
            const userId = tg?.initDataUnsafe?.user?.id;
            if(!userId) return;
            try {
                const res = await fetch('/api/check_sub?user_id=' + userId);
                const data = await res.json();
                if(!data.subscribed) {
                    const box = document.getElementById('subChannelsList');
                    box.innerHTML = data.channels.map(ch => `
                        <a href="https://t.me/${ch.replace('@','')}" target="_blank" class="channel-btn">
                            <span style="color:#ef4444; font-size:16px;">❌</span>
                            <span>${ch.replace('@','').toUpperCase()}</span>
                        </a>
                    `).join('');
                    document.getElementById('subModal').style.display = 'flex';
                } else {
                    document.getElementById('subModal').style.display = 'none';
                }
            } catch(e) {}
        }

        function checkSubAgain() { checkSub(); }

        /* ===================== ADMIN MOD EDIT ===================== */
        window.isAdmin = false;

        async function checkAdmin() {
            try {
                const uid = tg?.initDataUnsafe?.user?.id || 0;
                if(!uid) return;
                const res = await fetch('/api/is_admin?user_id=' + uid);
                const d = await res.json();
                window.isAdmin = !!d.is_admin;
            } catch(e) {}
        }

        function openEditModal(modId, event) {
            if(event) event.stopPropagation();
            const m = allMods.find(x => x.id === modId);
            if(!m) return;

            document.getElementById('editModId').value = modId;
            document.getElementById('editModName').value = m.name || '';
            document.getElementById('editModDesc').value = m.description || '';

            // Populate category dropdown
            const sel = document.getElementById('editModCategory');
            sel.innerHTML = categories
                .filter(c => c.id !== 'all' && c.id !== 'favorites')
                .map(c => `<option value="${c.id}" ${m.category === c.id ? 'selected' : ''}>${c.icon} ${c.name}</option>`)
                .join('');

            document.getElementById('editStatusMsg').style.display = 'none';
            document.getElementById('saveEditBtn').disabled = false;
            document.getElementById('saveEditBtn').innerText = '💾 Saqlash';
            document.getElementById('editModModal').style.display = 'flex';
        }

        function closeEditModal() {
            document.getElementById('editModModal').style.display = 'none';
        }

        async function saveModChanges() {
            const modId   = document.getElementById('editModId').value;
            const name    = document.getElementById('editModName').value.trim();
            const desc    = document.getElementById('editModDesc').value.trim();
            const cat     = document.getElementById('editModCategory').value;
            const statusDiv = document.getElementById('editStatusMsg');
            const saveBtn   = document.getElementById('saveEditBtn');

            if(!name) {
                statusDiv.style.cssText = 'display:block; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); color:#f87171; border-radius:10px; padding:10px 14px; font-size:13px; margin-bottom:12px;';
                statusDiv.innerText = '⚠️ Mod nomini kiriting!';
                return;
            }

            saveBtn.innerText = '⏳ Saqlanmoqda...';
            saveBtn.disabled = true;

            try {
                const uid = tg?.initDataUnsafe?.user?.id || 0;
                const res = await fetch('/api/edit_mod', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: uid, mod_id: modId, name, description: desc, category: cat })
                });
                const d = await res.json();
                if(d.ok) {
                    // Update local list
                    const idx = allMods.findIndex(x => x.id === modId);
                    if(idx !== -1) {
                        allMods[idx].name = name;
                        allMods[idx].description = desc;
                        allMods[idx].category = cat;
                    }
                    closeEditModal();
                    filterMods();
                    showToast('✅ Mod muvaffaqiyatli saqlandi!');
                } else {
                    throw new Error(d.error || 'Xato');
                }
            } catch(e) {
                statusDiv.style.cssText = 'display:block; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); color:#f87171; border-radius:10px; padding:10px 14px; font-size:13px; margin-bottom:12px;';
                statusDiv.innerText = '❌ Saqlashda xatolik: ' + e.message;
                saveBtn.disabled = false;
                saveBtn.innerText = '💾 Saqlash';
            }
        }

        /* Toast helper */
        let toastTimer = null;
        function showToast(msg) {
            let toast = document.getElementById('globalToast');
            if(!toast) {
                toast = document.createElement('div');
                toast.id = 'globalToast';
                toast.className = 'toast';
                document.body.appendChild(toast);
            }
            toast.innerText = msg;
            toast.classList.add('show');
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => toast.classList.remove('show'), 2800);
        }

        // Init
        try {
            const savedTheme = localStorage.getItem('mc_theme') || 'green';
            setTheme(savedTheme);
        } catch(e) {}

        checkAdmin().then(() => loadMods());
        checkSub();
    </script>
</body>
</html>
"""

class WebAppHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/comments":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                payload = json.loads(post_data)
                mod_id = payload.get("mod_id", "")
                user_id = payload.get("user_id", 0)
                user_name = payload.get("user_name", "Foydalanuvchi")
                text = payload.get("text", "")
                
                if mod_id and text:
                    comments_db = data.setdefault("comments", {})
                    mod_comments = comments_db.setdefault(mod_id, [])
                    new_c = {
                        "user_id": user_id,
                        "user_name": escape(user_name),
                        "text": escape(text),
                        "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
                    }
                    mod_comments.append(new_c)
                    save_data()
                    
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
            return

        if parsed.path == "/api/contact":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                payload = json.loads(post_data)
                user_id = payload.get("user_id", 0)
                user_name = payload.get("user_name", "Foydalanuvchi")
                text = payload.get("text", "")
                
                if text and user_id:
                    for admin_id in data.get("admins", []):
                        user_link = f'<a href="tg://user?id={user_id}"><b>{escape(user_name)}</b></a>'
                        msg = (
                            f"📩 <b>Yangi Yordam Xabari (Web App dan)!</b>\n\n"
                            f"👤 <b>Foydalanuvchi:</b> {user_link} (ID: <code>{user_id}</code>)\n"
                            f"💬 <b>Xabar:</b> {escape(text)}\n"
                            f"📅 <b>Vaqt:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                            f"💡 <i>Ushbu xabarga Telegram'da 'Reply' (Javob berish) qilib javob yozsangiz, javobingiz avtomatik foydalanuvchiga boradi!</i>"
                        )
                        kb = inline_kb([[button(f"👤 {user_name} profiliga o'tish", url=f"tg://user?id={user_id}")]])
                        res_msg = send_message(admin_id, msg, kb)
                        try:
                            if res_msg.get("ok"):
                                register_reply(res_msg["result"]["message_id"], user_id, user_id, user_name)
                        except Exception:
                            pass
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
            return

        if parsed.path == "/api/edit_mod":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                payload = json.loads(post_data)
                user_id = int(payload.get("user_id", 0))
                if user_id not in data.get("admins", ADMIN_IDS):
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "error": "Ruxsat yo'q"}).encode())
                    return
                mod_id = payload.get("mod_id", "")
                mods = data.get("mods", {})
                if mod_id not in mods:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "error": "Mod topilmadi"}).encode())
                    return
                if payload.get("name"):       mods[mod_id]["name"]        = escape(payload["name"])
                if payload.get("description"): mods[mod_id]["description"] = escape(payload["description"])
                if payload.get("category"):   mods[mod_id]["category"]    = payload["category"]
                save_data(backup=False)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
            return

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(WEBAPP_HTML.encode("utf-8"))
            return

        if path == "/api/comments":
            mod_id = query.get("mod_id", [""])[0]
            comments = data.get("comments", {}).get(mod_id, [])
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(comments, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/mods":
            mods_list = []
            for m_id, m in data.get("mods", {}).items():
                cover_url = ""
                if m.get("cover_file"):
                    cover_url = f"/mods_static/{os.path.basename(m['cover_file'])}"
                elif m.get("cover_id"):
                    cover_url = f"/mods_static/{m_id}.jpg"
                mods_list.append({
                    "id": m_id,
                    "name": m.get("name", "Nomsiz"),
                    "description": m.get("description", ""),
                    "category": m.get("category", "minecraft"),
                    "cover_url": cover_url,
                    "date": m.get("date", ""),
                    "downloads": m.get("downloads", 0)
                })
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(mods_list, ensure_ascii=False).encode("utf-8"))
            return

        if path.startswith("/mods_static/"):
            fname = os.path.basename(path)
            fpath = os.path.join(MODS_DIR, fname)
            
            # Dynamic auto-download from Telegram API if missing locally on Render
            if not os.path.exists(fpath):
                for m_id, m in data.get("mods", {}).items():
                    c_file = m.get("cover_file", "")
                    c_id = m.get("cover_id", "")
                    if (c_file and os.path.basename(c_file) == fname) or (m_id + ".jpg" == fname) or (m_id == fname):
                        if c_id:
                            download_file(c_id, fpath)
                            break
            
            if os.path.exists(fpath):
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                with open(fpath, "rb") as f:
                    self.wfile.write(f.read())
                return

        if path == "/api/check_sub":
            uid = query.get("user_id", ["0"])[0]
            try:
                user_id = int(uid)
                missing = check_channels(user_id)
                res = {"subscribed": len(missing) == 0, "channels": data.get("channels", [])}
            except Exception:
                res = {"subscribed": True, "channels": []}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        if path == "/api/is_admin":
            uid = query.get("user_id", ["0"])[0]
            try:
                is_adm = int(uid) in data.get("admins", ADMIN_IDS)
            except Exception:
                is_adm = False
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"is_admin": is_adm}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass

class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True

def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        server = ThreadedHTTPServer(('0.0.0.0', port), WebAppHandler)
        print(f"Threaded Web server started on port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"Web server error: {e}")

threading.Thread(target=start_web_server, daemon=True).start()

# ================= TELEGRAM API WRAPPERS =================
def api_request(method, params=None, files=None):
    url = API_URL + method
    try:
        if files:
            res = requests.post(url, data=params, files=files, timeout=75)
        elif params:
            res = requests.post(url, data=params, timeout=45)
        else:
            res = requests.get(url, timeout=45)
        return res.json()
    except Exception as e:
        print(f"API Request error ({method}): {e}")
        return {"ok": False}

def button(text, callback_data=None, url=None, web_app=None):
    b = {"text": text}
    if callback_data is not None:
        b["callback_data"] = callback_data
    if url is not None:
        b["url"] = url
    if web_app is not None:
        b["web_app"] = {"url": web_app}
    return b

def inline_kb(rows):
    return {"inline_keyboard": rows}

def send_message(chat_id, text, keyboard=None):
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }
    if keyboard is not None:
        params["reply_markup"] = json.dumps(keyboard)
    return api_request("sendMessage", params)

def send_photo(chat_id, photo, caption="", keyboard=None):
    params = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if keyboard is not None:
        params["reply_markup"] = json.dumps(keyboard)
    
    if os.path.exists(photo):
        with open(photo, "rb") as f:
            files = {"photo": f}
            return api_request("sendPhoto", params=params, files=files)
    else:
        params["photo"] = photo
        return api_request("sendPhoto", params=params)

def send_document(chat_id, document, caption=""):
    params = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if os.path.exists(document):
        with open(document, "rb") as f:
            files = {"document": (os.path.basename(document), f, "application/octet-stream")}
            return api_request("sendDocument", params=params, files=files)
    else:
        params["document"] = document
        return api_request("sendDocument", params=params)

def edit_message(chat_id, message_id, text, keyboard=None):
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if keyboard is not None:
        params["reply_markup"] = json.dumps(keyboard)
    return api_request("editMessageText", params)

def answer_callback(cid, text=None, alert=False):
    params = {"callback_query_id": cid}
    if text is not None:
        params["text"] = text
        params["show_alert"] = "true" if alert else "false"
    return api_request("answerCallbackQuery", params)

def download_file(file_id, save_path):
    res = api_request("getFile", {"file_id": file_id})
    if not res.get("ok"):
        return False
    path = res["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
    try:
        r = requests.get(url, stream=True, timeout=60)
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"Download file error: {e}")
    return False

# ================= MAJBURII OBUNA =================
def check_channels(user_id):
    missing = []
    for ch in data.get("channels", []):
        res = api_request("getChatMember", {"chat_id": ch, "user_id": user_id})
        if res.get("ok"):
            st = res.get("result", {}).get("status", "")
            if st not in ["member", "administrator", "creator"]:
                missing.append(ch)
    return missing

def is_subscribed(user_id):
    if is_admin(user_id):
        return True
    return len(check_channels(user_id)) == 0

def subscription_keyboard(missing):
    rows = []
    for ch in missing:
        s = str(ch)
        url = "https://t.me/" + (s[1:] if s.startswith("@") else s)
        rows.append([button("📢 " + s, url=url)])
    rows.append([button("Obunani tekshirish ♻️", callback_data="check_subscription")])
    return inline_kb(rows)

def send_subscription_warning(chat_id, missing):
    t = "⚠️ <b>siz kanallarga obuna bo'lmagansiz</b> ⚠️\n\n"
    t += "❗️ <b>iltimos obuna bo'lib ushbu tugmani bosing</b> ❗️ :\n"
    t += "obunanani tekshirish ♻️"
    send_message(chat_id, t, subscription_keyboard(missing))

def process_start_payload(chat_id, user_id, user_name, param):
    """Handles a /start deep-link payload (ref_ or mod_).
    Returns True if it fully handled the request (caller should not show the welcome menu)."""
    if param.startswith("ref_"):
        inv_id = param.replace("ref_", "")
        track_user(user_id, user_name, inviter_id=inv_id)
        return False
    elif param.startswith("mod_"):
        mod_id = param
        if mod_id in data.get("mods", {}):
            mod = data["mods"][mod_id]
            dl = mod.get("downloads", 0) + 1
            mod["downloads"] = dl
            save_data()

            info = f"📦 <b>{escape(mod.get('name', ''))}</b>\n\n📝 {escape(mod.get('description', ''))}\n📅 {mod.get('date', '')}\n⬇️ Yuklanishlar: {dl}"
            if mod.get("cover_file") and os.path.exists(mod["cover_file"]):
                send_photo(chat_id, mod["cover_file"], info)
            elif mod.get("cover_id"):
                send_photo(chat_id, mod["cover_id"], info)
            else:
                send_message(chat_id, info)

            for f in mod.get("files", []):
                if f.get("file_path") and os.path.exists(f["file_path"]):
                    send_document(chat_id, f["file_path"], f.get("file_name", ""))
                elif f.get("file_id"):
                    send_document(chat_id, f["file_id"], f.get("file_name", ""))
            return True
        else:
            send_message(chat_id, "❌ Mod topilmadi!")
            return True
    return False

def send_welcome(chat_id, user_id, user_name):
    welcome = (
        f"Salom, <b>{escape(user_name)}</b> 👋!\n"
        f"🎉 <b>Minecraft Mod Botga xush kelibsiz!</b> 🎉\n\n"
        f"🤖 <b>Buyruqlar:</b>\n"
        f"/start - Qayta boshlash ♻️\n"
        f"/mods - Barcha modlar 🗳️\n"
        f"/help - Adminga yozish 📝\n"
        f"/ref - Do'stlarni taklif qilish 🎁\n"
    )
    if is_admin(user_id):
        welcome += (
            f"/upload - Kontent yuborish 📤\n"
            f"/admin - Admin qo'shish 👤\n"
            f"/broadcast - Xabar tarqatish 📢\n"
            f"/panel - Admin panel 🛠️\n"
        )
    welcome += f"\n🌐 Kanal: @{CHANNEL_USERNAME}"
    send_message(chat_id, welcome, main_keyboard(is_admin(user_id)))

# ================= KLAVIATURALAR =================
def main_keyboard(admin=False):
    rows = [
        [button(B_MODS), button(B_HELP)],
        [button(B_REF), button(B_GUIDE)]
    ]
    if admin:
        rows.append([button(B_UPLOAD), button(B_ADMIN)])
        rows.append([button(B_PANEL)])
    return {"keyboard": rows, "resize_keyboard": True}

def cancel_keyboard():
    return {"keyboard": [[button(B_CANCEL)]], "resize_keyboard": True}

def file_upload_keyboard():
    return {"keyboard": [[button(B_FILE_ADD), button(B_FILES_DONE)], [button(B_CANCEL)]], "resize_keyboard": True}

def category_keyboard():
    rows = []
    cat_items = [c for c in CATEGORIES if c["id"] != "all" and c["id"] != "favorites"]
    for i in range(0, len(cat_items), 2):
        row = [button(cat_items[i]["icon"] + " " + cat_items[i]["name"], callback_data="cat_select_" + cat_items[i]["id"])]
        if i + 1 < len(cat_items):
            row.append(button(cat_items[i+1]["icon"] + " " + cat_items[i+1]["name"], callback_data="cat_select_" + cat_items[i+1]["id"]))
        rows.append(row)
    return inline_kb(rows)

def admin_panel_keyboard():
    rows = [
        [button("➕ Admin qo'shish", callback_data="panel_admin_add"), button("➖ Admin olib tashlash", callback_data="panel_admin_del")],
        [button("📤 Mod qo'shish", callback_data="panel_mod_add"), button("🗑️ Mod olib tashlash", callback_data="panel_mod_del")],
        [button("✏️ Mod Tahrirlash", callback_data="panel_mod_edit"), button("📢 Obuna kanallari", callback_data="panel_channels")],
        [button("📢 Xabar tarqatish", callback_data="panel_broadcast"), button("📊 Statistika", callback_data="panel_stats")],
        [button("💾 Zaxira olish", callback_data="panel_backup"), button("🔄 Yangilash", callback_data="panel_refresh")],
        [button("❌ Yopish", callback_data="panel_close")]
    ]
    return inline_kb(rows)

# ================= FOYDALANUVCHILAR VA GURUH KUZATUVI =================
def track_user(user_id, user_name, inviter_id=None):
    uid = str(user_id)
    users = data.setdefault("users", {})
    if not isinstance(users, dict):
        users = {}
        data["users"] = users

    is_new = uid not in users
    if is_new:
        users[uid] = {
            "name": user_name,
            "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            "inviter": inviter_id,
            "invited_count": 0
        }
        if inviter_id and str(inviter_id) in users and str(inviter_id) != uid:
            inv_str = str(inviter_id)
            users[inv_str]["invited_count"] = users[inv_str].get("invited_count", 0) + 1
            try:
                msg = (
                    f"🎉 <b>Yangi do'st qo'shildi!</b>\n\n"
                    f"👤 <b>{escape(user_name)}</b> sizning taklif havolangiz orqali botga kirdi!\n"
                    f"👥 Jami taklif qilgan do'stlaringiz: <b>{users[inv_str]['invited_count']} kishi</b>"
                )
                send_message(int(inviter_id), msg)
            except Exception:
                pass
        save_data()
    elif users[uid].get("name") != user_name:
        users[uid]["name"] = user_name
        save_data()

def track_group(chat):
    if chat.get("type") in ("group", "supergroup"):
        cid = str(chat["id"])
        title = chat.get("title", "Noma'lum guruh")
        groups = data.setdefault("groups", {})
        if not isinstance(groups, dict):
            groups = {}
            data["groups"] = groups

        if cid not in groups or groups[cid].get("title") != title:
            groups[cid] = {"title": title, "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M")}
            save_data()

def register_reply(admin_msg_id, user_chat_id, user_id, user_name):
    data.setdefault("replies", {})[str(admin_msg_id)] = {
        "chat_id": user_chat_id,
        "user_id": user_id,
        "user_name": user_name
    }
    save_data()

def get_reply(message):
    if not message.get("reply_to_message"):
        return None
    mid = str(message["reply_to_message"]["message_id"])
    return data.get("replies", {}).get(mid)

def is_admin(user_id):
    return user_id in data.get("admins", [])

def get_state(user_id):
    return data.get("states", {}).get(str(user_id), {})

def set_state(user_id, state, extra=None):
    if "states" not in data:
        data["states"] = {}
    data["states"][str(user_id)] = {"state": state, "data": extra or {}}
    save_data()

def clear_state(user_id):
    if str(user_id) in data.get("states", {}):
        del data["states"][str(user_id)]
        save_data()

# ================= ADMIN PANEL MENUSI =================
def panel_text():
    total_dl = sum(m.get("downloads", 0) for m in data.get("mods", {}).values())
    info = f"🛠️ <b>ADMIN PANEL</b>\n\n"
    info += f"📦 Modlar soni: <b>{len(data.get('mods', {}))} ta</b>\n"
    info += f"⬇️ Jami yuklanishlar: <b>{total_dl} marta</b>\n"
    info += f"👤 Adminlar soni: <b>{len(data.get('admins', []))} kishi</b>\n"
    info += f"👥 Foydalanuvchilar: <b>{len(data.get('users', {}))} kishi</b>\n"
    info += f"💬 Guruhlar soni: <b>{len(data.get('groups', {}))} ta</b>\n"
    info += f"📢 Obuna kanallari: <b>{len(data.get('channels', []))} ta</b>\n\n"
    info += f"⚙️ <b>Qulay buyruqlar:</b>\n"
    info += f"📤 /upload - Mod yuklash\n"
    info += f"👤 /admin - Admin qo'shish\n"
    info += f"📢 /broadcast - Xabar tarqatish\n"
    info += f"📊 /stats - Statistika\n"
    info += f"📢 /channels - Obuna kanallari"
    return info

def show_admin_panel(chat_id, message_id=None):
    if message_id is not None:
        edit_message(chat_id, message_id, panel_text(), admin_panel_keyboard())
    else:
        send_message(chat_id, panel_text(), admin_panel_keyboard())

def show_channels(chat_id, message_id=None):
    chans = data.get("channels", [])
    if chans:
        t = "📢 <b>Majburiy obuna kanallari:</b>\n\n"
        for i, ch in enumerate(chans, 1):
            t += f"{i}. <code>{ch}</code>\n"
        t += "\nO'chirish uchun ustiga bosing yoki yangi kanal qo'shing:"
    else:
        t = "📢 Majburiy kanallar belgilanmagan.\n\n➕ Yangi kanal qo'shishingiz mumkin:"
    rows = []
    for ch in chans:
        rows.append([button("🗑️ " + str(ch), callback_data="chdel_" + str(ch))])
    rows.append([button("➕ Kanal qo'shish", callback_data="channel_add_btn")])
    rows.append([button("🔙 Panelga qaytish", callback_data="panel_back")])
    kb = inline_kb(rows)
    if message_id is not None:
        edit_message(chat_id, message_id, t, kb)
    else:
        send_message(chat_id, t, kb)

def show_stats(chat_id, message_id=None):
    users = data.get("users", {})
    groups = data.get("groups", {})
    total_dl = sum(m.get("downloads", 0) for m in data.get("mods", {}).values())
    t = "📊 <b>BOT STATISTIKASI</b>\n\n"
    t += f"👥 Foydalanuvchilar: <b>{len(users)} kishi</b>\n"
    t += f"💬 Guruhlar: <b>{len(groups)} ta</b>\n"
    t += f"📦 Modlar: <b>{len(data.get('mods', {}))} ta</b>\n"
    t += f"⬇️ Yuklanishlar: <b>{total_dl} marta</b>\n\n"
    if groups:
        t += "🌐 <b>Bot ishlayotgan so'nggi guruhlar:</b>\n"
        for g in list(groups.values())[-10:]:
            t += f"🔹 {escape(g.get('title', 'Noma\'lum'))}\n"
    else:
        t += "🌐 Bot hali guruhlarga qo'shilmagan."
    rows = [
        [button("🔄 Yangilash", callback_data="panel_stats")],
        [button("🔙 Panelga qaytish", callback_data="panel_back")]
    ]
    if message_id is not None:
        edit_message(chat_id, message_id, t, inline_kb(rows))
    else:
        send_message(chat_id, t, inline_kb(rows))

# ================= HANDLERS =================
def handle_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    user_name = message["from"].get("first_name", "Foydalanuvchi")

    if message["chat"].get("type") == "private":
        track_user(user_id, user_name)
    else:
        track_group(message["chat"])

    # Mandatory Channel Subscription Check (applies to /start too — nothing opens before subscribing)
    if message["chat"].get("type") == "private" and not is_subscribed(user_id):
        missing = check_channels(user_id)
        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                set_state(user_id, "pending_start", {"param": parts[1]})
        send_subscription_warning(chat_id, missing)
        return

    state_info = get_state(user_id)
    cur = state_info.get("state", "")
    sd = state_info.get("data", {})

    if text == B_CANCEL:
        clear_state(user_id)
        send_message(chat_id, "❌ Amaliyot bekor qilindi.", main_keyboard(is_admin(user_id)))
        return

    # Admin Reply-To-User System
    if is_admin(user_id) and cur == "" and message.get("reply_to_message"):
        rep = get_reply(message)
        if rep is not None:
            out = f"💬 <b>Admindan javob keldi:</b>\n\n{escape(text)}"
            res = send_message(rep["chat_id"], out)
            if res.get("ok"):
                send_message(chat_id, f"✅ Javob <b>{escape(rep['user_name'])}</b> ga yuborildi!")
            else:
                send_message(chat_id, "❌ Javob yuborishda xatolik yuz berdi.")
            return

    if text.startswith("/start"):
        clear_state(user_id)
        parts = text.split()
        if len(parts) > 1:
            handled = process_start_payload(chat_id, user_id, user_name, parts[1])
            if handled:
                return
        send_welcome(chat_id, user_id, user_name)
        return

    # Referral Share
    if text == B_REF or text == "/ref":
        uid = str(user_id)
        u_data = data.get("users", {}).get(uid, {})
        cnt = u_data.get("invited_count", 0)
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        msg = (
            f"🎁 <b>TAKLIFA HAVOLASI (REFERAL)</b>\n\n"
            f"👤 <b>Sizning ID:</b> <code>{user_id}</code>\n"
            f"👥 <b>Taklif qilgan do'stlaringiz:</b> <b>{cnt} kishi</b>\n\n"
            f"🔗 <b>Sizning shaxsiy havolangiz:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"💡 <i>Ushbu havolani do'stlaringizga yuboring. Ular botga kirsa sizga xabar boradi!</i>"
        )
        share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote('Minecraft modlarini bepul yuklab oling! 🚀')}"
        kb = inline_kb([[button("📋 Havolani Nusxalash / Ulashish", url=share_url)]])
        send_message(chat_id, msg, kb)
        return

    # Installation Guide
    if text == B_GUIDE or text == "/guide":
        guide_msg = (
            f"📖 <b>MINECRAFT MODLARINI O'RNATISH QO'LLANMASI</b>\n\n"
            f"📱 <b>Android uchun:</b>\n"
            f"1. Mod faylini (<code>.mcaddon</code> / <code>.mcpack</code>) yuklab oling.\n"
            f"2. ZArchiver ilovasidan faylni bosing ➔ <i>'Minecraft bilan ochish'</i> ni tanlang.\n"
            f"3. O'yin avtomatik ochiladi va mod o'rnatiladi.\n"
            f"<i>💡 Fayl <code>.zip</code> bo'lsa, nomidan <code>.zip</code> ni o'chirib <code>.mcaddon</code> qiling!</i>\n\n"
            f"🍎 <b>iOS (iPhone) uchun:</b>\n"
            f"1. Fayllar (Files) ilovasidan faylni uzoq bosib <i>'Uzatish' (Share)</i> bosing.\n"
            f"2. Minecraft ilovasini tanlang.\n\n"
            f"💻 <b>Kompyuter (PC) uchun:</b>\n"
            f"1. Fayl ustiga 2 marta bosing (Double Click) — Minecraft avtomatik o'rnatadi."
        )
        kb = inline_kb([[button("🌐 Web Saytda Ko'rish", web_app=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'botz-7vrj.onrender.com')}/")]])
        send_message(chat_id, guide_msg, kb)
        return

    if text == "/upload" or text == B_UPLOAD:
        if not is_admin(user_id):
            send_message(chat_id, "❌ Faqat admin kontent yuklashi mumkin!")
            return
        set_state(user_id, "upload_photo", {"files": []})
        msg = "📬 <b>Kontent yuborish</b>\n\n<b>1-qadam: Eskiz (ko'rinadigan) rasmni yuboring.</b>"
        send_message(chat_id, msg, cancel_keyboard())
        return

    if text == "/help" or text == B_HELP:
        set_state(user_id, "help")
        send_message(chat_id, "📩 <b>Adminga xabaringizni yozib yuboring:</b>\n\nBekor qilish uchun tugmani bosing:", cancel_keyboard())
        return

    if text == "/mods" or text == B_MODS:
        mods = data.get("mods", {})
        if not mods:
            send_message(chat_id, "📭 Hozircha modlar yo'q.")
            return
        t = "📦 <b>Mavjud Modlar:</b>\n\n"
        rows = []
        for m_id, mod in mods.items():
            t += f"🔹 <b>{escape(mod.get('name', ''))}</b>\n"
            rows.append([button(f"⬇️ {mod.get('name', '')}", url=f"https://t.me/{BOT_USERNAME}?start={m_id}")])
        send_message(chat_id, t, inline_kb(rows))
        return

    if text == "/admin" or text == B_ADMIN:
        if not is_admin(user_id):
            send_message(chat_id, "❌ Sizda admin huquqi yo'q!")
            return
        set_state(user_id, "admin_add")
        send_message(chat_id, "👤 <b>Yangi admin ID sini yuboring:</b>", cancel_keyboard())
        return

    if text == "/panel" or text == B_PANEL:
        if not is_admin(user_id):
            send_message(chat_id, "❌ Sizda admin huquqi yo'q!")
            return
        show_admin_panel(chat_id)
        return

    if text == "/broadcast":
        if not is_admin(user_id):
            send_message(chat_id, "❌ Faqat admin xabar tarqatishi mumkin!")
            return
        set_state(user_id, "broadcast")
        send_message(chat_id, "📢 <b>Barcha foydalanuvchilarga tarqatiladigan xabarni yuboring:</b>", cancel_keyboard())
        return

    if text == "/stats":
        if not is_admin(user_id):
            send_message(chat_id, "❌ Sizda admin huquqi yo'q!")
            return
        show_stats(chat_id)
        return

    if text == "/channels":
        if not is_admin(user_id):
            send_message(chat_id, "❌ Sizda admin huquqi yo'q!")
            return
        show_channels(chat_id)
        return

    # State Steps
    if cur == "help":
        clear_state(user_id)
        for admin_id in data.get("admins", []):
            user_link = f'<a href="tg://user?id={user_id}"><b>{escape(user_name)}</b></a>'
            msg = (
                f"📩 <b>Yangi Yordam Xabari (Bot dan)!</b>\n\n"
                f"👤 <b>Foydalanuvchi:</b> {user_link} (ID: <code>{user_id}</code>)\n"
                f"💬 <b>Xabar:</b> {escape(text)}\n"
                f"📅 <b>Vaqt:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"💡 <i>Ushbu xabarga Telegram'da 'Reply' (Javob berish) qilib javob yozsangiz, javobingiz avtomatik foydalanuvchiga boradi!</i>"
            )
            kb = inline_kb([[button(f"👤 {user_name} profiliga o'tish", url=f"tg://user?id={user_id}")]])
            res_msg = send_message(admin_id, msg, kb)
            try:
                if res_msg.get("ok"):
                    register_reply(res_msg["result"]["message_id"], chat_id, user_id, user_name)
            except Exception:
                pass
        send_message(chat_id, "✅ Xabaringiz adminga yuborildi! Rahmat.", main_keyboard(is_admin(user_id)))
        return

    if cur == "admin_add":
        clear_state(user_id)
        if text.isdigit():
            new_id = int(text)
            if new_id not in data["admins"]:
                data["admins"].append(new_id)
                save_data()
                send_message(chat_id, f"✅ Yangi admin qo'shildi: <code>{new_id}</code>", main_keyboard(True))
            else:
                send_message(chat_id, "ℹ️ Bu admin allaqachon mavjud.")
        else:
            send_message(chat_id, "❌ Noto'g'ri ID format. Faqat raqam yuboring.")
        return

    if cur == "channel_add":
        clear_state(user_id)
        ch = text.strip()
        if not ch.startswith("@") and not ch.startswith("-"):
            send_message(chat_id, "❌ Noto'g'ri! Kanal @username yoki ID ko'rinishida bo'lsin.")
            return
        if ch not in data.get("channels", []):
            data.setdefault("channels", []).append(ch)
            save_data()
            send_message(chat_id, f"✅ Yangi kanal obuna ro'yxatiga qo'shildi: <b>{ch}</b>", main_keyboard(True))
        else:
            send_message(chat_id, "ℹ️ Bu kanal allaqachon mavjud.")
        return

    if cur == "broadcast":
        clear_state(user_id)
        users = list(data.get("users", {}).keys())
        send_message(chat_id, f"⏳ <b>{len(users)} kishiga xabar yuborilmoqda...</b>")
        success = 0
        failed = 0
        for uid in users:
            try:
                res = send_message(int(uid), f"📢 <b>XABAR:</b>\n\n{text}")
                if res.get("ok"):
                    success += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            time.sleep(0.05)
        send_message(chat_id, f"✅ Xabar tarqatish yakunlandi!\n\n🟢 Yetib bordi: <b>{success} ta</b>\n🔴 Yetib bormadi: <b>{failed} ta</b>", main_keyboard(True))
        return

    if cur == "upload_title":
        sd["name"] = text.strip()
        set_state(user_id, "upload_category", sd)
        send_message(chat_id, f"✅ Sarlavha qabul qilindi: <b>{escape(sd['name'])}</b>\n\n<b>Endi kategoriyani tanlang:</b>", category_keyboard())
        return

    if cur == "upload_desc":
        desc = "" if text == "/skip" else text.strip()
        sd["description"] = desc
        set_state(user_id, "upload_files", sd)
        
        msg = (
            "<b>4-qadam: Yuklab olinadigan fayllarni yuboring.</b>\n\n"
            "Masalan: .zip, .mcpack, .mcaddon, .apk va h.k.\n"
            "RP + BP kabi bir nechta fayl yuborishingiz mumkin. Hammasini yuborgach, 'Fayllar tayyor' tugmasini bosing.\n\n"
            "📦 Fayl kutilyapti... Birinchi faylni yuboring."
        )
        send_message(chat_id, msg, cancel_keyboard())
        return

    if cur == "upload_files" and (text == B_FILES_DONE or text == B_FILE_ADD):
        if not sd.get("files"):
            send_message(chat_id, "⚠️ Hali hech qanday fayl yubormadingiz! Kamida 1 ta fayl yuboring.")
            return
        finish_upload(chat_id, sd)
        return

    # ===== MOD TAHRIRLASH STATE HANDLERLARI =====
    if cur == "mod_edit_name":
        m_id = sd.get("mod_id", "")
        if m_id in data.get("mods", {}):
            old_name = data["mods"][m_id].get("name", "")
            data["mods"][m_id]["name"] = text.strip()
            save_data()
            clear_state(user_id)
            send_message(chat_id,
                f"✅ <b>Mod nomi o'zgartirildi!</b>\n\n"
                f"🔴 Eski nom: <s>{escape(old_name)}</s>\n"
                f"🟢 Yangi nom: <b>{escape(text.strip())}</b>",
                main_keyboard(True))
        else:
            send_message(chat_id, "❌ Mod topilmadi!", main_keyboard(True))
            clear_state(user_id)
        return

    if cur == "mod_edit_desc":
        m_id = sd.get("mod_id", "")
        if m_id in data.get("mods", {}):
            data["mods"][m_id]["description"] = text.strip()
            save_data()
            clear_state(user_id)
            send_message(chat_id,
                f"✅ <b>Mod tavsifi yangilandi!</b>\n\n"
                f"📝 Yangi tavsif: <i>{escape(text.strip())}</i>",
                main_keyboard(True))
        else:
            send_message(chat_id, "❌ Mod topilmadi!", main_keyboard(True))
            clear_state(user_id)
        return

    send_message(chat_id, "🤖 Tushunmadim. Bosh sahifa uchun /start bosing.")

def handle_photo(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    
    state_info = get_state(user_id)
    cur = state_info.get("state", "")
    sd = state_info.get("data", {})

    if cur == "upload_photo":
        photos = message.get("photo", [])
        if not photos:
            return
        largest = photos[-1]
        file_id = largest["file_id"]
        
        cover_path = os.path.join(MODS_DIR, f"cover_{int(time.time())}.jpg")
        download_file(file_id, cover_path)
        
        sd["cover_id"] = file_id
        sd["cover_file"] = cover_path
        
        set_state(user_id, "upload_title", sd)
        send_message(chat_id, "<b>2-qadam: Sarlavha (nomi) ni yozing.</b>", cancel_keyboard())

def handle_document(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    doc = message.get("document", {})

    if is_admin(user_id) and doc.get("file_name", "").endswith(".json"):
        file_id = doc.get("file_id")
        if download_file(file_id, DATA_FILE):
            global data
            data = load_data()
            mods_cnt = len(data.get("mods", {}))
            send_message(chat_id, f"✅ <b>Zaxira (data.json) muvaffaqiyatli tiklandi!</b>\n📦 Bazadagi modlar soni: <b>{mods_cnt} ta</b>", main_keyboard(True))
            return

    state_info = get_state(user_id)
    cur = state_info.get("state", "")
    sd = state_info.get("data", {})

    if cur == "upload_files":
        file_id = doc.get("file_id")
        file_name = doc.get("file_name", "mod_file")
        
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', file_name)
        fp = os.path.join(MODS_DIR, f"{int(time.time())}_{safe_name}")
        download_file(file_id, fp)
        
        files_list = sd.get("files", [])
        files_list.append({"file_id": file_id, "file_name": file_name, "file_path": fp})
        sd["files"] = files_list
        set_state(user_id, "upload_files", sd)

        msg = (
            f"✅ <b>Fayl qo'shildi ({len(files_list)} ta): {escape(file_name)}</b>\n\n"
            "Yana fayl yuborishingiz yoki yakunlash uchun quyidagi tugmani bosishingiz mumkin."
        )
        send_message(chat_id, msg, file_upload_keyboard())

def finish_upload(chat_id, sd):
    user_id = chat_id
    clear_state(user_id)

    mod_id = f"mod_{int(time.time())}"
    mod_data = {
        "id": mod_id,
        "name": sd.get("name", "Nomsiz"),
        "description": sd.get("description", ""),
        "category": sd.get("category", "minecraft"),
        "cover_id": sd.get("cover_id", ""),
        "cover_file": sd.get("cover_file", ""),
        "files": sd.get("files", []),
        "uploader": user_id,
        "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        "downloads": 0
    }
    
    data.setdefault("mods", {})[mod_id] = mod_data
    save_data(backup=True)

    info = (
        f"<b>{escape(mod_data['name'])}</b>\n\n"
        f"🧬 {escape(mod_data['description'])}\n\n"
        f"📱 Kanal: @{CHANNEL_USERNAME}"
    )
    kb = inline_kb([[button("📬 Kanalga joylash", callback_data=f"publish_{mod_id}")]])
    
    if mod_data.get("cover_file") and os.path.exists(mod_data["cover_file"]):
        send_photo(chat_id, mod_data["cover_file"], info, kb)
    elif mod_data.get("cover_id"):
        send_photo(chat_id, mod_data["cover_id"], info, kb)
    else:
        send_message(chat_id, info, kb)

def handle_callback(cq):
    callback_id = cq["id"]
    user_id = cq["from"]["id"]
    data_cb = cq.get("data", "")
    msg = cq.get("message", {})
    chat_id = msg.get("chat", {}).get("id", user_id)
    message_id = msg.get("message_id")

    if data_cb.startswith("cat_select_"):
        cat_id = data_cb.replace("cat_select_", "", 1)
        state_info = get_state(user_id)
        if state_info.get("state") == "upload_category":
            sd = state_info.get("data", {})
            sd["category"] = cat_id
            set_state(user_id, "upload_desc", sd)
            answer_callback(callback_id)
            send_message(chat_id, "<b>3-qadam: Tavsif yozing (yoki /skip).</b>", cancel_keyboard())
            return

    if data_cb.startswith("publish_"):
        mod_id = data_cb.replace("publish_", "", 1)
        if mod_id in data.get("mods", {}):
            mod = data["mods"][mod_id]
            link = f"https://t.me/{BOT_USERNAME}?start={mod_id}"
            
            caption = (
                f"<b>{escape(mod.get('name', ''))}</b>\n\n"
                f"🧬 {escape(mod.get('description', ''))}\n\n"
                f"📱 Kanal : @{CHANNEL_USERNAME}"
            )
            kb = inline_kb([[button("⬇️ Yuklab olish", url=link)]])
            
            if mod.get("cover_file") and os.path.exists(mod["cover_file"]):
                send_photo(CHANNEL_ID, mod["cover_file"], caption, kb)
            elif mod.get("cover_id"):
                send_photo(CHANNEL_ID, mod["cover_id"], caption, kb)
            else:
                send_message(CHANNEL_ID, caption, kb)

            answer_callback(callback_id, "✅ Kanalga joylandi!")
            send_message(chat_id, "✅ Mod muvaffaqiyatli kanalga joylandi! 🎉", main_keyboard(is_admin(user_id)))
            return

    if data_cb == "check_subscription":
        missing = check_channels(user_id)
        if not missing:
            answer_callback(callback_id, "✅ Obuna tasdiqlandi!")
            user_name = cq["from"].get("first_name", "Foydalanuvchi")
            state_info = get_state(user_id)
            pending_param = None
            if state_info.get("state") == "pending_start":
                pending_param = state_info.get("data", {}).get("param")
            clear_state(user_id)
            handled = False
            if pending_param:
                handled = process_start_payload(chat_id, user_id, user_name, pending_param)
            if not handled:
                send_message(chat_id, "✅ Obuna tasdiqlandi. Rahmat!")
                send_welcome(chat_id, user_id, user_name)
        else:
            answer_callback(callback_id, "❌ Hali barcha kanallarga obuna bo'lmadingiz!", alert=True)
        return

    # Panel Callback Handlers
    if data_cb == "panel_admin_add":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        set_state(user_id, "admin_add")
        send_message(chat_id, "👤 <b>Yangi admin ID sini yuboring:</b>", cancel_keyboard())
        answer_callback(callback_id)
        return

    if data_cb == "panel_admin_del":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        rows = []
        for aid in data.get("admins", []):
            rows.append([button(f"🗑️ ID: {aid}", callback_data=f"admin_del_{aid}")])
        rows.append([button("🔙 Panelga qaytish", callback_data="panel_back")])
        t = "👥 <b>Adminlar ro'yxati:</b>\nOlib tashlash uchun ustiga bosing:"
        edit_message(chat_id, message_id, t, inline_kb(rows))
        answer_callback(callback_id)
        return

    if data_cb.startswith("admin_del_"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        aid = int(data_cb.replace("admin_del_", "", 1))
        if aid in ADMIN_IDS:
            answer_callback(callback_id, "⚠️ Asosiy adminni o'chirib bo'lmaydi!", alert=True)
            return
        if aid in data.get("admins", []):
            data["admins"].remove(aid)
            save_data()
            answer_callback(callback_id, f"✅ Admin olib tashlandi: {aid}")
        else:
            answer_callback(callback_id, "ℹ️ Admin topilmadi.", alert=True)
        rows = []
        for a in data.get("admins", []):
            rows.append([button(f"🗑️ ID: {a}", callback_data=f"admin_del_{a}")])
        rows.append([button("🔙 Panelga qaytish", callback_data="panel_back")])
        t = "👥 <b>Adminlar ro'yxati:</b>\nOlib tashlash uchun ustiga bosing:"
        edit_message(chat_id, message_id, t, inline_kb(rows))
        return

    if data_cb == "panel_mod_add":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        set_state(user_id, "upload_photo", {"files": []})
        msg = "📬 <b>Kontent yuborish</b>\n\n<b>1-qadam: Eskiz (ko'rinadigan) rasmni yuboring.</b>"
        send_message(chat_id, msg, cancel_keyboard())
        answer_callback(callback_id)
        return

    if data_cb == "panel_mod_del":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        mods = data.get("mods", {})
        if not mods:
            answer_callback(callback_id, "📭 Modlar yo'q!", alert=True)
            return
        rows = []
        for m_id, mod in list(mods.items())[-10:]:
            rows.append([button(f"🗑️ {mod.get('name', '')}", callback_data=f"mod_del_{m_id}")])
        rows.append([button("🔙 Panelga qaytish", callback_data="panel_back")])
        t = "📦 <b>Modlar ro'yxati:</b>\nO'chirish uchun ustiga bosing:"
        edit_message(chat_id, message_id, t, inline_kb(rows))
        answer_callback(callback_id)
        return

    if data_cb == "panel_mod_edit":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        mods = data.get("mods", {})
        if not mods:
            answer_callback(callback_id, "📭 Modlar yo'q!", alert=True)
            return
        rows = []
        for m_id, mod in list(mods.items())[-15:]:
            cat = mod.get('category', '')
            rows.append([button(f"✏️ {mod.get('name', 'Nomsiz')} [{cat}]", callback_data=f"mod_edit_sel_{m_id}")])
        rows.append([button("🔙 Panelga qaytish", callback_data="panel_back")])
        t = "✏️ <b>Qaysi modni tahrirlash?</b>\n\nMod tanlang:"
        edit_message(chat_id, message_id, t, inline_kb(rows))
        answer_callback(callback_id)
        return

    if data_cb.startswith("mod_edit_sel_"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        m_id = data_cb.replace("mod_edit_sel_", "", 1)
        mod = data.get("mods", {}).get(m_id)
        if not mod:
            answer_callback(callback_id, "❌ Mod topilmadi!", alert=True)
            return
        cat_name = next((c["icon"]+" "+c["name"] for c in CATEGORIES if c["id"] == mod.get("category","")), mod.get("category","?"))
        t = (
            f"✏️ <b>Tahrirlash: {escape(mod.get('name',''))}</b>\n\n"
            f"📝 Nomi: <b>{escape(mod.get('name',''))}</b>\n"
            f"💬 Tavsifi: <i>{escape(mod.get('description','')[:80])}{'...' if len(mod.get('description',''))>80 else ''}</i>\n"
            f"📂 Kategoriya: <b>{cat_name}</b>\n\n"
            f"Nimani o'zgartirmoqchisiz?"
        )
        rows = [
            [button("📝 Nomini o'zgartirish", callback_data=f"mod_edit_name_{m_id}")],
            [button("💬 Tavsifini o'zgartirish", callback_data=f"mod_edit_desc_{m_id}")],
            [button("📂 Kategoriyani o'zgartirish", callback_data=f"mod_edit_cat_{m_id}")],
            [button("🔙 Orqaga", callback_data="panel_mod_edit")]
        ]
        edit_message(chat_id, message_id, t, inline_kb(rows))
        answer_callback(callback_id)
        return

    if data_cb.startswith("mod_edit_name_"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        m_id = data_cb.replace("mod_edit_name_", "", 1)
        set_state(user_id, "mod_edit_name", {"mod_id": m_id})
        send_message(chat_id, f"📝 <b>Yangi nomni yozing:</b>\n\n(Hozirgi: <i>{escape(data['mods'].get(m_id,{}).get('name',''))}</i>)", cancel_keyboard())
        answer_callback(callback_id)
        return

    if data_cb.startswith("mod_edit_desc_"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        m_id = data_cb.replace("mod_edit_desc_", "", 1)
        set_state(user_id, "mod_edit_desc", {"mod_id": m_id})
        send_message(chat_id, f"💬 <b>Yangi tavsifni yozing:</b>\n\n(Hozirgi: <i>{escape(data['mods'].get(m_id,{}).get('description','')[:100])}</i>)", cancel_keyboard())
        answer_callback(callback_id)
        return

    if data_cb.startswith("mod_edit_cat_"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        m_id = data_cb.replace("mod_edit_cat_", "", 1)
        mod = data.get("mods", {}).get(m_id, {})
        cat_items = [c for c in CATEGORIES if c["id"] not in ("all", "favorites")]
        rows = []
        for i in range(0, len(cat_items), 2):
            row = [button(
                cat_items[i]["icon"]+" "+cat_items[i]["name"]+(
                    " ✅" if mod.get("category") == cat_items[i]["id"] else ""
                ),
                callback_data=f"mod_set_cat_{m_id}_{cat_items[i]['id']}"
            )]
            if i+1 < len(cat_items):
                row.append(button(
                    cat_items[i+1]["icon"]+" "+cat_items[i+1]["name"]+(
                        " ✅" if mod.get("category") == cat_items[i+1]["id"] else ""
                    ),
                    callback_data=f"mod_set_cat_{m_id}_{cat_items[i+1]['id']}"
                ))
            rows.append(row)
        rows.append([button("🔙 Orqaga", callback_data=f"mod_edit_sel_{m_id}")])
        t = f"📂 <b>Kategoriya tanlang:</b>\n(Hozirgi: <b>{mod.get('category','?')}</b>)"
        edit_message(chat_id, message_id, t, inline_kb(rows))
        answer_callback(callback_id)
        return

    if data_cb.startswith("mod_set_cat_"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        parts = data_cb.replace("mod_set_cat_", "", 1).split("_", 1)
        if len(parts) == 2:
            m_id, new_cat = parts[0], parts[1]
            # m_id might contain underscore itself (mod_TIMESTAMP), reconstruct properly
            # format: mod_set_cat_{mod_id}_{cat_id} where mod_id=mod_XXXX and cat_id has no underscore
            # Actually split from right since category IDs have no underscore
            raw = data_cb.replace("mod_set_cat_", "", 1)
            # Find last underscore that separates cat_id
            last_us = raw.rfind("_")
            m_id = raw[:last_us]
            new_cat = raw[last_us+1:]
            if m_id in data.get("mods", {}):
                old_cat = data["mods"][m_id].get("category", "")
                data["mods"][m_id]["category"] = new_cat
                save_data()
                cat_name = next((c["icon"]+" "+c["name"] for c in CATEGORIES if c["id"] == new_cat), new_cat)
                answer_callback(callback_id, f"✅ Kategoriya o'zgartirildi: {cat_name}", alert=True)
                # Show updated edit menu
                mod = data["mods"][m_id]
                cat_disp = next((c["icon"]+" "+c["name"] for c in CATEGORIES if c["id"]==mod.get("category","")), mod.get("category","?"))
                t = (
                    f"✅ <b>Kategoriya o'zgartirildi!</b>\n\n"
                    f"📝 Nomi: <b>{escape(mod.get('name',''))}</b>\n"
                    f"📂 Yangi kategoriya: <b>{cat_disp}</b>\n\n"
                    f"Nimani o'zgartirmoqchisiz?"
                )
                rows2 = [
                    [button("📝 Nomini o'zgartirish", callback_data=f"mod_edit_name_{m_id}")],
                    [button("💬 Tavsifini o'zgartirish", callback_data=f"mod_edit_desc_{m_id}")],
                    [button("📂 Kategoriyani o'zgartirish", callback_data=f"mod_edit_cat_{m_id}")],
                    [button("🔙 Orqaga", callback_data="panel_mod_edit")]
                ]
                edit_message(chat_id, message_id, t, inline_kb(rows2))
            else:
                answer_callback(callback_id, "❌ Mod topilmadi!", alert=True)
        return

    if data_cb.startswith("mod_del_"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        m_id = data_cb.replace("mod_del_", "", 1)
        mods = data.get("mods", {})
        if m_id in mods:
            mod_item = mods[m_id]
            for f in mod_item.get("files", []):
                fp = f.get("file_path", "")
                if fp and os.path.exists(fp):
                    try: os.remove(fp)
                    except Exception: pass
            if mod_item.get("cover_file") and os.path.exists(mod_item["cover_file"]):
                try: os.remove(mod_item["cover_file"])
                except Exception: pass
            name = mod_item.get("name", "")
            del mods[m_id]
            save_data()
            answer_callback(callback_id, f"🗑️ Mod o'chirildi: {name}")
        else:
            answer_callback(callback_id, "ℹ️ Mod topilmadi.", alert=True)
        rows = []
        for m2, mod2 in list(mods.items())[-10:]:
            rows.append([button(f"🗑️ {mod2.get('name', '')}", callback_data=f"mod_del_{m2}")])
        rows.append([button("🔙 Panelga qaytish", callback_data="panel_back")])
        t = "📦 <b>Modlar ro'yxati:</b>\nO'chirish uchun ustiga bosing:" if mods else "📭 Modlar yo'q."
        edit_message(chat_id, message_id, t, inline_kb(rows))
        return

    if data_cb == "panel_channels":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        show_channels(chat_id, message_id)
        answer_callback(callback_id)
        return

    if data_cb == "channel_add_btn":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        set_state(user_id, "channel_add")
        send_message(chat_id, "📢 <b>Kanal username (@bilan) yuboring:</b>", cancel_keyboard())
        answer_callback(callback_id)
        return

    if data_cb.startswith("chdel_"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        ch = data_cb.replace("chdel_", "", 1)
        if ch in data.get("channels", []):
            data["channels"].remove(ch)
            save_data()
            answer_callback(callback_id, f"🗑️ Kanal olib tashlandi: {ch}")
        else:
            answer_callback(callback_id, "ℹ️ Kanal topilmadi.", alert=True)
        show_channels(chat_id, message_id)
        return

    if data_cb == "panel_broadcast":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        set_state(user_id, "broadcast")
        send_message(chat_id, "📢 <b>Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yozing:</b>", cancel_keyboard())
        answer_callback(callback_id)
        return

    if data_cb == "panel_backup":
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        auto_backup_async()
        answer_callback(callback_id, "💾 Zaxira Telegramingizga yuborildi!", alert=True)
        return

    if data_cb in ("panel_back", "panel_refresh"):
        if not is_admin(user_id):
            answer_callback(callback_id, "❌ Faqat admin!", alert=True)
            return
        show_admin_panel(chat_id, message_id)
        answer_callback(callback_id)
        return

    if data_cb == "panel_close":
        if is_admin(user_id):
            edit_message(chat_id, message_id, "🛠️ Admin Panel yopildi.")
        answer_callback(callback_id)
        return

# ================= MAIN TELEGRAM BOT LOOP =================
def run_bot():
    print("Bot polling boshlandi...")
    offset = 0
    while True:
        try:
            res = api_request("getUpdates", {"offset": offset, "timeout": 30})
            if res.get("ok"):
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        m = update["message"]
                        if "photo" in m:
                            handle_photo(m)
                        elif "document" in m:
                            handle_document(m)
                        elif "text" in m:
                            handle_message(m)
                    elif "callback_query" in update:
                        handle_callback(update["callback_query"])
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    run_bot()
