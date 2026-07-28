#!/usr/bin/env python3
"""Radar de presse : les titres parus depuis le brief precedent, dates.

Pourquoi. Mesure faite le 28/07/2026, l'outillage du brief tient en huit secondes
et le temps part dans la recherche. Or une partie de cette recherche est
mecanique : savoir CE QUI est paru depuis hier. Ce script s'en charge et rend une
liste de candidats horodates, a partir de laquelle il reste a choisir, lire et
citer.

Ce qu'il ne fait pas, volontairement. Il n'ecrit rien dans le brief. Un titre n'est
pas une source : la puce se redige apres avoir lu l'article, et c'est l'article qui
est cite. Le radar remplace la question « qu'est-ce qui est sorti ? », pas le
travail de lecture.

Flux retenus : ceux de CNBC, verifies accessibles et horodates au format RSS
standard. Boursorama et ABC Bourse n'exposent pas de flux a l'adresse attendue —
404 sur les deux — donc la presse francophone reste a chercher par requete.

Usage :
    py news_radar.py              titres depuis la publication du brief precedent
    py news_radar.py --heures 18  fenetre explicite
    py news_radar.py --tout       sans filtre de date
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import io
import json
import os
import re
import sys
import urllib.request

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
NEWS = os.path.join(ROOT, "news")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
TIMEOUT = 40

# Un flux par rubrique du brief, pour que les candidats arrivent deja tries selon
# la structure a remplir. CNBC uniquement : ce sont les seuls flux du lot autorise
# qui repondent et qui horodatent.
FLUX = [
    ("marchés",     "https://www.cnbc.com/id/15839135/device/rss/rss.html"),
    ("macro",       "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("finance",     "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("entreprises", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
    ("technologie", "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("énergie",     "https://www.cnbc.com/id/19836768/device/rss/rss.html"),
]

RESET, DIM, BOLD, YELLOW = "\033[0m", "\033[2m", "\033[1m", "\033[33m"

# Mots qui font remonter un titre en tete : ce sont les faits qui ouvrent un brief.
SAILLANTS = re.compile(
    r"\b(fed|ecb|boj|boe|rate|inflation|cpi|pce|tariff|opec|oil|crude|"
    r"earnings|profit|loss|guidance|beats|misses|layoff|merger|acquisition|"
    r"strike|sanction|ceasefire|iran|hormuz|chip|semiconductor|selloff|rally|"
    r"yields|treasury|recession|jobs|unemployment)\b", re.I)


def _texte(motif: str, bloc: str) -> str:
    m = re.search(motif, bloc, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).replace("]]>", "").strip()


def flux(url: str) -> list[dict]:
    brut = urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=TIMEOUT
    ).read().decode("utf-8", "replace")
    articles = []
    for bloc in re.findall(r"<item>(.*?)</item>", brut, re.S):
        titre = _texte(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", bloc)
        lien = _texte(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", bloc)
        pub = _texte(r"<pubDate>(.*?)</pubDate>", bloc)
        quand = None
        if pub:
            try:
                quand = email.utils.parsedate_to_datetime(pub)
                if quand.tzinfo is None:
                    quand = quand.replace(tzinfo=dt.timezone.utc)
            except (TypeError, ValueError):
                quand = None
        if titre and lien:
            articles.append({"titre": titre.replace("&apos;", "'")
                                          .replace("&amp;", "&"),
                             "url": lien, "quand": quand})
    return articles


def depuis_brief_precedent() -> dt.datetime | None:
    """`generated_at` du brief le plus recent : la fenetre d'actualite commence la,
    exactement comme le veut la specification."""
    idx = os.path.join(NEWS, "index.json")
    if not os.path.exists(idx):
        return None
    dates = json.load(open(idx, encoding="utf-8")).get("dates") or []
    aujourdhui = dt.date.today().isoformat()
    for d in dates:
        if d == aujourdhui:
            continue                       # le brief du jour n'est pas une borne
        chemin = os.path.join(NEWS, f"brief-{d}.json")
        if not os.path.exists(chemin):
            continue
        gen = json.load(open(chemin, encoding="utf-8")).get("generated_at")
        try:
            return dt.datetime.fromisoformat((gen or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--heures", type=float,
                   help="fenetre en heures au lieu de la borne du brief precedent")
    p.add_argument("--tout", action="store_true", help="aucun filtre de date")
    a = p.parse_args()

    maintenant = dt.datetime.now(dt.timezone.utc)
    if a.tout:
        borne, origine = None, "aucun filtre"
    elif a.heures:
        borne = maintenant - dt.timedelta(hours=a.heures)
        origine = f"{a.heures:g} h"
    else:
        borne = depuis_brief_precedent()
        origine = "publication du brief précédent"
        if borne is None:
            borne = maintenant - dt.timedelta(hours=24)
            origine = "24 h (brief précédent introuvable)"

    print(f"{BOLD}Radar de presse{RESET} — fenêtre : {origine}"
          + (f", depuis {borne:%d/%m %H:%M} UTC" if borne else ""))

    total = retenus = 0
    for rubrique, url in FLUX:
        try:
            articles = flux(url)
        except Exception as exc:                       # noqa: BLE001
            print(f"  {YELLOW}échec {rubrique} : {type(exc).__name__}{RESET}")
            continue
        total += len(articles)
        frais = [x for x in articles
                 if borne is None or (x["quand"] and x["quand"] >= borne)]
        # Les titres portant un mot saillant d'abord : ce sont ceux qui ouvrent un
        # brief. Le reste suit, du plus recent au plus ancien.
        frais.sort(key=lambda x: (0 if SAILLANTS.search(x["titre"]) else 1,
                                  -(x["quand"] or borne or maintenant).timestamp()))
        if not frais:
            continue
        retenus += len(frais)
        print()
        print(f"{BOLD}{rubrique}{RESET} {DIM}({len(frais)} sur {len(articles)}){RESET}")
        for x in frais:
            heure = f"{x['quand']:%d/%m %H:%M}" if x["quand"] else "sans date"
            marque = "*" if SAILLANTS.search(x["titre"]) else " "
            print(f"  {marque} {DIM}{heure}{RESET}  {x['titre'][:96]}")
            print(f"      {DIM}{x['url'][:110]}{RESET}")

    print()
    print(f"{retenus} titre(s) dans la fenêtre sur {total} relevé(s). "
          f"{DIM}Les « * » portent un mot saillant.{RESET}")
    print(f"{DIM}Un titre n'est pas une source : lire l'article avant de citer, "
          f"et citer l'article.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
