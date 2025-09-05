#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
from pathlib import Path
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ======== CONFIG ========
COOKIES_STRING = "PHPSESSID=pdnh5fl1jvn139c0l0rglmug7s; _gcl_au=1.1.1884119554.1756846145.1072503122.1756846377.1756846377; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8"
LIST_PRIORITY = ["unreturned", "online", "random"]
CYCLES = 3334              # pedir 10 listas
WORKERS = 30             # 10 workers
SAVE_LISTS = False       # True para guardar cada clicklist HTML
# ========================

CLICKLIST_URL = "https://pokeheroes.com/includes/ajax/pokemon/load_clicklist"
INTERACT_URL  = "https://pokeheroes.com/includes/ajax/pokemon/lite_interact.php"
REFERRER_FMT  = "https://pokeheroes.com/pokemon_lite?cl_type={}"  # newest/unreturned/...

BASE_HEADERS = {
    "accept": "text/html, */*; q=0.01",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://pokeheroes.com",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
}

def parse_cookie_string(cookie_str: str) -> requests.cookies.RequestsCookieJar:
    jar = requests.cookies.RequestsCookieJar()
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        jar.set(k.strip(), v.strip(), domain="pokeheroes.com")
    return jar

def extract_pairs_from_clicklist(html: str) -> List[Tuple[str, str]]:
    # pkmn_arr.push(new Array("pkmnid","pkmnsid", ... ));
    return re.findall(r'pkmn_arr\.push\(new Array\("(\d+)","(\d+)"', html)

def make_session(cookies: requests.cookies.RequestsCookieJar) -> requests.Session:
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    # referer se setea por request, pero dejamos UA y base aquí
    s.cookies.update(cookies)
    return s

def fetch_clicklist(session: requests.Session, list_type: str, save_lists: bool, cycle_idx: int):
    headers = dict(BASE_HEADERS)
    headers["referer"] = REFERRER_FMT.format(list_type)
    payload = {
        "type": list_type,
        "inarow": "0",
        "ret": "clicklist?err=done",
    }
    r = session.post(CLICKLIST_URL, data=payload, headers=headers, timeout=20)
    r.raise_for_status()
    html = r.text
    if save_lists:
        Path(f"clicklist_{cycle_idx}.html").write_text(html, encoding="utf-8")
    pairs = extract_pairs_from_clicklist(html)
    return pairs

def warm_interact(session: requests.Session, list_type: str, pkmnid: str, pkmnsid: str, inarow: int, berry: str = "") -> int:
    headers = dict(BASE_HEADERS)
    headers["referer"] = REFERRER_FMT.format(list_type)
    payload = {
        "pkmnid": pkmnid,
        "pkmnsid": pkmnsid,
        "method": "warm",
        "berry": berry,  # "" o "Razz Berry"
        "timeclick": str(int(time.time() * 1000)),
        "inarow": str(inarow),
    }
    r = session.post(INTERACT_URL, data=payload, headers=headers, timeout=20)
    return r.status_code  # podés inspeccionar r.text si necesitás

def main():
    if "PHPSESSID=" not in COOKIES_STRING:
        print("⚠️ Configurá COOKIES_STRING con tu PHPSESSID y demás cookies.")
        return

    cookiejar = parse_cookie_string(COOKIES_STRING)

    # Pre-creamos sesiones por worker (requests.Session NO es thread-safe)
    sessions = [make_session(cookiejar) for _ in range(WORKERS)]

    inarow_global = 1
    interaction_count = 0

    for cycle in range(1, CYCLES + 1):
        pairs = []
        list_type = ""
        # intentamos en orden: unreturned -> online -> random
        for candidate in LIST_PRIORITY:
            print(f"\n=== Ciclo {cycle}/{CYCLES}: pidiendo clicklist ({candidate}) ===")
            try:
                pairs = fetch_clicklist(sessions[0], candidate, SAVE_LISTS, cycle)
            except requests.RequestException as e:
                print(f"❌ Error al pedir clicklist: {e}")
                pairs = []
            if pairs:
                list_type = candidate
                break
            else:
                print("Lista vacía, probando siguiente…")

        if not pairs:
            print("No vinieron Pokémon en ninguna lista. Corto.")
            break

        print(f"→ {len(pairs)} Pokémon en la lista. Mandando warms en paralelo ({WORKERS} workers, sin delay)…")

        # Preparamos tareas con inarow asignado por índice (aprox. “secuencia”)
        jobs = []
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for idx, (pkmnid, pkmnsid) in enumerate(pairs, start=1):
                # round-robin de sesiones por worker
                sess = sessions[(idx - 1) % WORKERS]
                inarow = inarow_global
                inarow_global += 1
                jobs.append(
                    ex.submit(warm_interact, sess, list_type, pkmnid, pkmnsid, inarow, "")
                )

            ok = 0
            total = len(jobs)
            procesados = 0
            for fut in as_completed(jobs):
                try:
                    status = fut.result()
                    if status == 200:
                        ok += 1
                except Exception as e:
                    status = f"ERROR: {e}"
                procesados += 1
                print(f"→ Resultado: {status} ({ok}/{procesados}/{total})")

        interaction_count += ok
        print(f"✔️ Ciclo {cycle} completo: {ok}/{total} warms HTTP 200 (total: {interaction_count})")
        # sin delay entre ciclos; si te bloquea, agregá un sleep acá

    print("\nListo. Vapaí.")

if __name__ == "__main__":
    main()
