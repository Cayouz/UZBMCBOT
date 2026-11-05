import threading
import time

import config
import storage
import web


def main():
    print("=== MODHUB ishga tushmoqda ===")
    print("Ma'lumotlar: %s" % config.DATA_FILE)
    print("Modlar: %d ta | Foydalanuvchilar: %d ta" % (
        len(storage.data.get("mods", {})), len(storage.data.get("users", {}))))

    web.run_server(block=False)

    if config.DISABLE_BOT:
        print("DISABLE_BOT=1 — Telegram polling o'chirilgan (faqat sayt).")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    import bot
    bot.run_bot()


if __name__ == "__main__":
    main()
