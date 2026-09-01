"""Telethon userbot: Telegram invite-link monitor.

Workflow
--------
1. From your own account, send your spare invite links (one per line) to your
   Saved Messages. Each line is one fresh link, e.g.:
       https://t.me/+AAAA
       https://t.me/+BBBB
       https://t.me/+CCCC
2. In your channel there is a post that shows the *current* invite link,
   usually repeated on several lines (the "4-5 line" style).
3. In that channel, send ``.monitor`` (from your own account). The bot finds
   the most recent post that contains invite links and starts watching it.
4. Every ``interval_minutes`` (default 15) it validates the link via Telegram
   (``CheckChatInvite`` — NOT an HTTP request). When the link is revoked or
   expired, it takes the next unused link from your Saved Messages, EDITS the
   channel post in place (keeping the same multi-line style), and marks the
   consumed link used. No status spam is posted to the channel.

Commands (send them yourself, from the account running the userbot):
    .monitor        watch the invite-link post in the current channel
    .stopmonitor    stop watching
    .status         show active link + validity + pool counts
    .links          list the Saved-Messages pool (queued / used)
    .checknow       force an immediate validity check + rotate if needed
    .reset          clear used/active state (re-queue every spare link)
    .ping           health check
"""

# --- make sure we run inside the project venv --------------------------------
import os
import sys


def _reexec_in_venv():
    """If a project venv exists and we're not using it, re-exec with it.

    This prevents the classic 'ValueError: too many values to unpack' /
    version-mismatch crash from running `python3 userbot.py` with a different
    system Telethon than the one that created the session.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    if os.name == "nt":
        venv_py = os.path.join(root, ".venv", "Scripts", "python.exe")
    else:
        venv_py = os.path.join(root, ".venv", "bin", "python")
    if not os.path.exists(venv_py):
        return
    try:
        if os.path.samefile(sys.executable, venv_py):
            return
    except OSError:
        pass
    os.execv(venv_py, [venv_py, os.path.abspath(__file__), *sys.argv[1:]])


_reexec_in_venv()

import asyncio
import re

import aiohttp
from telethon import TelegramClient, events
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.errors import (
    FloodWaitError,
    InviteHashEmptyError,
    InviteHashExpiredError,
    InviteHashInvalidError,
)

import config

cfg = config.load_config()
state = config.load_state()

# Any URL (used to locate the pool links and the channel post links).
URL_RE = re.compile(r"(https?://\S+|t\.me/\S+|tg://\S+)", re.IGNORECASE)
# Extract the invite hash from t.me/+HASH, joinchat/HASH, tg://join?invite=HASH.
INVITE_RE = re.compile(r"(?:joinchat/|\+|invite=)([A-Za-z0-9_\-]{5,})")

_monitor_task = None
_http_session = None


def prefix(cmd):
    return r"^\%s%s$" % (cfg["command_prefix"], cmd)


def invite_hash(link):
    m = INVITE_RE.search(link)
    return m.group(1) if m else None


async def get_http():
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            headers={"User-Agent": cfg["user_agent"]},
            timeout=aiohttp.ClientTimeout(total=30),
        )
    return _http_session


# --- validity check ----------------------------------------------------------
async def check_link(client, link):
    """Return (alive: bool, detail: str).

    Telegram invite links are validated through the API. Only a genuine
    expired/invalid/revoked result rotates the link; transient errors
    (flood-wait, network) are treated as 'alive' so we never rotate by mistake.
    Plain http(s) links fall back to an HTTP GET + keyword check.
    """
    h = invite_hash(link)
    if h:
        try:
            await client(CheckChatInviteRequest(h))
            return True, "valid"
        except (InviteHashExpiredError, InviteHashInvalidError, InviteHashEmptyError) as exc:
            return False, type(exc).__name__
        except FloodWaitError as exc:
            return True, "floodwait:%ss" % exc.seconds
        except Exception as exc:  # noqa: BLE001 - don't rotate on unknown errors
            return True, "skip:%s" % type(exc).__name__

    if link.lower().startswith("http"):
        return await http_click(link)
    return True, "unknown-scheme"


async def http_click(url):
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
        return True, "timeout"          # transient -> don't rotate
    except Exception as exc:            # noqa: BLE001
        return True, "skip:%s" % type(exc).__name__


# --- pool from Saved Messages ------------------------------------------------
async def fetch_pool(client):
    """Every link in the link source (Saved Messages), de-duped.

    Order: oldest message first, and within a single message the links are
    kept in reading order (top line first). iter_messages is newest-first, so
    we collect message texts, reverse the message order, then read each
    message's links top-to-bottom.
    """
    texts = []
    async for msg in client.iter_messages(cfg["link_source"], limit=300):
        if msg.message:
            texts.append(msg.message)
    texts.reverse()  # oldest message first
    seen, ordered = set(), []
    for text in texts:
        for match in URL_RE.findall(text):
            link = match.strip()
            if link not in seen:
                seen.add(link)
                ordered.append(link)
    return ordered


def pick_next(pool):
    used = set(state.get("used", []))
    active = state.get("active")
    for link in pool:
        if link not in used and link != active:
            return link
    return None


async def next_valid_link(client, pool):
    """Return the next unused link Telegram confirms is still valid.

    Genuinely-dead spares are marked used as we skip past them, but the valid
    link we return is NOT marked used here — the caller marks it only after it
    has actually been placed into the post, so a failed edit wastes nothing.
    """
    while True:
        cand = pick_next(pool)
        if not cand:
            return None
        alive, _ = await check_link(client, cand)
        if alive:
            return cand
        # genuinely dead spare: mark used so we don't retry it
        used = state.setdefault("used", [])
        if cand not in used:
            used.append(cand)
        config.save_state(state)


# --- the channel post we manage ----------------------------------------------
async def find_link_post(client, chat, exclude_id):
    """Newest message in `chat` (excluding the command) that has invite links."""
    async for msg in client.iter_messages(chat, limit=60):
        if msg.id == exclude_id or not msg.message:
            continue
        if URL_RE.search(msg.message):
            return msg
    return None


async def can_edit_here(client, chat):
    """True/False if we can/can't edit posts in `chat`; None if undetermined."""
    try:
        perms = await client.get_permissions(chat, "me")
        return bool(
            getattr(perms, "is_creator", False)
            or getattr(perms, "edit_messages", False)
            or getattr(perms, "post_messages", False)
        )
    except Exception:  # noqa: BLE001 - private chats etc. are always editable
        return None


