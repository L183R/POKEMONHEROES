#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import contextlib
from pathlib import Path
from http.cookiejar import MozillaCookieJar
import requests

# === Config ===
COOKIES_FILE   = "cookies.txt"   # archivo con cookies (Netscape o "k=v; k2=v2")
TOOLS_SHED     = "https://pokeheroes.com/toolshed"

MAKER_ID       = 2               # Seed Maker #
DESIRED_TOTAL  = 10              # Cantidad total a usar por ciclo
LEVEL_START    = 10               # Nivel inicial
LEVEL_MIN      = 1               # Nivel mínimo
PRIORITY_BERRIES = ["Pecha", "Chesto", "Cheri"]  # Orden de prueba por nivel

CLAIM_URL = "https://pokeheroes.com/includes/ajax/berrygarden/claimSeedMaker.php"
FILL_URL  = "https://pokeheroes.com/includes/ajax/berrygarden/fillSeedMaker.php"

RX_DELTA = re.compile(r"addBerryToBag\('([^']+)',\s*(\d+),\s*(-?\d+)", re.I)
RX_BUSY  = re.compile(r"prodProgress", re.I)  # si aparece, el maker quedó ocupado


def load_cookies_from_file(session: requests.Session, path: str) -> int:
    """
    Carga cookies desde:
    - Formato Netscape/Mozilla (cookies.txt de extensiones)
    - O un header plano: "key=val; key2=val2; ..."
    Devuelve cuántas cookies cargó.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="ignore")

    # Intento 1: Netscape/Mozilla
    try:
        if "HTTP Cookie File" in raw or "\t" in raw:
            jar = MozillaCookieJar()
            jar.load(path, ignore_discard=True, ignore_expires=True)
            count = 0
            for c in jar:
                session.cookies.set_cookie(c)
                count += 1
            return count
    except Exception:
        pass

    # Intento 2: header "k=v; k2=v2"
    count = 0
    header_line = raw.replace("\n", ";")
    for token in header_line.split(";"):
        token = token.strip()
        if not token or "=" not in token:
            continue
        k, v = token.split("=", 1)
        session.cookies.set(k.strip(), v.strip())
        count += 1
    return count


def parse_used_and_busy(html: str) -> tuple[int, bool]:
    """
    Devuelve (usadas_en_esta_llamada, maker_ocupado)
    - usadas_en_esta_llamada: abs(tercer parámetro de addBerryToBag), p.ej. -10 => 10
    - maker_ocupado: True si aparece 'prodProgress'
    """
    used = 0
    m = RX_DELTA.search(html)
    if m:
        with contextlib.suppress(Exception):
            used = abs(int(m.group(3)))
    busy = bool(RX_BUSY.search(html))
    return used, busy


def claim_seed_maker(session: requests.Session, maker_id: int) -> None:
    r = session.post(CLAIM_URL, data={"maker": str(maker_id)}, timeout=30)
    print("claim:", r.status_code)


def try_fill(session: requests.Session, berry: str, amount: int, level: int, maker_id: int) -> tuple[int, bool, str]:
    """
    Intenta cargar 'amount' berries de 'berry' en 'level' para 'maker_id'.
    Devuelve (usadas, busy, preview_texto)
    """
    payload = {
        "berries": f"{berry},",
        "amount":  f"{amount},",
        "level":   f"{level},",
        "maker":   str(maker_id),
    }
    r = session.post(FILL_URL, data=payload, timeout=30)
    used, busy = parse_used_and_busy(r.text)
    return used, busy, r.text[:220]


def run_cycle(session: requests.Session) -> int:
    """
    Ejecuta un ciclo completo:
    - claim
    - esperar 1s
    - intentar llenar desde LEVEL_START bajando hasta LEVEL_MIN
      probando por nivel: Pecha -> Chesto -> Cheri
    Devuelve cuántas berries se usaron en total en el ciclo.
    """
    claim_seed_maker(session, MAKER_ID)
    time.sleep(1)

    remaining = DESIRED_TOTAL
    current_level = LEVEL_START
    total_used = 0

    while remaining > 0 and current_level >= LEVEL_MIN:
        used_at_level = 0
        print(f"\nNivel {current_level} — objetivo restante: {remaining}")

        for berry in PRIORITY_BERRIES:
            print(f"  Intento: {remaining}x {berry} nivel {current_level}")
            used, busy, preview = try_fill(session, berry, remaining, current_level, MAKER_ID)
            total_used += used
            remaining -= used
            used_at_level += used
            print(f"    → {berry}: usó {used} | Busy: {busy} | Preview: {preview!r}")

            if busy:
                # El maker quedó ocupado; no se puede seguir en este ciclo
                print("    Maker ocupao: cierro ciclo.")
                return total_used

            if remaining <= 0:
                break  # objetivo cumplido en este nivel

        if used_at_level == 0:
            # En este nivel no había de ninguna de las 3: bajar de nivel
            current_level -= 1
            if current_level >= LEVEL_MIN:
                print(f"  Sin stock en nivel {current_level+1}. Bajando a {current_level}…")
        else:
            # Hubo consumo en este nivel. Si aún queda, volver a intentar en el MISMO nivel
            # (por si no quedó ocupado y todavía hay capacidad).
            print(f"  En nivel {current_level} se usaron {used_at_level}. Restan {remaining}. Reintento en el mismo nivel.")

    print(f"\nResumen del ciclo: objetivo {DESIRED_TOTAL}, usadas {total_used}, faltan {remaining}.")
    return total_used


def main():
    session = requests.Session()
    session.headers.update({
        "accept": "text/html, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "referer": TOOLS_SHED,
    })

    n = load_cookies_from_file(session, COOKIES_FILE)
    print(f"Cookies cargadas: {n}")

    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"\n=== Ciclo #{cycle} ===")
            used = run_cycle(session)

            # Espera (berries_usadas * 8) + 2; si no usó ninguna, usa el objetivo.
            wait_base = used if used > 0 else DESIRED_TOTAL
            wait_secs = wait_base * 8 + 2
            print(f"Durmiendo {wait_secs} s (base={wait_base} berries). Ctrl+C pa’ cortar.")
            time.sleep(wait_secs)
    except KeyboardInterrupt:
        print("\nCortao por el usuario. Vapaí.")


if __name__ == "__main__":
    main()
