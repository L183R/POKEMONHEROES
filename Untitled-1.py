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

# ========= CONFIG =========
URL = "https://pokeheroes.com/gc_hangman"
COOKIE_STRING = "PHPSESSID=pdnh5fl1jvn139c0l0rglmug7s; _gcl_au=1.1.1884119554.1756846145.1072503122.1756846377.1756846377; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8; friendbar_hide=hide"  # ← poné tu PHPSESSID válido
WORDLIST_PATH = Path("hangman_words.txt")

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

def cookies_from_string(s: str) -> dict:
    d = {}
    for part in [p.strip() for p in s.split(";") if p.strip()]:
        if "=" in part and not part.lower().startswith("expires"):
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
    return d

def normalize_text(txt: str) -> str:
    txt = unescape(txt).replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", txt)

def load_wordlist(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def spaced(s: str) -> str:
    return " ".join(list(s))

def matches_pattern(candidate: str, raw_game_word: str, wrong_letters: set[str] | None = None) -> bool:
    """
    Filtro ESTRICTO:
    - misma longitud/espacios
    - respeta letras reveladas
    - '_' acepta letra (no espacio)
    - NO permite que una letra revelada aparezca además en posiciones ocultas
    - excluye letras fallidas
    """
    cand = candidate.upper()
    patt = raw_game_word.upper()
    if len(cand) != len(patt):
        return False

    revealed_positions: dict[str, set[int]] = {}
    for i, (pc, cc) in enumerate(zip(patt, cand)):
        if pc == " ":
            if cc != " ":
                return False
        elif pc == "_":
            if cc == " ":
                return False
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

def matches_shape_loose(candidate: str, raw_game_word: str, wrong_letters: set[str] | None = None) -> bool:
    """
    Filtro AMPLIO por 'shape':
    - misma longitud/espacios
    - respeta letras reveladas (pero NO aplica la regla de “no repetidas”)
    - excluye letras fallidas
    """
    cand = candidate.upper()
    patt = raw_game_word.upper()
    if len(cand) != len(patt):
        return False

    for pc, cc in zip(patt, cand):
        if pc == " ":
            if cc != " ":
                return False
        elif pc == "_":
            if cc == " ":
                return False
        elif pc.isalpha():
            if cc != pc:
                return False
        else:
            if cc != pc:
                return False

    if wrong_letters:
        for bad in wrong_letters:
            if bad in cand:
                return False

    return True

def find_word(soup: BeautifulSoup, html: str) -> str | None:
    span = soup.find("span", attrs={"style": lambda s: s and "letter-spacing" in s.lower()})
    if span:
        t = normalize_text(span.get_text(strip=True)).upper()
        if t and re.fullmatch(r"[A-Z_ ]+", t):
            return t
    center = soup.find("center")
    if center:
        sp2 = center.find("span")
        if sp2:
            t = normalize_text(sp2.get_text(strip=True)).upper()
            if t and re.fullmatch(r"[A-Z_ ]+", t):
                return t
    for sp in soup.select("#textbar span"):
        t = normalize_text(sp.get_text(strip=True)).upper()
        if "_" in t and re.fullmatch(r"[A-Z_ ]+", t):
            return t
    m = re.search(r"<span[^>]*>([A-Za-z_ \u00A0]{3,})</span>", html, re.I)
    if m:
        t = normalize_text(m.group(1)).upper()
        if "_" in t and re.fullmatch(r"[A-Z_ ]+", t):
            return t
    plain = normalize_text(soup.get_text(" ", strip=True)).upper()
    for m2 in re.finditer(r"[A-Z_ ]{3,}", plain):
        t = m2.group(0)
        if "_" in t and re.fullmatch(r"[A-Z_ ]+", t):
            return t
    return None

def is_instruction_banner_text(text_upper: str) -> bool:
    return ("INSTRUCTIONS" in text_upper and "HANGMAN GAME" in text_upper and "RANDOMLY SELECTS" in text_upper)

def grab_metrics(soup: BeautifulSoup) -> tuple[str, str, str]:
    txt = normalize_text(soup.get_text(" ", strip=True))
    def rx(label):
        m = re.search(rf"{re.escape(label)}:\s*(\d+)", txt, re.I)
        return m.group(1) if m else "?"
    return rx("Solved Hangmen in a row"), rx("Correct Guesses"), rx("Lives left")

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
    if raw_word:
        print(f"Word: {spaced(raw_word)} ")
    else:
        center = soup.find("center")
        approx = normalize_text(center.get_text(" ", strip=True)).upper() if center else "(vacío)"
        print(f"Word: {spaced(approx)} (palabra no encontrada) ")
    print(f"Solved Hangmen in a row: {solved}")
    print(f"Correct Guesses: {correct}")
    print(f"Lives left: {lives}")
    return solved, correct, lives

def round_finished(raw_word: str | None, lives: str | None) -> bool:
    if raw_word and "_" not in raw_word:
        return True
    try:
        return int(lives) <= 0
    except (TypeError, ValueError):
        return False

def auto_refresh_until_word(sess: requests.Session, cookies: dict, interval=2, max_tries=60):
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
    counter = Counter()
    for w in candidates:
        letters = {ch for ch in w.upper() if "A" <= ch <= "Z"}
        for ch in letters:
            if ch not in used_letters:
                counter[ch] += 1
    return sorted(counter.items(), key=lambda x: (-x[1], x[0]))

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
        import select, sys as _sys
        rlist, _, _ = select.select([_sys.stdin], [], [], timeout)
        if rlist:
            line = _sys.stdin.readline()
            return line.rstrip("\n")
        else:
            print()
            return ""

def auto_guess_letters(sess, cookies, next_letters):
    """Envía una secuencia de letras (iterable) con pequeñas pausas."""
    for ch in next_letters:
        html = request_page(sess, cookies, ch)
        soup = BeautifulSoup(html, "html.parser")
        raw_word = find_word(soup, html)
        print_state(raw_word, soup)
        _, _, lives = grab_metrics(soup)
        time.sleep(AUTO_GUESS_SLEEP_SEC)
        if round_finished(raw_word, lives):
            return raw_word, soup
    return raw_word, soup

def auto_guess_loop(sess, cookies, wordlist, soup, raw_word, used, wrong):
    """
    Con candidatas: intentar letras más frecuentes (excluyendo usadas).
    """
    tries = 0
    while AUTO_GUESS_WHEN_CANDIDATES and tries < AUTO_GUESS_MAX_PER_ROUND:
        strict = [w for w in wordlist if matches_pattern(w, raw_word, wrong_letters=wrong)]
        if strict:
            base = strict
        else:
            # si estricto=0, usar AMPLIO por shape antes de decir "sin candidatas"
            loose = [w for w in wordlist if matches_shape_loose(w, raw_word, wrong_letters=wrong)]
            if not loose:
                break
            print(f"\nℹ️ Candidatas estrictas: 0 → usando filtro amplio por shape ({len(loose)})")
            base = loose

        ranking = rank_letters(base, used_letters=used)
        if not ranking:
            break
        next_letter = ranking[0][0]
        print(f"\n🤖 Auto: probando {next_letter} (top entre {len(base)} candidatas)")
        html = request_page(sess, cookies, next_letter)
        soup = BeautifulSoup(html, "html.parser")
        raw_word = find_word(soup, html)
        print_state(raw_word, soup)
        used, wrong = extract_used_and_wrong_letters(soup, raw_word)

        if raw_word and "_" not in raw_word:
            word_upper = raw_word.upper().strip()
            bank = load_wordlist(WORDLIST_PATH)
            if word_upper not in [w.upper() for w in bank]:
                with WORDLIST_PATH.open("a", encoding="utf-8") as f:
                    f.write(word_upper + "\n")
                print(f"\n✅ Palabra agregada al banco: {word_upper}")

        _, _, lives = grab_metrics(soup)
        if round_finished(raw_word, lives):
            break
        tries += 1
        time.sleep(AUTO_GUESS_SLEEP_SEC)
    return raw_word, soup

def fallback_guess_loop(sess, cookies, soup, raw_word, used, wrong):
    """
    Sin candidatas (estricto y amplio): probar letras por frecuencia en inglés.
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
            bank = load_wordlist(WORDLIST_PATH)
            if word_upper not in [w.upper() for w in bank]:
                with WORDLIST_PATH.open("a", encoding="utf-8") as f:
                    f.write(word_upper + "\n")
                print(f"\n✅ Palabra agregada al banco: {word_upper}")
        _, _, lives = grab_metrics(soup)
        if round_finished(raw_word, lives):
            break
        tries += 1
        time.sleep(FALLBACK_SLEEP_SEC)
    return raw_word, soup

def main():
    cookies = cookies_from_string(COOKIE_STRING)
    wordlist = load_wordlist(WORDLIST_PATH)

    with requests.Session() as sess:
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

            if not raw_word and AUTO_REFRESH_ON_FALLBACK:
                print("\n🔄 No se encontró la palabra. Autorefrescando… (Ctrl+C para cortar)")
                try:
                    raw_word, soup = auto_refresh_until_word(
                        sess, cookies, interval=REFRESH_INTERVAL_SEC, max_tries=MAX_REFRESH_TRIES
                    )
                except KeyboardInterrupt:
                    print("\n⏹ Autorefresco cancelado por el usuario.")
                print_state(raw_word, soup)
            else:
                print()
                print_state(raw_word, soup)

            used, wrong = extract_used_and_wrong_letters(soup, raw_word)
            print("Letras fallidas:", " ".join(sorted(wrong)) if wrong else "-")

            if raw_word:
                # Candidatas: primero ESTRICTO; si 0 → AMPLIO por shape
                strict = [w for w in wordlist if matches_pattern(w, raw_word, wrong_letters=wrong)]
                if strict:
                    print(f"\nCandidatas ({len(strict)}):")
                    for w in strict:
                        print(f"- {w}")
                    ranked = rank_letters(strict, used_letters=used)
                    if ranked:
                        print("\nLetras por frecuencia (excluyendo intentadas):")
                        print(" ".join(f"{ltr}:{cnt}" for ltr, cnt in ranked[:15]))
                    if AUTO_GUESS_WHEN_CANDIDATES:
                        raw_word, soup = auto_guess_loop(sess, cookies, wordlist, soup, raw_word, used, wrong)
                else:
                    loose = [w for w in wordlist if matches_shape_loose(w, raw_word, wrong_letters=wrong)]
                    if loose:
                        print(f"\nℹ️ Candidatas estrictas: 0 → usando filtro amplio por shape ({len(loose)}):")
                        for w in loose:
                            print(f"- {w}")
                        ranked = rank_letters(loose, used_letters=used)
                        if ranked:
                            print("\nLetras por frecuencia (excluyendo intentadas):")
                            print(" ".join(f"{ltr}:{cnt}" for ltr, cnt in ranked[:15]))
                        if AUTO_GUESS_WHEN_CANDIDATES:
                            raw_word, soup = auto_guess_loop(sess, cookies, wordlist, soup, raw_word, used, wrong)
                    else:
                        print("\nCandidatas (0): (ninguna con ese patrón en el banco)")
                        if FALLBACK_GUESS_WHEN_NO_CANDIDATES:
                            raw_word, soup = fallback_guess_loop(sess, cookies, soup, raw_word, used, wrong)

                # Guardar si quedó completa
                if raw_word and "_" not in raw_word:
                    word_upper = raw_word.upper().strip()
                    if word_upper not in [w.upper() for w in wordlist]:
                        with WORDLIST_PATH.open("a", encoding="utf-8") as f:
                            f.write(word_upper + "\n")
                        wordlist.append(word_upper)
                        print(f"\n✅ Palabra agregada al banco: {word_upper}")
                    else:
                        print(f"\nℹ️ Palabra ya estaba en el banco: {word_upper}")

            _, _, lives = grab_metrics(soup)
            if round_finished(raw_word, lives):
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

if __name__ == "__main__":
    main()
