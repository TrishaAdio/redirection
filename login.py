"""Interactive Telegram login. Run inside the venv (setup.py does this for you).

Collects API credentials, saves them to config.json, then signs in and
creates the Telethon session file so the userbot can start non-interactively.
"""

import asyncio
import getpass

from telethon import TelegramClient

import config


def prompt_credentials():
    cfg = config.load_config()
    print("=== Telegram credentials ===")
    print("Get api_id / api_hash at https://my.telegram.org -> API development tools\n")

    api_id = input("api_id [%s]: " % (cfg["api_id"] or "")).strip()
    api_hash = input("api_hash [%s]: " % (cfg["api_hash"] or "")).strip()
    phone = input("phone (e.g. +15551234567) [%s]: " % (cfg["phone"] or "")).strip()

    if api_id:
        cfg["api_id"] = int(api_id)
    if api_hash:
        cfg["api_hash"] = api_hash
    if phone:
        cfg["phone"] = phone

    interval = input("click interval in minutes [%s]: " % cfg["interval_minutes"]).strip()
    if interval:
        cfg["interval_minutes"] = int(interval)

    if not cfg["api_id"] or not cfg["api_hash"]:
        raise SystemExit("api_id and api_hash are required.")

    config.save_config(cfg)
    return cfg


async def do_login(cfg):
    client = TelegramClient(cfg["session"], int(cfg["api_id"]), cfg["api_hash"])
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print("\nAlready logged in as %s (id %s)." % (me.first_name, me.id))
        await client.disconnect()
        return

    await client.send_code_request(cfg["phone"])
    code = input("Login code (sent via Telegram): ").strip()
    try:
        await client.sign_in(cfg["phone"], code)
    except Exception as exc:  # 2FA password needed
        if "password" in str(exc).lower() or exc.__class__.__name__ == "SessionPasswordNeededError":
            pw = getpass.getpass("Two-step verification password: ")
            await client.sign_in(password=pw)
        else:
            raise

    me = await client.get_me()
    print("\nLogged in as %s (id %s). Session saved as %s.session" % (
        me.first_name, me.id, cfg["session"]))
    await client.disconnect()


def main():
    cfg = prompt_credentials()
    asyncio.run(do_login(cfg))


if __name__ == "__main__":
    main()
