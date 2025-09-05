#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from html import unescape
from pathlib import Path
from collections import Counter
import builtins
import atexit

# ========= CONFIG =========
URL = "https://pokeheroes.com/gc_hangman"
COOKIE_STRING = "PHPSESSID=pdnh5fl1jvn139c0l0rglmug7s; _gcl_au=1.1.1884119554.1756846145.1072503122.1756846377.1756846377; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8; friendbar_hide=hide"  # ← poné tu PHPSESSID válido
WORDLIST_PATH = Path("hangman_words.txt")
LOG_PATH = Path("log.txt")
RESULTS_PATH = Path("results.txt")

# Autorefresco cuando NO se encuentra la palabra
AUTO_REFRESH_ON_FALLBACK = True
REFRESH_INTERVAL_SEC = 2
MAX_REFRESH_TRIES = 60

# Cuando aparece el banner de INSTRUCTIONS, esperar 5 minutos antes de refrescar
INSTRUCTION_WAIT_SEC = 300  # 5 minutos

# Auto-juego (letra más frecuente entre candidatas)
AUTO_GUESS_WHEN_CANDIDATES = True
AUTO_GUESS_MAX_PER_ROUND = 26
AUTO_GUESS_SLEEP_SEC = 0.6

# Fallback cuando NO hay candidatas: orden de frecuencia en inglés
FALLBACK_GUESS_WHEN_NO_CANDIDATES = True
FALLBACK_FREQ_ORDER = "ETAOINSHRDLUCMFYWGPBVKXQJZ"
FALLBACK_MAX_PER_ROUND = 26
FALLBACK_SLEEP_SEC = 0.5

# Timeout de input (auto-ENTER)
INPUT_TIMEOUT_SEC = 5
# ==========================

if os.name == "nt":
    import msvcrt  # Windows

# === Logging setup ===
_original_print = builtins.print
_logged_messages: list[str] = []

current_streak = 0
max_streak = 0
total_coins = 0

def log_print(*args, sep=" ", end="\n", **kwargs):
    msg = sep.join(str(a) for a in args) + end
    _logged_messages.append(msg.rstrip("\n"))
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(msg)

builtins.print = log_print

def _print_last_message():
    if _logged_messages:
        _original_print(_logged_messages[-1])

atexit.register(_print_last_message)
# ======================

def log_round_result(raw_word: str | None) -> None:
    global current_streak, max_streak, total_coins
    success = bool(raw_word and "_" not in raw_word)
    result_text = f"{raw_word or '-'} - {'SUCCESS' if success else 'FAIL'}"
    log_print(f"RESULT: {result_text}")
    if success:
        current_streak += 1
        coins = current_streak * 25
        total_coins += coins
        if current_streak > max_streak:
            max_streak = current_streak
    else:
        current_streak = 0
    os.system("cls" if os.name == "nt" else "clear")
    for line in (
        f"Racha actual: {current_streak}",
        f"Racha máxima: {max_streak}",
        f"Total de monedas ganadas: {total_coins}",
    ):
        log_print(line)
        _original_print(line)

def cookies_from_string(s: str) -> dict:
    d = {}
    for part in [p.strip() for p in s.split(";") if p.strip()]:
        if "=" in part and not part.lower().startswith("expires"):
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
    return d

def normalize_text(txt: str) -> str:
    txt = unescape(txt)
    txt = re.sub(r"\xa0{2,}", " ", txt)
    txt = txt.replace("\xa0", "")
    return re.sub(r"[ \t\r\f\v]+", " ", txt).strip()


def parse_game_word(raw: str) -> str:
    raw = unescape(raw).replace("\xa0", " ").upper()
    raw = re.sub(r"[^A-Z_ ]+", "", raw)
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == " ":
            j = i
            while j < len(raw) and raw[j] == " ":
                j += 1
            if j - i > 1:
                out.append(" ")
            i = j
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)

