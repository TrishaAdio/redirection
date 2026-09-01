"""Telethon userbot: link monitor.

Workflow
--------
1. From your own account, send 4-5 links (one per line) to Saved Messages.
   Multiple messages are fine; every link found is added to the pool.
2. In any channel/chat, send ``.monitor`` (from your own account).
3. Every ``interval_minutes`` (default 15) the bot "clicks" (HTTP GET) the
   currently active link.
4. When the active link is detected as expired, it is marked used, the next
   unused link from Saved Messages becomes active, and a note is posted in
   the channel where ``.monitor`` was started.

Commands (send them yourself, from the account running the userbot):
    .monitor        start the 15-minute click loop in the current chat
    .stopmonitor    stop the loop
    .links          show the current pool + which links are used/active
    .clicknow       trigger an immediate click of the active link
    .ping           health check
"""

import asyncio
import re
import sys

import aiohttp
from telethon import TelegramClient, events

import config

cfg = config.load_config()
state = config.load_state()

# --- link extraction ---------------------------------------------------------
URL_RE = re.compile(r"(https?://\S+|t\.me/\S+|tg://\S+)", re.IGNORECASE)

# Monitor task handle so it can be started/stopped.
_monitor_task = None
_http_session = None


def prefix(cmd):
    """Build a regex pattern for a command with the configured prefix."""
    return r"^\%s%s$" % (cfg["command_prefix"], cmd)


async def get_http():
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            headers={"User-Agent": cfg["user_agent"]},
            timeout=aiohttp.ClientTimeout(total=30),
        )
    return _http_session


async def fetch_pool(client):
    """Read every link from the link source (Saved Messages), oldest first."""
    found = []
    async for msg in client.iter_messages(cfg["link_source"], limit=300):
        if not msg.message:
            continue
        for match in URL_RE.findall(msg.message):
            found.append(match.strip())
    found.reverse()  # iter_messages is newest-first; we want oldest-first
    # de-duplicate while preserving order
    seen, ordered = set(), []
    for link in found:
        if link not in seen:
            seen.add(link)
            ordered.append(link)
    return ordered


def pick_next(pool):
    """First link in the pool that isn't used and isn't already active."""
    used = set(state.get("used", []))
    active = state.get("active")
    for link in pool:
        if link not in used and link != active:
            return link
    return None


async def click(url):
    """'Click' a link. Returns (alive: bool, detail: str)."""
    session = await get_http()
    try:
        async with session.get(url, allow_redirects=True) as resp:
            body = ""
            ctype = resp.headers.get("Content-Type", "")
            if "text" in ctype or "html" in ctype or not ctype:
                body = (await resp.text(errors="ignore"))[:20000].lower()
            if resp.status >= 400:
                return False, "HTTP %s" % resp.status
            for kw in cfg["expiry_keywords"]:
                if kw.lower() in body:
                    return False, "matched '%s'" % kw
            return True, "HTTP %s" % resp.status
    except asyncio.TimeoutError:
        return False, "timeout"
    except Exception as exc:  # noqa: BLE001 - any network error == treat as dead
        return False, type(exc).__name__


async def report(client, text):
    chat = state.get("monitor_chat")
    if chat is not None:
        try:
            await client.send_message(chat, text, link_preview=False)
        except Exception:  # noqa: BLE001
            pass


async def ensure_active(client):
    """Make sure state has an active link; return it (or None)."""
    pool = await fetch_pool(client)
    active = state.get("active")
    used = set(state.get("used", []))
    if not active or active in used or active not in pool:
        active = pick_next(pool)
        state["active"] = active
        config.save_state(state)
    return active, pool


