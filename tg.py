import http.client
import json
import mimetypes
import os
import ssl
import time
import urllib.parse
import urllib.request
import uuid

import config

HOST = "api.telegram.org"


def _file_size(f):
    try:
        pos = f.tell()
        f.seek(0, os.SEEK_END)
        size = f.tell() - pos
        f.seek(pos)
        return size
    except Exception:
        return 0


class _StreamBody(object):
    """Multipart tanasini xotirada saqlamasdan bo'laklab yuborish."""

    def __init__(self, parts):
        self.parts = parts
        self.idx = 0
        self.pos = 0

    def read(self, n=-1):
        if n is None or n < 0:
            n = 65536
        out = bytearray()
        while len(out) < n and self.idx < len(self.parts):
            part = self.parts[self.idx]
            if isinstance(part, (bytes, bytearray)):
                take = bytes(part[self.pos:self.pos + (n - len(out))])
                out += take
                self.pos += len(take)
                if self.pos >= len(part):
                    self.idx += 1
                    self.pos = 0
            else:
                chunk = part.read(n - len(out))
                if chunk:
                    out += chunk
                else:
                    self.idx += 1
                    self.pos = 0
        return bytes(out)


def _build_multipart(fields, files):
    boundary = "----ModHub%s" % uuid.uuid4().hex
    parts = []
    for key, value in (fields or {}).items():
        head = ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n'
                % (boundary, key)).encode("utf-8")
        val = value if isinstance(value, bytes) else str(value).encode("utf-8")
        parts.extend([head, val, b"\r\n"])
    for key, value in (files or {}).items():
        if isinstance(value, (tuple, list)):
            filename, fobj = value[0], value[1]
            ctype = value[2] if len(value) > 2 else None
        else:
            fobj = value
            filename = os.path.basename(getattr(fobj, "name", "file"))
            ctype = None
        ctype = ctype or mimetypes.guess_type(str(filename))[0] or "application/octet-stream"
        safe_name = str(filename).replace('"', "'").replace("\r", "").replace("\n", "")
        head = ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: %s\r\n\r\n' % (boundary, key, safe_name, ctype)).encode("utf-8")
        parts.extend([head, fobj, b"\r\n"])
    parts.append(("--%s--\r\n" % boundary).encode("utf-8"))

    length = 0
    for p in parts:
        length += len(p) if isinstance(p, (bytes, bytearray)) else _file_size(p)
    headers = {
        "Content-Type": "multipart/form-data; boundary=%s" % boundary,
        "Content-Length": str(length),
    }
    return _StreamBody(parts), headers


def _do_request(method, params=None, files=None, timeout=60):
    if files:
        for f in files.values():
            fobj = f[1] if isinstance(f, (tuple, list)) else f
            try:
                fobj.seek(0)
            except Exception:
                pass
        body, headers = _build_multipart(params, files)
        path = "/bot%s/%s" % (config.BOT_TOKEN, method)
    else:
        data = urllib.parse.urlencode(params or {}).encode("utf-8")
        body = data
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        path = "/bot%s/%s" % (config.BOT_TOKEN, method)

    conn = http.client.HTTPSConnection(HOST, timeout=timeout, context=ssl.create_default_context())
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        return json.loads(raw.decode("utf-8"))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def api_request(method, params=None, files=None, timeout=60):
    result = {"ok": False}
    for attempt in range(2):
        try:
            result = _do_request(method, params, files, timeout)
        except Exception as e:
            print("API error (%s): %s" % (method, e))
            result = {"ok": False, "error": str(e)}
            if attempt == 0:
                time.sleep(1)
                continue
            return result
        if result.get("error_code") == 429 and attempt == 0:
            retry_after = 1
            try:
                retry_after = int(result.get("parameters", {}).get("retry_after", 1))
            except Exception:
                pass
            if retry_after <= 8:
                time.sleep(retry_after)
                continue
        return result
    return result


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


def reply_kb(rows, resize=True):
    return {"keyboard": rows, "resize_keyboard": resize}


def send_message(chat_id, text, keyboard=None):
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }
    if keyboard is not None:
        params["reply_markup"] = json.dumps(keyboard)
    return api_request("sendMessage", params)


def send_photo(chat_id, photo, caption="", keyboard=None, silent=False):
    params = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if silent:
        params["disable_notification"] = "true"
    if keyboard is not None:
        params["reply_markup"] = json.dumps(keyboard)
    if isinstance(photo, str) and os.path.exists(photo):
        with open(photo, "rb") as f:
            return api_request("sendPhoto", params=params, files={"photo": f})
    params["photo"] = photo
    return api_request("sendPhoto", params=params)


