#!/usr/bin/env python3
"""One-shot setup for the Telethon link-monitor userbot.

Run with your system Python:

    python3 setup.py

It will:
  1. create a virtual environment in ./.venv
  2. install dependencies (telethon, aiohttp) into it
  3. ask for your Telegram credentials and log you in (creates the session)

After it finishes, start the bot with:

    ./.venv/bin/python userbot.py        (Linux/macOS)
    .venv\\Scripts\\python userbot.py      (Windows)
"""

import os
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(ROOT, ".venv")


def venv_python():
    if os.name == "nt":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def create_venv():
    py = venv_python()
    if os.path.exists(py):
        print("[1/3] venv already exists at .venv — reusing it.")
        return
    print("[1/3] Creating virtual environment in .venv …")
    venv.EnvBuilder(with_pip=True).create(VENV_DIR)


def install_deps():
    py = venv_python()
    req = os.path.join(ROOT, "requirements.txt")
    print("[2/3] Installing dependencies …")
    subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "-r", req])


def run_login():
    py = venv_python()
    print("[3/3] Logging in to Telegram …\n")
    subprocess.check_call([py, os.path.join(ROOT, "login.py")])


def main():
    create_venv()
    install_deps()
    run_login()
    py = venv_python()
    print("\nSetup complete. Start the userbot with:\n")
    print("    %s userbot.py\n" % py)
    print("Then send links (one per line) to your Saved Messages and run")
    print("'.monitor' in any chat from your own account.")


if __name__ == "__main__":
    main()