async def rotate(client):
    """Check the managed post's link; if dead, edit it to a fresh one.

    Returns (keep_going: bool, note: str).
    """
    chat = state.get("monitor_chat")
    post_id = state.get("post_id")
    if chat is None or post_id is None:
        return False, "no post"

    msg = await client.get_messages(chat, ids=post_id)
    if not msg:
        return False, "post deleted"

    text = msg.message or ""
    links = URL_RE.findall(text)
    if not links:
        return True, "post has no links"

    active = links[0].strip()
    state["active"] = active
    config.save_state(state)

    alive, detail = await check_link(client, active)
    if alive:
        return True, "active valid (%s)" % detail

    # expired -> find a fresh valid spare, then edit the post in place.
    pool = await fetch_pool(client)
    new_link = await next_valid_link(client, pool)
    if not new_link:
        return False, "expired (%s) — no valid spare links left" % detail

    # keep the exact style: replace every occurrence of the dead link.
    new_text = text.replace(active, new_link)
    if new_text == text:  # links differed; swap all links to be safe
        new_text = URL_RE.sub(lambda m: new_link, text)
    try:
        await client.edit_message(chat, post_id, new_text, link_preview=False)
    except Exception as exc:  # noqa: BLE001
        # Most likely the account lacks edit rights on this channel post.
        # Do NOT consume the valid spare, so nothing is wasted.
        print("[rotate] edit failed: %r" % exc)
        return False, ("cannot edit the post (%s) — this account must be an "
                       "admin of the channel with the right to edit/post "
                       "messages." % type(exc).__name__)

    # success: only now mark the dead link and the newly-placed link as used.
    used = state.setdefault("used", [])
    for link in (active, new_link):
        if link not in used:
            used.append(link)
    state["active"] = new_link
    config.save_state(state)
    print("[rotate] %s expired -> swapped to %s" % (active, new_link))
    return True, "swapped -> %s" % new_link


async def monitor_loop(client):
    interval = max(1, int(cfg["interval_minutes"])) * 60
    while True:
        try:
            keep_going, note = await rotate(client)
            print("[monitor] %s" % note)
        except Exception as exc:  # noqa: BLE001 - never let the loop die silently
            print("[monitor] error: %r" % exc)
            keep_going = True
        if not keep_going:
            break
        await asyncio.sleep(interval)


def _pool_counts(pool):
    used = set(state.get("used", []))
    queued = [l for l in pool if l not in used]
    return len(queued), len(used)


def _cmd_from_owner(event):
    """Which messages count as a command from you.

    - Your own outgoing messages (Saved Messages, DMs, groups): ``event.out``.
    - Anonymous broadcast-channel posts: in a broadcast channel your posts are
      attributed to the channel, so ``out`` is False and the sender is the
      channel — but only admins can post there, so any command-shaped post in a
      broadcast channel is treated as yours.
    """
    if event.out:
        return True
    if event.is_channel and not event.is_group:
        return True
    return False


