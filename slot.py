#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import re
import html
from pathlib import Path
from http.cookiejar import MozillaCookieJar
import requests

# === Config ===
COOKIES_FILE = Path("cookies.txt")     # Netscape/Mozilla cookies.txt
URL = "https://httpbin.org/post"       # Cambiá por tu endpoint permitido
INTERVAL_SEC = 0.5
HEADERS = {
    "accept": "text/html, */*; q=0.01",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
}
DATA = {
    "coinside": "head",
    "bet": "1",
}

def load_cookies_into_session(session: requests.Session, path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    try:
        jar = MozillaCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies = jar
        return f"Netscape/Mozilla: {len(jar)} cookies cargadas."
    except Exception:
        pairs = [p.strip() for p in text.split(";") if "=" in p]
        cookies = dict(p.split("=", 1) for p in pairs)
        session.cookies.update(cookies)
        return f"Fallback simple: {len(cookies)} cookies cargadas."

def classify_result(body: str) -> str:
    """
    Devuelve 'You won', 'You lost' o 'Unknown' según el texto.
    Busca de forma case-insensitive y limpia HTML básico.
    """
    t = html.unescape(re.sub(r"<[^>]+>", " ", body)).lower()
    if "you won" in t or "you win" in t:
        return "You won"
    if "you lost" in t or "you lose" in t:
        return "You lost"
    return "Unknown"

def main():
    if not COOKIES_FILE.exists():
        print(f"No existe {COOKIES_FILE.resolve()}")
        return

    s = requests.Session()
    info = load_cookies_into_session(s, COOKIES_FILE)
    print(info)

    i = 0
    try:
        while True:
            try:
                r = s.post(URL, headers=HEADERS, data=DATA, timeout=15)
                verdict = classify_result(r.text)
                print(f"[{i}] {r.status_code} | {verdict}")
                i += 1
            except Exception as e:
                print(f"[{i}] ERROR: {e}")
            time.sleep(INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\nCortado por el usuario. Vapaí.")

if __name__ == "__main__":
    main()
