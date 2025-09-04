import requests
from bs4 import BeautifulSoup
import re

# --- CONFIG --- 
COOKIES = {
    # "PHPSESSID": "tu_valor",
}

COOKIE_STRING = "PHPSESSID=pdnh5fl1jvn139c0l0rglmug7s; _gcl_au=1.1.1884119554.1756846145.1072503122.1756846377.1756846377; username=L183R; password=6299ad21b8644aa31efb9e2ed4d660160c5480d44dac3f9a090179086e8db991b39e11d5f4b959a13df5f863aebaba997753ef0392427a3c519b48f425b1f6e8; friendbar_hide=hide"

def cookies_from_string(s: str) -> dict:
    d = {}
    for part in [p.strip() for p in s.split(";") if p.strip()]:
        if "=" in part:
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
    return d

def main():
    url = "https://pokeheroes.com/gc_hangman"
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "es-ES,es;q=0.9,en;q=0.8",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "referer": "https://pokeheroes.com/gc_hangman?",
        "x-requested-with": "XMLHttpRequest",
    }

    cookies = COOKIES if COOKIES else cookies_from_string(COOKIE_STRING)

    with requests.Session() as s:
        data = {"guess": "E"}
        r = s.post(url, headers=headers, cookies=cookies, data=data, timeout=30)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        # Buscamos el span que tiene el patrón del ahorcado
        span = soup.find("span", attrs={"style": lambda s: s and "letter-spacing" in s})
        if not span:
            # fallback: intentar con GET
            r2 = s.get(url, params={"guess": "A"}, headers=headers, cookies=cookies, timeout=30)
            soup = BeautifulSoup(r2.text, "html.parser")
            span = soup.find("span", attrs={"style": lambda s: s and "letter-spacing" in s})

        if span:
            palabra = span.get_text(strip=True)
            separado = " ".join(list(palabra))
            print(separado)   # => _ _ _ _ _ _ E
        else:
            print("No se encontró la palabra del ahorcado. ¿Sesión/logueo OK?")

if __name__ == "__main__":
    main()