def load_wordlist(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def spaced(s: str) -> str:
    return " ".join(list(s))

def matches_pattern(candidate: str, raw_game_word: str, wrong_letters: set[str] | None = None) -> bool:
    """
    - misma longitud/espacios que el patrón
    - respeta letras reveladas
    - '_' acepta letra (no espacio)
    - NO repite una letra revelada en posiciones ocultas
    - excluye letras fallidas
    """
    cand = candidate.upper().replace(" ", "")
    patt = raw_game_word.upper().replace(" ", "")
    if len(cand) != len(patt):
        return False

    revealed_positions: dict[str, set[int]] = {}
    for i, (pc, cc) in enumerate(zip(patt, cand)):
        if pc == "_":
            continue
        elif pc.isalpha():
            if cc != pc:
                return False
            revealed_positions.setdefault(pc, set()).add(i)
        else:
            if cc != pc:
                return False

    for letter, pos_set in revealed_positions.items():
        for i, cc in enumerate(cand):
            if i not in pos_set and cc == letter:
                return False

    if wrong_letters:
        for bad in wrong_letters:
            if bad in cand:
                return False

    return True

def find_word(soup: BeautifulSoup, html: str) -> str | None:
    # 1) span con letter-spacing
    span = soup.find("span", attrs={"style": lambda s: s and "letter-spacing" in s.lower()})
    if span:
        t = parse_game_word(span.get_text())
        if t and re.fullmatch(r"[A-Z_ ]+", t):
            return t
    # 2) primer span dentro de center
    center = soup.find("center")
    if center:
        sp2 = center.find("span")
        if sp2:
            t = parse_game_word(sp2.get_text())
            if t and re.fullmatch(r"[A-Z_ ]+", t):
                return t
    # 3) spans en #textbar que parezcan palabra (_ y letras)
    for sp in soup.select("#textbar span"):
        t = parse_game_word(sp.get_text())
        if "_" in t and re.fullmatch(r"[A-Z_ ]+", t):
            return t
    # 4) regex en HTML
    m = re.search(r"<span[^>]*>([A-Za-z_ \u00A0]{3,})</span>", html, re.I)
    if m:
        t = parse_game_word(m.group(1))
        if "_" in t and re.fullmatch(r"[A-Z_ ]+", t):
            return t
    # 5) regex en texto plano
    plain = soup.get_text(" ")
    for m2 in re.finditer(r"[A-Za-z_ \u00A0]{3,}", plain):
        t = parse_game_word(m2.group(0))
        if "_" in t and re.fullmatch(r"[A-Z_ ]+", t):
            return t
    return None

def is_instruction_banner_text(text_upper: str) -> bool:
    """
    Detecta el banner de instrucciones (cuando en Word aparece el texto largo).
    """
    # Señales robustas (inglés del sitio):
    return (
        "INSTRUCTIONS" in text_upper and
        "HANGMAN GAME" in text_upper and
        "RANDOMLY SELECTS" in text_upper
    )

def grab_metrics(soup: BeautifulSoup) -> tuple[str, str, str]:
    txt = normalize_text(soup.get_text(" ", strip=True))
    def rx(label):
        m = re.search(rf"{re.escape(label)}:\s*(\d+)", txt, re.I)
        return m.group(1) if m else "?"
    return rx("Solved Hangmen in a row"), rx("Correct Guesses"), rx("Lives left")

# --- Estadísticas de rondas y monedas ---
_last_streak: int | None = None
_max_streak = 0

def _update_round_stats(solved_str: str) -> None:
    """Actualiza y muestra rondas, máximo y monedas según la racha actual."""
    global _last_streak, _max_streak
    if not solved_str.isdigit():
        return
    current = int(solved_str)

    changed = (_last_streak is None) or (current != _last_streak)
    if not changed:
        return

    _last_streak = current
    if current > _max_streak:
        _max_streak = current

    coins = current * 25
    print(f"Rondas: {current} | Máximo: {_max_streak} | Monedas: {coins}")


def extract_used_and_wrong_letters(soup: BeautifulSoup, raw_word: str | None) -> tuple[set[str], set[str]]:
    used = set()
    for a in soup.find_all("a", class_="letterGuess"):
        letter = (a.get_text(strip=True) or "").upper()
        if len(letter) == 1 and letter.isalpha() and not a.get("href"):
            used.add(letter)
    letters_in_word = set(ch for ch in (raw_word or "") if ch.isalpha())
    wrong = used - letters_in_word if raw_word else used
    return used, wrong

def headers_common():
    return {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "referer": "https://pokeheroes.com/gc_hangman?",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "es-ES,es;q=0.9,en;q=0.8",
        "upgrade-insecure-requests": "1",
    }

def request_page(sess: requests.Session, cookies: dict, letter: str | None):
    params = {"guess": letter} if letter else None
    r = sess.get(URL, params=params, headers=headers_common(), cookies=cookies, timeout=30)
    r.raise_for_status()
    return r.text

def refresh_round(sess: requests.Session, cookies: dict):
    params = {"_": int(time.time() * 1000)}  # cache-buster
    r = sess.get(URL, params=params, headers=headers_common(), cookies=cookies, timeout=30)
    r.raise_for_status()
    return r.text

def is_game_page(soup: BeautifulSoup) -> bool:
    txt = normalize_text(soup.get_text(" ", strip=True))
    return bool(soup.select("a.letterGuess")) or ("Hangman" in txt and "Guess the word" in txt)

def print_state(raw_word: str | None, soup: BeautifulSoup):
    solved, correct, lives = grab_metrics(soup)
    global current_streak
    try:
        current_streak = int(solved)
    except (TypeError, ValueError):
        current_streak = 0
    if raw_word:
        print(f"Word: {spaced(raw_word)} ")
    else:
        center = soup.find("center")
        approx = normalize_text(center.get_text(" ", strip=True)).upper() if center else "(vacío)"
        print(f"Word: {spaced(approx)} (palabra no encontrada) ")
    print(f"Racha actual: {current_streak}")
    print(f"Correct Guesses: {correct}")
    print(f"Lives left: {lives}")
    RESULTS_PATH.write_text(str(current_streak), encoding="utf-8")
    _update_round_stats(solved)
    return solved, correct, lives

def round_finished(raw_word: str | None, lives: str | None) -> bool:
    if raw_word and "_" not in raw_word:
        return True
    try:
        return int(lives) <= 0
    except (TypeError, ValueError):
        return False

def auto_refresh_until_word(sess: requests.Session, cookies: dict, interval=2, max_tries=60):
    """
    Autorefresca hasta que aparezca la palabra.
    Si se detecta el banner de INSTRUCTIONS, espera INSTRUCTION_WAIT_SEC entre intentos.
    """
    last_soup = None
    empty_center_hits = 0

    for i in range(1, max_tries + 1):
        html = refresh_round(sess, cookies)
        soup = BeautifulSoup(html, "html.parser")

        if not is_game_page(soup):
            Path("last_response.html").write_text(html, encoding="utf-8")
            print("\n❌ No llegó la página del juego. Guardé last_response.html")
            return None, soup

        raw_word = find_word(soup, html)
        if raw_word:
            print("\rWord: " + " " * 120, end="\r")
            print(f"Word: {spaced(raw_word)} ")
            return raw_word, soup

        center = soup.find("center")
        approx = normalize_text(center.get_text(" ", strip=True)).upper() if center else ""
        if approx:
            empty_center_hits = 0
            line = f"Word: {spaced(approx)} (palabra no encontrada) [{i}/{max_tries}] "
        else:
            empty_center_hits += 1
            line = f"Word: (sin bloque del juego) [{i}/{max_tries}] "

        print("\r" + line + " " * 8, end="", flush=True)

        # si vemos el banner, esperar 5 minutos antes del próximo intento
        wait = INSTRUCTION_WAIT_SEC if is_instruction_banner_text(approx) else interval

        if approx == "" and empty_center_hits >= 3:
            Path("last_response.html").write_text(html, encoding="utf-8")
            print("\n❌ El bloque del juego vino vacío varias veces. Guardé last_response.html")
            return None, soup

        last_soup = soup
        time.sleep(wait)

    print()
    return None, last_soup

def rank_letters(candidates: list[str], used_letters: set[str]) -> list[tuple[str, int]]:
    """
    Ranking por DF (en cuántas candidatas aparece la letra), excluyendo usadas.
    """
    counter = Counter()
    for w in candidates:
        letters = {ch for ch in w.upper() if "A" <= ch <= "Z"}
        for ch in letters:
            if ch not in used_letters:
                counter[ch] += 1
    return sorted(counter.items(), key=lambda x: (-x[1], x[0]))

def is_new_round_pattern(raw_word: str | None) -> bool:
    return bool(raw_word) and all(ch in {"_", " "} for ch in raw_word)

def timed_input(prompt: str, timeout: int) -> str:
    print(prompt, end="", flush=True)
    if os.name == "nt":
        buf = []
        start = time.time()
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    print()
                    return "".join(buf)
                elif ch == "\003":
                    raise KeyboardInterrupt
                elif ch == "\b":
                    if buf:
                        buf.pop()
                        print("\b \b", end="", flush=True)
                else:
                    buf.append(ch)
                    print(ch, end="", flush=True)
            if time.time() - start >= timeout:
                print()
                return ""
            time.sleep(0.05)
    else:
        import select
        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
        if rlist:
            line = sys.stdin.readline()
            return line.rstrip("\n")
        else:
            print()
            return ""

def auto_guess_loop(sess, cookies, wordlist, soup, raw_word, used, wrong):
    """
    Con candidatas: intentar letras más frecuentes (excluyendo usadas).
    """
    tries = 0
    while AUTO_GUESS_WHEN_CANDIDATES and tries < AUTO_GUESS_MAX_PER_ROUND:
        candidates = [w for w in wordlist if matches_pattern(w, raw_word, wrong_letters=wrong)]
        if not candidates:
            break
        ranking = rank_letters(candidates, used_letters=used)
        if not ranking:
            break
        next_letter = ranking[0][0]
        print(f"\n🤖 Auto: probando {next_letter} (top entre {len(candidates)} candidatas)")
        html = request_page(sess, cookies, next_letter)
        soup = BeautifulSoup(html, "html.parser")
        raw_word = find_word(soup, html)
        print_state(raw_word, soup)
        used, wrong = extract_used_and_wrong_letters(soup, raw_word)
        if raw_word and "_" not in raw_word:
            word_upper = raw_word.upper().strip()
            if word_upper not in [w.upper() for w in wordlist]:
                with WORDLIST_PATH.open("a", encoding="utf-8") as f:
                    f.write(word_upper + "\n")
                wordlist.append(word_upper)
                print(f"\n✅ Palabra agregada al banco: {word_upper}")
        _, _, lives = grab_metrics(soup)
        if lives == "?":
            break
        if round_finished(raw_word, lives):
            break
        tries += 1
        time.sleep(AUTO_GUESS_SLEEP_SEC)
    return raw_word, soup

def fallback_guess_loop(sess, cookies, wordlist, soup, raw_word, used, wrong):
    """
    Sin candidatas: probar letras por frecuencia en inglés (excluye usadas).
    """
    pool = [ch for ch in FALLBACK_FREQ_ORDER if ch not in used]
    if not pool:
        print("\n(No hay letras disponibles para fallback)")
        return raw_word, soup

    tries = 0
    for next_letter in pool:
        if tries >= FALLBACK_MAX_PER_ROUND:
            break
        print(f"\n🤖 Fallback: probando {next_letter} (sin candidatas)")
        html = request_page(sess, cookies, next_letter)
        soup = BeautifulSoup(html, "html.parser")
        raw_word = find_word(soup, html)
        print_state(raw_word, soup)
        used, wrong = extract_used_and_wrong_letters(soup, raw_word)
        if raw_word and "_" not in raw_word:
            word_upper = raw_word.upper().strip()
            if word_upper not in [w.upper() for w in wordlist]:
                with WORDLIST_PATH.open("a", encoding="utf-8") as f:
                    f.write(word_upper + "\n")
                wordlist.append(word_upper)
                print(f"\n✅ Palabra agregada al banco: {word_upper}")
        _, _, lives = grab_metrics(soup)
        if lives == "?":
            break
        if round_finished(raw_word, lives):
            break
        tries += 1
        time.sleep(FALLBACK_SLEEP_SEC)
    return raw_word, soup

def main():
    cookies = cookies_from_string(COOKIE_STRING)
    wordlist = load_wordlist(WORDLIST_PATH)

    with requests.Session() as sess:
        # GET inicial
        try:
            _ = request_page(sess, cookies, None)
        except Exception as e:
            print(f"Error inicial: {e}")
            return

        while True:
            try:
                entrada = timed_input(
                    f"\nLetra (A-Z) | ENTER=refrescar | salir/exit (auto-ENTER en {INPUT_TIMEOUT_SEC}s): ",
                    INPUT_TIMEOUT_SEC
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nChau!")
                break

            if entrada.lower() in {"salir", "exit"}:
                print("Chau!")
                break

            letter = None
            if entrada:
                if len(entrada) == 1 and entrada.isalpha():
                    letter = entrada.upper()
                else:
                    print("Ingresá UNA letra A-Z, o ENTER para refrescar.")
                    continue

            try:
                html = request_page(sess, cookies, letter)
            except Exception as e:
                print(f"Error de red: {e}")
                continue

            soup = BeautifulSoup(html, "html.parser")
            raw_word = find_word(soup, html)

            # Si no encontramos la palabra, autorefrescar hasta que aparezca (con espera 5 min si es banner)
            if not raw_word and AUTO_REFRESH_ON_FALLBACK:
                print("\n🔄 No se encontró la palabra. Autorefrescando… (Ctrl+C para cortar)")
                try:
                    raw_word, soup = auto_refresh_until_word(
                        sess, cookies, interval=REFRESH_INTERVAL_SEC, max_tries=MAX_REFRESH_TRIES
                    )
                except KeyboardInterrupt:
                    print("\n⏹ Autorefresco cancelado por el usuario.")
                solved, correct, lives = print_state(raw_word, soup)
            else:
                print()
                solved, correct, lives = print_state(raw_word, soup)

            if lives == "?":
                print("\nℹ️ 'Lives left' desconocido. Esperando 5s y refrescando...")
                time.sleep(5)
                try:
                    html = refresh_round(sess, cookies)
                except Exception as e:
                    print(f"Error al refrescar: {e}")
                    continue
                soup = BeautifulSoup(html, "html.parser")
                raw_word = find_word(soup, html)
                solved, correct, lives = print_state(raw_word, soup)
                used, wrong = extract_used_and_wrong_letters(soup, raw_word)
                print("Letras fallidas:", " ".join(sorted(wrong)) if wrong else "-")
                continue

            # Letras usadas/fallidas
            used, wrong = extract_used_and_wrong_letters(soup, raw_word)
            print("Letras fallidas:", " ".join(sorted(wrong)) if wrong else "-")

            if raw_word:
                # Si es NUEVA RONDA (solo '_' y espacios): armar candidatas por "shape" y auto-adivinar
                if is_new_round_pattern(raw_word):
                    candidates = [w for w in wordlist if matches_pattern(w, raw_word, wrong_letters=wrong)]
                    if candidates:
                        print(f"\nCandidatas (shape) ({len(candidates)}):")
                        for w in candidates:
                            print(f"- {w}")
                        ranked = rank_letters(candidates, used_letters=used)
                        if ranked:
                            top_line = " ".join(f"{ltr}:{cnt}" for ltr, cnt in ranked[:15])
                            print("\nLetras por frecuencia (excluyendo intentadas):")
                            print(top_line)
                        else:
                            print("\nLetras por frecuencia: (sin sugerencias; todas intentadas)")
                        if AUTO_GUESS_WHEN_CANDIDATES:
                            raw_word, soup = auto_guess_loop(sess, cookies, wordlist, soup, raw_word, used, wrong)
                    else:
                        print("\nCandidatas (shape) (0): (ninguna en el banco para ese patrón)")

                # Flujo normal: candidatas por patrón actual
                candidates = [w for w in wordlist if matches_pattern(w, raw_word, wrong_letters=wrong)]
                if candidates:
                    print(f"\nCandidatas ({len(candidates)}):")
                    for w in candidates:
                        print(f"- {w}")
                    ranked = rank_letters(candidates, used_letters=used)
                    if ranked:
                        top_line = " ".join(f"{ltr}:{cnt}" for ltr, cnt in ranked[:15])
                        print("\nLetras por frecuencia (excluyendo intentadas):")
                        print(top_line)
                    else:
                        print("\nLetras por frecuencia: (sin sugerencias; todas intentadas)")
                    if AUTO_GUESS_WHEN_CANDIDATES:
                        raw_word, soup = auto_guess_loop(sess, cookies, wordlist, soup, raw_word, used, wrong)
                else:
                    print("\nCandidatas (0): (ninguna con ese patrón en el banco)")
                    # Fallback: probar letras por frecuencia global si no hay candidatas
                    if FALLBACK_GUESS_WHEN_NO_CANDIDATES:
                        raw_word, soup = fallback_guess_loop(sess, cookies, wordlist, soup, raw_word, used, wrong)

                # Guardar si quedó completa
                if raw_word and "_" not in raw_word:
                    word_upper = raw_word.upper().strip()
                    if word_upper not in [w.upper() for w in wordlist]:
                        with WORDLIST_PATH.open("a", encoding="utf-8") as f:
                            f.write(word_upper + "\n")
                        wordlist.append(word_upper)
                        print(f"\n✅ Palabra agregada al banco: {word_upper}")

            # Fin de ronda → refrescar
            _, _, lives = grab_metrics(soup)
            if lives == "?":
                print("\nℹ️ 'Lives left' desconocido. Esperando 5s y refrescando...")
                time.sleep(5)
                try:
                    html2 = refresh_round(sess, cookies)
                except Exception as e:
                    print(f"Error al refrescar: {e}")
                    continue
                soup2 = BeautifulSoup(html2, "html.parser")
                new_raw = find_word(soup2, html2)
                print("\n— Refrescado —")
                print_state(new_raw, soup2)
                used2, wrong2 = extract_used_and_wrong_letters(soup2, new_raw)
                print("Letras fallidas:", " ".join(sorted(wrong2)) if wrong2 else "-")
                continue
            if round_finished(raw_word, lives):
                log_round_result(raw_word)
                print("\n🔄 Ronda terminada. Refrescando para nueva palabra...")
                try:
                    html2 = refresh_round(sess, cookies)
                except Exception as e:
                    print(f"Error al refrescar: {e}")
                    continue
                soup2 = BeautifulSoup(html2, "html.parser")
                new_raw = find_word(soup2, html2)
                print("\n— Nueva ronda —")
                print_state(new_raw, soup2)
                used2, wrong2 = extract_used_and_wrong_letters(soup2, new_raw)
                print("Letras fallidas:", " ".join(sorted(wrong2)) if wrong2 else "-")

                # En nueva ronda: candidatas por shape y auto-adivinar
                if new_raw and is_new_round_pattern(new_raw):
                    new_candidates = [w for w in wordlist if matches_pattern(w, new_raw, wrong_letters=wrong2)]
                    if new_candidates:
                        print(f"\nCandidatas (shape) ({len(new_candidates)}):")
                        for w in new_candidates:
                            print(f"- {w}")
                        ranked2 = rank_letters(new_candidates, used_letters=used2)
                        if ranked2:
                            print("\nLetras por frecuencia (excluyendo intentadas):")
                            print(" ".join(f"{ltr}:{cnt}" for ltr, cnt in ranked2[:15]))
                        if AUTO_GUESS_WHEN_CANDIDATES:
                            _rw, _soup = auto_guess_loop(sess, cookies, wordlist, soup2, new_raw, used2, wrong2)
                    else:
                        print("\nCandidatas (shape) (0): (ninguna en el banco para ese patrón)")

if __name__ == "__main__":
    main()
