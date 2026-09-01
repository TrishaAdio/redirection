# Telethon Invite-Link Monitor Userbot

A personal (userbot) Telegram automation built on
[Telethon](https://docs.telethon.dev). You keep a stack of spare **invite
links** in your own **Saved Messages** (one per line). Your channel has a post
that shows the current invite link (usually repeated over several lines). You
run `.monitor` in that channel; every 15 minutes the bot checks whether the
link is still valid, and the moment it's revoked/expired it **edits the channel
post in place** — swapping in the next fresh link from your Saved Messages and
keeping the same multi-line style. No status messages are posted to the channel.

> ⚠️ This logs in as **your own account** (a userbot), not a Bot API bot.
> Automating a user account can violate Telegram's Terms of Service — use a
> secondary account and reasonable intervals at your own risk.

## Quick start

```bash
python3 setup.py
```

`setup.py` will:
1. create a virtual environment in `./.venv`
2. install `telethon` + `aiohttp`
3. ask for your `api_id`, `api_hash`, and phone number, then log you in
   (a code is sent via Telegram; 2FA password is supported)

Get your `api_id` / `api_hash` at <https://my.telegram.org> → *API development tools*.

Then run the bot:

```bash
python3 userbot.py
```

You can use plain `python3 userbot.py` from the project folder — the script
**automatically re-executes itself inside `.venv`**, so it always uses the same
Telethon that created your session. (Running with a mismatched system Telethon
is what caused the earlier `too many values to unpack` crash.)

## How to use

1. Open **Saved Messages** and send your spare invite links, one per line:
   ```
   https://t.me/+AAAAaaaa1111
   https://t.me/+BBBBbbbb2222
   https://t.me/+CCCCcccc3333
   https://t.me/+DDDDdddd4444
   ```
   Multiple messages are fine — every link found becomes part of the pool.
2. In your channel, make sure there's a post that contains the current invite
   link (repeated on as many lines as you like — that style is preserved).
3. In that channel, send `.monitor` **from your own account**.
4. The bot checks the link now and every 15 minutes. When it expires it edits
   the post to the next valid link from your Saved Messages and marks that one
   used. Nothing else is posted to the channel.

## Commands

Send these yourself, from the account running the userbot:

| Command         | What it does                                                    |
|-----------------|-----------------------------------------------------------------|
| `.monitor`      | watch the invite-link post in the current channel               |
| `.stopmonitor`  | stop watching                                                   |
| `.status`       | show active link + validity + pool counts                       |
| `.links`        | list the Saved-Messages pool (`active` / `used` / `queued`)     |
| `.checknow`     | force an immediate validity check + rotate if needed            |
| `.reset`        | clear used/active state so every spare link is queued again     |
| `.ping`         | health check                                                    |

## Requirement: the account must be an admin of the channel

To edit the channel post, the account running the userbot must be an **admin of
the channel with the right to edit/post messages** (or the channel creator). If
it isn't, `.monitor` will refuse to start and tell you so, and no spare links
are consumed. Add the account as an admin, then run `.monitor` again.

## How validity is checked

- **Telegram invite links** (`t.me/+…`, `t.me/joinchat/…`, `tg://join?invite=…`)
  are validated through Telegram's `CheckChatInvite` API — **not** an HTTP
  request. This is why the earlier version wrongly flagged valid links as
  `404`: an invite link is not a normal web page.
- A link is rotated **only** when Telegram reports it expired/invalid/revoked.
  Transient problems (flood-wait, network hiccups) are treated as "still alive"
  so the bot never rotates by mistake.
- Plain `http(s)` links (if you ever use them) fall back to an HTTP `GET` with
  the configurable `expiry_keywords` check.

## Configuration (`config.json`)

Created by `setup.py`; edit any time:

| Key                | Meaning                                             |
|--------------------|-----------------------------------------------------|
| `interval_minutes` | check interval (default `15`)                       |
| `command_prefix`   | command trigger prefix (default `.`)                |
| `link_source`      | where spare links are read from (`me` = Saved Messages) |
| `expiry_keywords`  | words that mean "expired" for plain http links      |
| `user_agent`       | UA used for http-link fallback                      |

Runtime state (used links, active link, watched channel + post id) is kept in
`state.json`, so monitoring resumes automatically after a restart.

## Files

```
setup.py          bootstrap: venv + deps + login
login.py          interactive credential prompt + Telegram sign-in
userbot.py        the userbot: commands + monitor/rotate loop
config.py         config/state load & save helpers
requirements.txt  telethon, aiohttp
```
