#!/usr/bin/env python3
"""Remove duplicate or blank entries from hangman_words.txt."""
from pathlib import Path

WORDLIST = Path("hangman_words.txt")

def main() -> None:
    seen: set[str] = set()
    cleaned: list[str] = []
    for line in WORDLIST.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if not word:
            continue  # skip blank lines
        upper = word.upper()
        if upper not in seen:
            seen.add(upper)
            cleaned.append(upper)
    WORDLIST.write_text("\n".join(cleaned) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
