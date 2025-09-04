#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import os
from pathlib import Path
from time import monotonic
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================== CONFIG ==================
COOKIES_STRING = ""              # Pegá el header Cookie completo (p.ej. "PHPSESSID=...; otra=...")
COOKIES_FILE   = "cookies.txt"   # Si COOKIES_STRING está vacío, se usa este archivo si existe

SIZE                 = 36        # Cambiá a 30 si tu mesa es de 30
DELAY                = 2      # Pausa base tras cada flip ok
SLEEP_AFTER_A_BEFORE_B = 2    # Pausa extra entre A y B del mismo turno
PAIR_PAUSE           = 4      # Pausa tras MATCH (animación)
MISMATCH_PAUSE       = 4      # Pausa tras NO MATCH

# Reintentos “exploratorios”
MAX_RETRIES_EXP      = 4
RETRY_SLEEP_EXP      = 2
DEADLINE_EXP_SEC     = 18.0

# Reintentos “estrictos” (cerrar par conocido)
MAX_RETRIES_PAIR     = 12
RETRY_SLEEP_PAIR     = 23
DEADLINE_PAIR_SEC    = 14.0

# Red
NET_RETRIES_TOTAL    = 8
NET_BACKOFF_FACTOR   = 4
STATUS_FORCELIST     = [429, 500, 502, 503, 504]

WAIT_SECONDS = 100            # si ya lo agregaste, dejalo
COOLDOWN_AFTER_SKIP = 15.0    # segundos que “duerme” un índice problemático

# ============================================

BASE        = "https://pokeheroes.com"
URL_PAGE    = f"{BASE}/gc_concentration?d=2"
URL_FLIP    = f"{BASE}/includes/ajax/game_center/concentration_flip.php"
REFERER_XHR = "https://pokeheroes.com/gc_concentration?d=0"   # <-- CORREGIDO
ORIGIN      = "https://pokeheroes.com"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/139.0.0.0 Safari/537.36")

XHR_HEADERS = {
    "accept": "text/html, */*; q=0.01",
    "accept-language": "es-ES,es;q=0.9,en;q=0.8",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "priority": "u=1, i",
    "sec-ch-ua": "\"Not;A=Brand\";v=\"99\", \"Google Chrome\";v=\"139\", \"Chromium\";v=\"139\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-requested-with": "XMLHttpRequest",
    "Referer": REFERER_XHR,        # <-- usa el referer con d=0
    "Origin": ORIGIN,
    "User-Agent": UA,
    "Connection": "keep-alive",
}

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "es-ES,es;q=0.9,en;q=0.8",
    "upgrade-insecure-requests": "1",
    "User-Agent": UA,
    "Referer": URL_PAGE,
    "Connection": "keep-alive",
}

def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=NET_RETRIES_TOTAL,
        connect=NET_RETRIES_TOTAL,
        read=NET_RETRIES_TOTAL,
        backoff_factor=NET_BACKOFF_FACTOR,
        status_forcelist=STATUS_FORCELIST,
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": UA, "Connection": "keep-alive"})
    s.trust_env = True
    return s

def parse_cookie_string(s: str) -> dict:
    parts = [p.strip() for p in s.split(";") if "=" in p]
    return {k.split("=",1)[0].strip(): k.split("=",1)[1] for k in parts}

def load_cookies() -> dict:
    s = COOKIES_STRING.strip()
    if not s and Path(COOKIES_FILE).exists():
        s = Path(COOKIES_FILE).read_text(encoding="utf-8").strip()
    if not s and os.getenv("PH_COOKIE"):
        s = os.getenv("PH_COOKIE").strip()
    if not s:
        raise SystemExit("Falta Cookie: pegala en COOKIES_STRING o creá cookies.txt con la cookie en una línea.")
    return parse_cookie_string(s)

def ensure_warmup(session: requests.Session, cookies: dict):
    r = session.get(URL_PAGE, headers=PAGE_HEADERS, cookies=cookies, timeout=(10, 30), allow_redirects=True)
    print("[warmup]", r.status_code, r.url)
    low = r.text.lower()
    if any(s in low for s in ["login", "log in", "signin", "sign in"]) and "concentration" not in low:
        Path("warmup_response.html").write_text(r.text, encoding="utf-8")
        raise SystemExit("Parece que no estás logueado. Guardé warmup_response.html.")

# ---- Parsing de ID (desde bytes) ----
def extract_card_id_from_bytes(content: bytes, prev_known: str | None = None) -> str | None:
    tokens = re.findall(rb"\d+", content)
    if not tokens:
        return None
    def last3(t: bytes) -> str:
        return t[-3:].decode("ascii", errors="ignore").zfill(3)
    long_tokens = [t for t in tokens if len(t) >= 3]
    if long_tokens:
        for t in long_tokens:
            v = last3(t)
            if v != "000":
                return v
        return last3(long_tokens[0])
    best = max(tokens, key=len)
    v = last3(best)
    if v == "000":
        return None
    if prev_known and v != prev_known and len(best) < 3:
        return prev_known
    return v if len(best) >= 3 else None

