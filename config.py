"""Shared configuration helpers for the userbot.

Config is stored as JSON in ``config.json`` next to this file. Both
``login.py`` and ``userbot.py`` read from it. Nothing here imports Telethon
so it is safe to use from ``setup.py`` before dependencies are installed.
"""

import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "state.json")

DEFAULTS = {
    "api_id": 0,
    "api_hash": "",
    "phone": "",
    # Telethon session file name (a "<session>.session" file is created).
    "session": "userbot",
    # Prefix that triggers commands sent from your own account.
    "command_prefix": ".",
    # How often (minutes) the monitor loop clicks the active link.
    "interval_minutes": 15,
    # Where the link pool comes from. "me" == your own Saved Messages.
    "link_source": "me",
    # A link is treated as expired if the HTTP request fails, returns a
    # status >= 400, or if any of these words appear in the response body.
    "expiry_keywords": ["expired", "not found", "invalid", "no longer", "404"],
    # Browser-like UA so "clicking" looks like a real visit.
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


def load_config():
    """Return the saved config merged over defaults."""
    data = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data.update(json.load(fh))
    return data


def save_config(data):
    """Persist config to disk, keeping any unknown keys already present."""
    current = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            current = json.load(fh)
    current.update(data)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2)
    return current


def load_state():
    """Return persisted runtime state (used links / active link)."""
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"used": [], "active": None, "monitor_chat": None}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def is_configured():
    cfg = load_config()
    return bool(cfg["api_id"]) and bool(cfg["api_hash"])
