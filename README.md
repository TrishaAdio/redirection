# Telethon Link-Monitor Userbot

A personal (userbot) Telegram account automation built on
[Telethon](https://docs.telethon.dev). You keep a pool of links in your own
**Saved Messages** (one link per line). In any chat you run `.monitor`, and
every 15 minutes the bot "clicks" the active link. When a link expires it is
marked used and the next link from your Saved Messages is promoted
automatically.

> ⚠️ This logs in as **your own account** (a userbot), not a Bot API bot.
> Automating a user account can violate Telegram's Terms of Service — use a
> throwaway/secondary account and reasonable intervals at your own risk.

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
./.venv/bin/python userbot.py          # Linux / macOS
.venv\Scripts\python userbot.py        # Windows
```

## How to use

1. Open **Saved Messages** and send your links, one per line, e.g.:
   ```
   https://example.com/ref/aaa
   https://example.com/ref/bbb
   https://example.com/ref/ccc
   https://example.com/ref/ddd
   ```
   Multiple messages are fine — every link found is added to the pool.
2. In any chat/channel, send `.monitor` **from your own account**.
3. The bot clicks the active link now and every 15 minutes after. Status
   updates are posted in the chat where you ran `.monitor`.

## Commands

Send these yourself, from the account running the userbot:

| Command         | What it does                                            |
|-----------------|---------------------------------------------------------|
| `.monitor`      | start the 15-min click loop in the current chat         |
| `.stopmonitor`  | stop the loop                                           |
| `.links`        | show the pool with `active` / `used` / `queued` tags    |
| `.clicknow`     | click the active link immediately                       |
| `.ping`         | health check                                            |

## What "clicking" and "expired" mean

- **Click** = an HTTP `GET` of the link (following redirects) with a
  browser-like user agent, so it counts as a real visit.
- A link is treated as **expired** when the request fails, returns HTTP
  `>= 400`, or the page body contains any expiry keyword
  (`expired`, `not found`, `invalid`, `no longer`, `404` by default).

## Configuration (`config.json`)

Created by `setup.py`; edit any time:

| Key                | Meaning                                             |
|--------------------|-----------------------------------------------------|
| `interval_minutes` | click interval (default `15`)                       |
| `command_prefix`   | command trigger prefix (default `.`)                |
| `link_source`      | where links are read from (`me` = Saved Messages)   |
| `expiry_keywords`  | words in a page body that mean "expired"            |
| `user_agent`       | UA sent when clicking                               |

Runtime state (used links, active link, monitor chat) is kept in
`state.json` so monitoring resumes after a restart.

## Files

```
setup.py          bootstrap: venv + deps + login
login.py          interactive credential prompt + Telegram sign-in
userbot.py        the userbot: commands + monitor loop
config.py         config/state load & save helpers
requirements.txt  telethon, aiohttp
```