# ---- Flip con dos modos: exploratorio vs estricto ----
def flip_generic(session, cookies, idx: int, expected: str | None,
                 max_retries: int, base_sleep: float, deadline_sec: float) -> str | None:
    start = monotonic()
    backoff = base_sleep
    for attempt in range(1, max_retries + 1):
        if monotonic() - start > deadline_sec:
            print(f"[deadline] idx={idx} {deadline_sec:.1f}s. {'mantengo previo' if expected else 'skip'}")
            return expected  # si teníamos expected, devolvelo; si no, None

        try:
            r = session.post(
                URL_FLIP,
                headers=XHR_HEADERS,
                cookies=cookies,
                data={"card": str(idx)},
                timeout=(10, 30),
                allow_redirects=False,
            )

            # Sólo acá se permite warmup: si el servidor redirige (sesión/nonce caído)
            if 300 <= r.status_code < 400:
                loc = r.headers.get("Location", "")
                print(f"[redir] idx={idx} {r.status_code} -> {loc}. Warmup…")
                ensure_warmup(session, cookies)
                time.sleep(0.6)
                continue

            cid = extract_card_id_from_bytes(r.content, prev_known=expected)

            # Dump de cuerpo si no hay dígitos para depurar
            if cid is None:
                Path(f"debug_flip_idx{idx}_attempt{attempt}.bin").write_bytes(r.content)

            # Modo estricto: si hay expected, sólo acepto ese valor
            if expected is not None:
                if cid == expected:
                    return cid
                print(f"[retry strict] idx={idx} intento {attempt}/{max_retries} (cid={cid}, esperado={expected}). {backoff:.2f}s")
                time.sleep(backoff)
                backoff *= 1.35
                continue

            # Modo exploratorio: aceptá cualquier ID válido
            if cid is not None and cid != "000":
                return cid

            print(f"[retry exp] idx={idx} intento {attempt}/{max_retries} (cid={cid}). {backoff:.2f}s")
            time.sleep(backoff)
            backoff *= 1.35

        except (requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ChunkedEncodingError) as e:
            # NO warmup acá: sólo backoff y reintentar
            print(f"[net] idx={idx} {type(e).__name__}: {e}. Esperando {max(backoff,0.8):.2f}s…")
            time.sleep(max(backoff, 0.8))
            backoff *= 1.4

    return expected  # agotado

def flip_explore(session, cookies, idx: int, prev_known: str | None) -> str | None:
    return flip_generic(session, cookies, idx, expected=None,
                        max_retries=MAX_RETRIES_EXP, base_sleep=RETRY_SLEEP_EXP, deadline_sec=DEADLINE_EXP_SEC)

def flip_strict_pair(session, cookies, idx: int, expected_id: str) -> str | None:
    return flip_generic(session, cookies, idx, expected=expected_id,
                        max_retries=MAX_RETRIES_PAIR, base_sleep=RETRY_SLEEP_PAIR, deadline_sec=DEADLINE_PAIR_SEC)