def send_media_group(chat_id, photos, caption="", silent=False):
    """photos: list of dict {file_id, path} yoki list[str] (file_id/path)."""
    items = []
    files = {}
    for p in photos[:10]:
        if isinstance(p, dict):
            path = p.get("path") or ""
            file_id = p.get("file_id") or ""
        else:
            path = p if os.path.exists(str(p)) else ""
            file_id = "" if path else str(p)
        item = {"type": "photo"}
        if path and os.path.exists(path):
            key = "photo%d" % len(items)
            try:
                files[key] = open(path, "rb")
            except Exception:
                if not file_id:
                    continue
            else:
                item["media"] = "attach://" + key
        elif file_id:
            item["media"] = file_id
        else:
            continue
        items.append(item)
    try:
        if not items:
            return {"ok": False}
        if caption:
            items[0]["caption"] = caption
            items[0]["parse_mode"] = "HTML"
        params = {"chat_id": chat_id, "media": json.dumps(items)}
        if silent:
            params["disable_notification"] = "true"
        return api_request("sendMediaGroup", params=params, files=files or None)
    finally:
        for f in files.values():
            try:
                f.close()
            except Exception:
                pass


def edit_photo(chat_id, message_id, photo, caption="", keyboard=None):
    params = {"chat_id": chat_id, "message_id": message_id}
    media = {"type": "photo", "caption": caption, "parse_mode": "HTML"}
    if keyboard is not None:
        params["reply_markup"] = json.dumps(keyboard)
    if isinstance(photo, str) and os.path.isfile(photo):
        media["media"] = "attach://photo"
        params["media"] = json.dumps(media)
        with open(photo, "rb") as file:
            return api_request("editMessageMedia", params, {"photo": file})
    media["media"] = photo
    params["media"] = json.dumps(media)
    return api_request("editMessageMedia", params)


def send_document(chat_id, document, caption="", silent=False):
    params = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if silent:
        params["disable_notification"] = "true"
    if isinstance(document, str) and os.path.exists(document):
        with open(document, "rb") as f:
            return api_request("sendDocument", params=params, files={"document": f})
    params["document"] = document
    return api_request("sendDocument", params=params)


def pin_message(chat_id, message_id):
    return api_request("pinChatMessage", {"chat_id": chat_id, "message_id": message_id,
                                          "disable_notification": "true"})


def unpin_all(chat_id):
    return api_request("unpinAllChatMessages", {"chat_id": chat_id})


def get_chat(chat_id, timeout=20):
    return api_request("getChat", {"chat_id": chat_id}, timeout=timeout)


def get_chat_member(chat_id, user_id):
    return api_request("getChatMember", {"chat_id": chat_id, "user_id": user_id})


def edit_message(chat_id, message_id, text, keyboard=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if keyboard is not None:
        params["reply_markup"] = json.dumps(keyboard)
    return api_request("editMessageText", params)


def answer_callback(cb_id, text=None, alert=False):
    params = {"callback_query_id": cb_id}
    if text is not None:
        params["text"] = text
        params["show_alert"] = "true" if alert else "false"
    return api_request("answerCallbackQuery", params)


def get_file_path(file_id):
    res = api_request("getFile", {"file_id": file_id})
    if not res.get("ok"):
        return None
    return res["result"].get("file_path")


def download_file(file_id, save_path):
    path = get_file_path(file_id)
    if not path:
        return False
    url = "https://api.telegram.org/file/bot%s/%s" % (config.BOT_TOKEN, path)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ModHub/2.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
            with open(save_path, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        return True
    except Exception as e:
        print("Download error:", e)
    return False


def set_chat_menu_button(url):
    """Botning chap pastidagi menyu tugmasini WebApp qilib o'rnatish."""
    if not url:
        return {"ok": False}
    menu = {"type": "web_app", "text": "\U0001f310 Saytni ochish", "web_app": {"url": url}}
    return api_request("setChatMenuButton", {"menu_button": json.dumps(menu)})


def set_my_commands():
    cmds = [
        {"command": "start", "description": "Boshlash / Salomlashish"},
        {"command": "mods", "description": "Modlar bo'limi"},
        {"command": "guide", "description": "O'rnatish qo'llanmasi"},
        {"command": "ref", "description": "Do'stlarni taklif qilish"},
        {"command": "help", "description": "Adminga yozish"},
        {"command": "panel", "description": "Admin panel (adminlar uchun)"},
    ]
    return api_request("setMyCommands", {"commands": json.dumps(cmds)})
