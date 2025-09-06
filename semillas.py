#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import contextlib
from pathlib import Path
from http.cookiejar import MozillaCookieJar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# === Config ===
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import contextlib
from pathlib import Path
from http.cookiejar import MozillaCookieJar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# === Config ===
COOKIES_FILE   = "cookies.txt"   # archivo con cookies (Netscape o "k=v; k2=v2")
TOOLS_SHED     = "https://pokeheroes.com/toolshed"

MAKER_ID       = 2               # Setear por GUI
DESIRED_TOTAL  = 10              # Setear por GUI
LEVEL_START    = 10              # Setear por GUI
LEVEL_MIN      = 1               # Setear por GUI
PRIORITY_BERRIES = ["Oran", "Pomeg", "Nanab", "Mago", "Pecha", "Chesto", "Cheri"]  # Setear por GUI
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


def build_session() -> requests.Session:
    s = requests.Session()

    # Headers parecidos al navegador
    s.headers.update({
        "accept": "text/html, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "referer": TOOLS_SHED,
        "origin": "https://pokeheroes.com",
        "accept-language": "es-ES,es;q=0.9,en;q=0.8",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),
        "connection": "keep-alive",
    })

    # Reintentos para POST (maneja 429/5xx y desconexiones)
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.8,                 # 0.8, 1.6, 3.2, ...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def safe_post(session: requests.Session, url: str, data: dict, timeout: int = 30) -> requests.Response | None:
    """
    POST con manejo de desconexiones: intenta varias veces (por el HTTPAdapter)
    y además captura errores de conexión devolviendo None para que el flujo siga.
    """
    try:
        return session.post(url, data=data, timeout=timeout)
    except requests.exceptions.RequestException as e:
        print(f"[WARN] POST {url} falló por red: {e}")
        return None


def parse_used_and_busy(html: str | None) -> tuple[int, bool]:
    """
    Devuelve (usadas_en_esta_llamada, maker_ocupado)
    - usadas_en_esta_llamada: abs(tercer parámetro de addBerryToBag), p.ej. -10 => 10
    - maker_ocupado: True si aparece 'prodProgress'
    Si html es None o vacío, devuelve (0, False).
    """
    if not html:
        return 0, False
    used = 0
    m = RX_DELTA.search(html)
    if m:
        with contextlib.suppress(Exception):
            used = abs(int(m.group(3)))
    busy = bool(RX_BUSY.search(html))
    return used, busy


def claim_seed_maker(session: requests.Session, maker_id: int) -> None:
    resp = safe_post(session, CLAIM_URL, {"maker": str(maker_id)})
    code = resp.status_code if resp is not None else "ERR"
    print("claim:", code)


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
    resp = safe_post(session, FILL_URL, payload)
    html = resp.text if (resp is not None and resp.text) else ""
    used, busy = parse_used_and_busy(html)
    preview = html[:220].replace("\n", " ") if html else "<sin respuesta>"
    return used, busy, preview


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
            # En este nivel no había de ninguna de las 3 o no hubo respuesta válida: bajar nivel
            current_level -= 1
            if current_level >= LEVEL_MIN:
                print(f"  Sin stock/respuesta en nivel {current_level+1}. Bajando a {current_level}…")
        else:
            # Hubo consumo en este nivel. Si aún queda, reintentar en el mismo nivel.
            print(f"  En nivel {current_level} se usaron {used_at_level}. Restan {remaining}. Reintento en el mismo nivel.")

    print(f"\nResumen del ciclo: objetivo {DESIRED_TOTAL}, usadas {total_used}, faltan {remaining}.")
    return total_used


def main():
    session = build_session()

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


def build_session() -> requests.Session:
    s = requests.Session()

    # Headers parecidos al navegador
    s.headers.update({
        "accept": "text/html, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "referer": TOOLS_SHED,
        "origin": "https://pokeheroes.com",
        "accept-language": "es-ES,es;q=0.9,en;q=0.8",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),
        "connection": "keep-alive",
    })

    # Reintentos para POST (maneja 429/5xx y desconexiones)
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.8,                 # 0.8, 1.6, 3.2, ...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def safe_post(session: requests.Session, url: str, data: dict, timeout: int = 30) -> requests.Response | None:
    """
    POST con manejo de desconexiones: intenta varias veces (por el HTTPAdapter)
    y además captura errores de conexión devolviendo None para que el flujo siga.
    """
    try:
        return session.post(url, data=data, timeout=timeout)
    except requests.exceptions.RequestException as e:
        print(f"[WARN] POST {url} falló por red: {e}")
        return None


def parse_used_and_busy(html: str | None) -> tuple[int, bool]:
    """
    Devuelve (usadas_en_esta_llamada, maker_ocupado)
    - usadas_en_esta_llamada: abs(tercer parámetro de addBerryToBag), p.ej. -10 => 10
    - maker_ocupado: True si aparece 'prodProgress'
    Si html es None o vacío, devuelve (0, False).
    """
    if not html:
        return 0, False
    used = 0
    m = RX_DELTA.search(html)
    if m:
        with contextlib.suppress(Exception):
            used = abs(int(m.group(3)))
    busy = bool(RX_BUSY.search(html))
    return used, busy


def claim_seed_maker(session: requests.Session, maker_id: int) -> None:
    resp = safe_post(session, CLAIM_URL, {"maker": str(maker_id)})
    code = resp.status_code if resp is not None else "ERR"
    print("claim:", code)


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
    resp = safe_post(session, FILL_URL, payload)
    html = resp.text if (resp is not None and resp.text) else ""
    used, busy = parse_used_and_busy(html)
    preview = html[:220].replace("\n", " ") if html else "<sin respuesta>"
    return used, busy, preview


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
            # En este nivel no había de ninguna de las 3 o no hubo respuesta válida: bajar nivel
            current_level -= 1
            if current_level >= LEVEL_MIN:
                print(f"  Sin stock/respuesta en nivel {current_level+1}. Bajando a {current_level}…")
        else:
            # Hubo consumo en este nivel. Si aún queda, reintentar en el mismo nivel.
            print(f"  En nivel {current_level} se usaron {used_at_level}. Restan {remaining}. Reintento en el mismo nivel.")

    print(f"\nResumen del ciclo: objetivo {DESIRED_TOTAL}, usadas {total_used}, faltan {remaining}.")
    return total_used


def main():
    session = build_session()

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