# ---- Solver ----
def solve(size: int, cookies: dict, warmup: bool = True) -> None:
    s = build_session()
    if warmup:
        ensure_warmup(s, cookies)

    known_id_by_idx: dict[int, str] = {}  # idx -> "XYZ"
    id_to_idxs: dict[str, set[int]] = {}  # "XYZ" -> {idx, ...}
    solved = set()                        # índices resueltos
    pending_pairs: list[tuple[int, int, str]] = []  # (i, j, id) pendientes de cerrar
    skipped_until: dict[int, float] = {}  # idx -> timestamp para reintentar

    log_path = Path(f"concentration_log_{int(time.time())}.txt")
    with log_path.open("w", encoding="utf-8") as outf:

        def log(msg: str):
            print(msg)
            outf.write(msg + "\n")
            outf.flush()

        def register(idx: int, cid: str):
            known_id_by_idx[idx] = cid
            id_to_idxs.setdefault(cid, set()).add(idx)
            mates = [i for i in id_to_idxs[cid] if i != idx and i not in solved]
            if mates:
                j = mates[0]
                pair = (min(idx, j), max(idx, j), cid)
                if pair not in pending_pairs:
                    pending_pairs.append(pair)

        def mark_skipped(idx: int):
            skipped_until[idx] = monotonic() + COOLDOWN_AFTER_SKIP

        def is_skipped(idx: int) -> bool:
            until = skipped_until.get(idx)
            if until is None:
                return False
            if monotonic() >= until:
                skipped_until.pop(idx, None)
                return False
            return True

        def find_next_pair():
            while pending_pairs:
                i, j, cid = pending_pairs[0]
                if i in solved or j in solved:
                    pending_pairs.pop(0)
                    continue
                if is_skipped(i) or is_skipped(j):
                    # buscá otro par disponible
                    for k in range(1, len(pending_pairs)):
                        ii, jj, cc = pending_pairs[k]
                        if ii not in solved and jj not in solved and not is_skipped(ii) and not is_skipped(jj):
                            pending_pairs.pop(k)
                            pending_pairs.insert(0, (ii, jj, cc))
                            return pending_pairs[0]
                    return None
                return pending_pairs[0]
            return None

        def pick_unknown(exclude):
            for k in range(size):
                if k in solved or k in exclude or is_skipped(k):
                    continue
                if k not in known_id_by_idx:
                    return k
            for k in range(size):
                if k not in solved and k not in exclude and not is_skipped(k):
                    return k
            for k in list(skipped_until):
                if not is_skipped(k) and k not in solved and k not in exclude:
                    return k
            return None

        while len(solved) < size:
            # 1) Cerrar pares primero (modo estricto)
            pair = find_next_pair()
            if pair:
                a, b, cid_goal = pair

                cid_a = flip_strict_pair(s, cookies, a, expected_id=cid_goal)
                if cid_a != cid_goal:
                    mark_skipped(a)
                    log(f"[pair-skip] idx={a:02d} no estabiliza id={cid_goal}. Lo intento luego.")
                    time.sleep(0.8)
                    continue
                register(a, cid_a)
                log(f"[Flip A*] idx={a:02d} -> id={cid_a} (estricto)")

                time.sleep(SLEEP_AFTER_A_BEFORE_B)

                cid_b = flip_strict_pair(s, cookies, b, expected_id=cid_goal)
                if cid_b != cid_goal:
                    mark_skipped(b)
                    log(f"[pair-skip] idx={b:02d} no estabiliza id={cid_goal}. Lo intento luego.")
                    time.sleep(0.8)
                    continue
                register(b, cid_b)
                log(f"[Flip B*] idx={b:02d} -> id={cid_b} (estricto)")

                if cid_a == cid_b == cid_goal:
                    solved.update({a, b})
                    pending_pairs[:] = [p for p in pending_pairs if not (p[0] in {a, b} or p[1] in {a, b})]
                    log(f"✅ MATCH id={cid_goal} | par=({a},{b}) | resueltas={len(solved)}/{size}")
                    time.sleep(PAIR_PAUSE)
                else:
                    log(f"⚠️ Par inconsistente: ({a}:{cid_a}) vs ({b}:{cid_b}) esperado={cid_goal}")
                    time.sleep(MISMATCH_PAUSE)
                continue

            # 2) Explorar
            a = pick_unknown(exclude=set())
            if a is None:
                break

            prev_a = known_id_by_idx.get(a)
            cid_a = flip_explore(s, cookies, a, prev_known=prev_a)

            if cid_a is None:
                mark_skipped(a)
                log(f"[skip] idx={a:02d} sin ID estable. Lo intento luego.")
                time.sleep(0.8)
                continue

            register(a, cid_a)
            log(f"[Flip A] idx={a:02d} -> id={cid_a}")

            mates = [i for i in id_to_idxs.get(cid_a, set()) if i != a and i not in solved and not is_skipped(i)]
            if mates:
                b = mates[0]
            else:
                b = pick_unknown(exclude={a})
                if b is None:
                    continue

            time.sleep(SLEEP_AFTER_A_BEFORE_B)

            prev_b = known_id_by_idx.get(b)
            if b in id_to_idxs.get(cid_a, set()):
                cid_b = flip_strict_pair(s, cookies, b, expected_id=cid_a)
            else:
                cid_b = flip_explore(s, cookies, b, prev_known=prev_b)

            if cid_b is None:
                mark_skipped(b)
                log(f"[skip] idx={b:02d} sin ID estable. Lo intento luego.")
                time.sleep(0.8)
                continue

            register(b, cid_b)
            log(f"[Flip B] idx={b:02d} -> id={cid_b}")

            if cid_a == cid_b:
                solved.update({a, b})
                pending_pairs[:] = [p for p in pending_pairs if not (p[0] in {a, b} or p[1] in {a, b})]
                log(f"✅ MATCH id={cid_a} | par=({a},{b}) | resueltas={len(solved)}/{size}")
                time.sleep(PAIR_PAUSE)
            else:
                log(f"❌ NO MATCH: ({a}:{cid_a}) vs ({b}:{cid_b}) | resueltas={len(solved)}/{size}")
                time.sleep(MISMATCH_PAUSE)

        log(f"Listo. Pares resueltos: {len(solved)}/{size}")
        log(f"Log guardado en: {log_path}")

if __name__ == "__main__":
    try:
        while True:
            cookies = load_cookies()

            # Juega una partida
            try:
                solve(size=SIZE, cookies=cookies, warmup=True)
            except Exception as e:
                print(f"[error] {e}")

            # Warmup post-partida ANTES de esperar 90s
            try:
                with build_session() as s:
                    ensure_warmup(s, cookies)
            except Exception as e:
                print(f"[post-warmup] {e}")

            # Espera visible de 90s y reinicia
            print(f"[sleep] Esperando {WAIT_SECONDS}s para iniciar una nueva partida…")
            for i in range(WAIT_SECONDS, 0, -1):
                print(f"\rReinicio en {i:02d}s", end="", flush=True)
                time.sleep(1)
            print("\n[restart] Nueva ejecución…")

    except KeyboardInterrupt:
        print("\n[exit] Cortado por el usuario.")
