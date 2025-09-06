#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import requests
from datetime import datetime

BASE = "https://pokeheroes.com"
AJAX = f"{BASE}/includes/ajax/berrygarden"

# Pegá tu header Cookie COMPLETO (tal cual de DevTools)
COOKIE_STRING = "PHPSESSID=pdnh5fl1jvn139c0l0rglmug7s; _gcl_au=1.1.1884119554.1756846145.1072503122.1756846377.1756846377; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8; friendbar_hide=hide"

CYCLE_DELAY_SEC = 30  # # Setear por GUI
BERRY_ORDER = ["Oran", "Pomeg", "Nanab", "Mago", "Pecha", "Chesto", "Cheri"] # Setear por GUI
LEVEL = "1" # Setear por GUI
VERBOSE = True  # poné False si no querés ver los BODYs

def parse_cookie_string(s: str):
    jar = requests.cookies.RequestsCookieJar()
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            jar.set(k.strip(), v.strip(), domain="pokeheroes.com", path="/")
    return jar

HEADERS = {
    "accept": "text/html, */*; q=0.01",
    "accept-language": "es-ES,es;q=0.9,en;q=0.8",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
    "origin": BASE,
    "referer": f"{BASE}/berrygarden",
    "user-agent": "Mozilla/5.0"
}

s = requests.Session()
s.headers.update(HEADERS)
s.cookies.update(parse_cookie_string(COOKIE_STRING))

def dbg(label, r, show_text=False):
    txt = r.text
    print(f"{label}: status={r.status_code} len={len(txt)} redirected={bool(r.history)}")
    if show_text:
        print(f"BODY: {repr(txt[:300])}")

def get_garden_page():
    r = s.get(f"{BASE}/berrygarden", allow_redirects=False, timeout=20)
    dbg("GET /berrygarden", r, show_text=False)
    return r.text

def extract_token(html: str):
    pats = [
        r'name="token"\s+value="([a-zA-Z0-9_\-]{8,})"',
        r'name="csrf_token"\s+value="([a-zA-Z0-9_\-]{8,})"',
        r'data-token="([a-zA-Z0-9_\-]{8,})"',
        r'ajaxToken\s*[:=]\s*["\']([a-zA-Z0-9_\-]{8,})["\']',
    ]
    for p in pats:
        m = re.search(p, html)
        if m:
            return m.group(1)
    return None

def find_berry_ids(html: str, names):
    ids = {}
    for name in names:
        for p in [
            rf'data-berryname\s*=\s*"{name}"[^>]*data-berryid\s*=\s*"(\d+)"',
            rf'data-bname\s*=\s*"{name}"[^>]*data-bid\s*=\s*"(\d+)"',
            rf'data-name\s*=\s*"{name}"[^>]*data-id\s*=\s*"(\d+)"',
            rf'option[^>]+value="(\d+)"[^>]*>\s*{name}\s*<',
        ]:
            m = re.search(p, html, re.IGNORECASE)
            if m:
                ids[name] = m.group(1)
                break
    return ids

def post(path, data, show=False):
    r = s.post(f"{AJAX}/{path}", data=data, allow_redirects=False, timeout=20)
    dbg(f"POST {path}", r, show_text=show and VERBOSE)
    return r

def harvest(token=None):
    data = {"garden": "1"}
    if token:
        data["token"] = token
    return post("harvest.php", data, show=True)

def plant_request(pos, berry, berry_id=None, token=None, level=LEVEL):
    data = {"garden": "1", "pos": str(pos), "lvl": level}
    # Enviamos nombre e ID (por si el endpoint requiere ID):
    if berry_id:
        data["plant_id"] = berry_id
        data["plant"] = berry_id
    else:
        data["plant"] = berry
    if token:
        data["token"] = token
    return post("plant.php", data, show=True)

def water(i, token=None):
    data = {"garden": "1", "id": str(i)}
    if token:
        data["token"] = token
    return post("water.php", data, show=True)

def plant_ok(text: str) -> bool:
    # Éxito real: aparece el tiempo de finalización
    return "plantFinishTime" in text

def try_plant_in_order(pos, order, berry_ids, token):
    for berry in order:
        bid = berry_ids.get(berry)
        r = plant_request(pos, berry, berry_id=bid, token=token)
        if plant_ok(r.text):
            print(f"✔️ Pos {pos}: plantó {berry} (id={bid or '—'})")
            return True, berry
        else:
            print(f"✖️ Pos {pos}: {berry} no plantó, pruebo la siguiente…")
            time.sleep(0.2)
    print(f"⚠️ Pos {pos}: no pude plantar ninguna de la lista.")
    return False, None

def run_cycle():
    print(f"\n=== Ciclo @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    html = get_garden_page()
    token = extract_token(html)
    if not token:
        print("⚠️ No encontré token CSRF; pruebo sin token.")
    berry_ids = find_berry_ids(html, BERRY_ORDER)
    if berry_ids:
        print("IDs detectados:", berry_ids)

    time.sleep(0.3)
    harvest(token)
    time.sleep(0.4)

    # ✅ Posiciones 1..24 (no 0..23)
    for pos in range(0, 24):
        try_plant_in_order(pos, BERRY_ORDER, berry_ids, token)
        time.sleep(0.25)

    time.sleep(0.4)
    for i in range(0, 24):
        water(i, token=token)
        time.sleep(0.2)

    final_html = get_garden_page()
    planted_guess = len(re.findall(r'class="(?:plot|tile)[^"]*(?:occupied|planted)', final_html))
    print(f"🔎 Heurística: slots ocupados detectados: {planted_guess}")

if __name__ == "__main__":
    try:
        while True:
            run_cycle()
            print(f"⏳ Esperando {CYCLE_DELAY_SEC//60} min…")
            time.sleep(CYCLE_DELAY_SEC)
    except KeyboardInterrupt:
        print("\nCortao por el usuario. Vapaí.")