def register_handlers(client):
    own = dict(func=_cmd_from_owner)

    @client.on(events.NewMessage(pattern=prefix("monitor"), **own))
    async def _monitor(event):
        global _monitor_task
        print("[cmd] .monitor in chat %s" % event.chat_id)
        post = await find_link_post(client, event.chat_id, event.id)
        if not post:
            await event.edit("▸ no invite-link post found in this channel.")
            return
        state["monitor_chat"] = event.chat_id
        state["post_id"] = post.id
        config.save_state(state)

        if _monitor_task and not _monitor_task.done():
            _monitor_task.cancel()

        editable = await can_edit_here(client, event.chat_id)
        if editable is False:
            await event.edit(
                "▸ found post #%d, but this account can't edit posts here.\n"
                "▸ make this account an admin of the channel with the "
                "'Edit messages of others' / post right, then run .monitor again."
                % post.id
            )
            return

        keep_going, note = await rotate(client)
        pool = await fetch_pool(client)
        q, u = _pool_counts(pool)
        await event.edit(
            "▸ monitoring post #%d · every %s min · pool: %d queued / %d used · %s"
            % (post.id, cfg["interval_minutes"], q, u, note)
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

    @client.on(events.NewMessage(pattern=prefix("checknow"), **own))
    async def _checknow(event):
        await event.edit("▸ checking…")
        # Full self-contained diagnosis, reported in Telegram (not just stdout).
        chat = state.get("monitor_chat")
        post_id = state.get("post_id")
        editable = await can_edit_here(client, chat) if chat is not None else None
        edit_txt = {True: "yes", False: "NO — not an admin/can't edit", None: "?"}[editable]

        active = None
        detail = "-"
        if chat is not None and post_id is not None:
            msg = await client.get_messages(chat, ids=post_id)
            if msg and msg.message:
                found = URL_RE.findall(msg.message)
                if found:
                    active = found[0].strip()
                    _, detail = await check_link(client, active)

        keep_going, note = await rotate(client)
        await event.edit(
            "▸ watching chat: %s · post #%s\n"
            "▸ active link: %s\n"
            "▸ link check: %s\n"
            "▸ can edit post here: %s\n"
            "▸ result: %s"
            % (chat, post_id, active or "none (run .monitor in the channel first)",
               detail, edit_txt, note)
        )

    @client.on(events.NewMessage(pattern=prefix("status"), **own))
    async def _status(event):
        active = state.get("active")
        pool = await fetch_pool(client)
        q, u = _pool_counts(pool)
        running = _monitor_task and not _monitor_task.done()
        detail = "-"
        if active:
            _, detail = await check_link(client, active)
        await event.edit(
            "▸ monitor: %s\n▸ active: %s (%s)\n▸ pool: %d queued / %d used"
            % ("on" if running else "off", active or "none", detail, q, u)
        )

    @client.on(events.NewMessage(pattern=prefix("links"), **own))
    async def _links(event):
        pool = await fetch_pool(client)
        used = set(state.get("used", []))
        active = state.get("active")
        if not pool:
            await event.edit("▸ pool empty. send invite links to Saved Messages, one per line.")
            return
        lines = ["▸ pool (%d):" % len(pool)]
        for i, link in enumerate(pool, 1):
            tag = "active" if link == active else ("used" if link in used else "queued")
            lines.append("%d. [%s] %s" % (i, tag, link))
        await event.edit("\n".join(lines))

    @client.on(events.NewMessage(pattern=prefix("reset"), **own))
    async def _reset(event):
        state["used"] = []
        state["active"] = None
        config.save_state(state)
        pool = await fetch_pool(client)
        await event.edit("▸ pool reset — %d links now queued." % len(pool))

    @client.on(events.NewMessage(pattern=prefix("ping"), **own))
    async def _ping(event):
        print("[cmd] .ping in chat %s (out=%s, channel=%s)"
              % (event.chat_id, event.out, event.is_channel))
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
    print("Send '%smonitor' in your channel to begin." % cfg["command_prefix"])

    if state.get("monitor_chat") and state.get("post_id"):
        global _monitor_task
        _monitor_task = asyncio.create_task(monitor_loop(client))
        print("Resumed monitor on post #%s." % state["post_id"])

    try:
        await client.run_until_disconnected()
    finally:
        if _http_session and not _http_session.closed:
            await _http_session.close()


if __name__ == "__main__":
    asyncio.run(main())