async def do_cycle(client):
    """One monitor cycle: click active, rotate on expiry. Returns keep_going."""
    active, pool = await ensure_active(client)
    if not active:
        await report(client, "▸ monitor: no unused links left in the pool.")
        return False

    alive, detail = await click(active)
    if alive:
        await report(client, "▸ clicked active link — ok (%s)\n%s" % (detail, active))
        return True

    # expired -> mark used, rotate to next
    used = state.get("used", [])
    if active not in used:
        used.append(active)
    state["used"] = used
    new_link = pick_next(pool)
    state["active"] = new_link
    config.save_state(state)

    if new_link:
        alive2, detail2 = await click(new_link)
        status = "ok" if alive2 else "also dead (%s)" % detail2
        await report(
            client,
            "▸ link expired (%s), marked used:\n%s\n\n▸ switched to next link — %s:\n%s"
            % (detail, active, status, new_link),
        )
        return True

    await report(
        client,
        "▸ link expired (%s), marked used:\n%s\n\n▸ no more unused links in the pool."
        % (detail, active),
    )
    return False


async def monitor_loop(client):
    interval = max(1, int(cfg["interval_minutes"])) * 60
    while True:
        keep_going = await do_cycle(client)
        if not keep_going:
            break
        await asyncio.sleep(interval)
    state["monitor_chat"] = state.get("monitor_chat")
    config.save_state(state)


def register_handlers(client):
    own = dict(outgoing=True, from_users="me")

    @client.on(events.NewMessage(pattern=prefix("monitor"), **own))
    async def _monitor(event):
        global _monitor_task
        state["monitor_chat"] = event.chat_id
        config.save_state(state)
        if _monitor_task and not _monitor_task.done():
            await event.edit("▸ monitor already running in this or another chat.")
            return
        await event.edit(
            "▸ monitor started. clicking every %s min in this chat."
            % cfg["interval_minutes"]
        )
        _monitor_task = asyncio.create_task(monitor_loop(client))

    @client.on(events.NewMessage(pattern=prefix("stopmonitor"), **own))
    async def _stop(event):
        global _monitor_task
        if _monitor_task and not _monitor_task.done():
            _monitor_task.cancel()
            _monitor_task = None
            await event.edit("▸ monitor stopped.")
        else:
            await event.edit("▸ monitor is not running.")

    @client.on(events.NewMessage(pattern=prefix("clicknow"), **own))
    async def _clicknow(event):
        await event.edit("▸ clicking now…")
        await do_cycle(client)

    @client.on(events.NewMessage(pattern=prefix("links"), **own))
    async def _links(event):
        pool = await fetch_pool(client)
        used = set(state.get("used", []))
        active = state.get("active")
        if not pool:
            await event.edit("▸ pool is empty. send links to Saved Messages, one per line.")
            return
        lines = ["▸ link pool (%d):" % len(pool)]
        for i, link in enumerate(pool, 1):
            if link == active:
                tag = "active"
            elif link in used:
                tag = "used"
            else:
                tag = "queued"
            lines.append("%d. [%s] %s" % (i, tag, link))
        await event.edit("\n".join(lines))

    @client.on(events.NewMessage(pattern=prefix("ping"), **own))
    async def _ping(event):
        await event.edit("▸ pong — userbot alive.")


async def main():
    if not config.is_configured():
        print("Not configured yet. Run:  python setup.py")
        sys.exit(1)

    client = TelegramClient(cfg["session"], int(cfg["api_id"]), cfg["api_hash"])
    await client.start(phone=cfg["phone"] or None)
    me = await client.get_me()
    register_handlers(client)
    print("Userbot running as %s (id %s)." % (me.first_name, me.id))
    print("Send '%smonitor' in a chat to begin." % cfg["command_prefix"])

    # Resume monitoring if it was running before a restart.
    if state.get("monitor_chat"):
        global _monitor_task
        _monitor_task = asyncio.create_task(monitor_loop(client))
        print("Resumed monitor in chat %s." % state["monitor_chat"])

    try:
        await client.run_until_disconnected()
    finally:
        if _http_session and not _http_session.closed:
            await _http_session.close()


if __name__ == "__main__":
    asyncio.run(main())
