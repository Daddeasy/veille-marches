#!/usr/bin/env python3
"""Verifie la date de publication reelle de chaque article cite par le brief.

Pourquoi ce script existe : le brief a un jour cite, pour la seance du 24 juillet,
un article du 17 juillet et un autre du 25 decembre precedent. Les deux etaient
precisement ceux dont l'URL ne portait pas de date. La regle « preferer un article
recent » ne suffit pas — il faut un controle.

La date de publication figure dans les metadonnees de presque toutes les pages de
presse, sous une forme lisible par machine : JSON-LD `datePublished`, ou balise
Open Graph `article:published_time`. C'est la seule source fiable, car ni l'URL
ni le titre ne distinguent publication et mise a jour — un suivi en continu porte
dans son URL la date de sa creation, pas celle de son contenu.

Trois verdicts :
  OK          date confirmee dans la fenetre couverte
  HORS        date confirmee mais anterieure a la fenetre -> a retirer
  INVERIFIE   page inaccessible au robot ; le champ date_unverified doit alors
              etre present dans le JSON, pour que le site le signale au lecteur

Usage :
    py brief_check.py                  verifie le brief le plus recent
    py brief_check.py 2026-07-24       verifie un brief precis
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/120"}
TIMEOUT = 30

# Tolerance amont : un article de contexte de la veille reste acceptable.
WINDOW_DAYS_BEFORE = 2

PATTERNS = [
    r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})',
    r'property="article:published_time"[^>]*content="(\d{4}-\d{2}-\d{2})',
    r'content="(\d{4}-\d{2}-\d{2})[^"]*"[^>]*property="article:published_time"',
    r'<meta[^>]*name="date"[^>]*content="(\d{4}-\d{2}-\d{2})',
]


def date_in_url(url: str) -> str | None:
    """Date portee par l'URL elle-meme : bloomberg.com/news/articles/2026-07-24/,
    cnbc.com/2026/07/23/, axios.com/2026/07/21/.

    Sert quand la page est inaccessible au robot : on ne fait alors pas confiance
    a la date DECLAREE dans le JSON, on la confronte a l'URL. Ce n'est probant que
    pour un article fige — un suivi en continu porte la date de sa creation.
    """
    m = re.search(r'/(\d{4})[-/](\d{2})[-/](\d{2})/', url)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def real_date(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        html = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode(
            "utf-8", "replace")
    except Exception:                                  # noqa: BLE001
        return None
    for pattern in PATTERNS:
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    return None


def check_factset(brief: dict) -> list[str]:
    """Coherence de l'encart FactSet Earnings Insight.

    Le document est hebdomadaire et repris a l'identique toute la semaine : rien
    dans le texte ne signale qu'il vieillit. Trois verifications suffisent a
    l'empecher de deriver — as_of anterieure au brief, nom du PDF cite conforme a
    as_of, et age inferieur a huit jours, delai au-dela duquel le vendredi suivant
    est passe sans qu'on ait releve le nouveau fichier.
    """
    fs = brief.get("factset")
    if not fs:
        print("factset : encart absent de ce brief.")
        return []

    problems: list[str] = []
    as_of = fs.get("as_of")
    try:
        d = dt.date.fromisoformat(as_of)
    except (TypeError, ValueError):
        print(f"factset : as_of illisible ({as_of!r})")
        return ["factset / as_of absente ou illisible"]

    age = (dt.date.fromisoformat(brief["date"]) - d).days
    # Nom de fichier FactSet : EarningsInsight_MMJJAA.pdf, date americaine.
    expected = d.strftime("%m%d%y")
    in_url = re.search(r"EarningsInsight_(\d{6})\.pdf", fs.get("url", "") or "")

    print(f"factset : as_of {as_of} ({age} j), {len(fs.get('metrics') or [])} metriques")
    if age < 0:
        problems.append(f"factset / as_of {as_of} posterieure au brief")
    if age > 8:
        problems.append(f"factset / as_of {as_of} vieille de {age} j, relever le PDF du vendredi")
    if not fs.get("metrics"):
        problems.append("factset / aucune metrique")
    if in_url and in_url.group(1) != expected:
        problems.append(f"factset / le PDF cite est celui du {in_url.group(1)}, "
                        f"as_of annonce {expected}")
    elif not in_url:
        problems.append("factset / url absente ou hors motif EarningsInsight_MMJJAA.pdf")
    return problems


def main() -> int:
    news = os.path.join(ROOT, "news")
    if len(sys.argv) > 1:
        stem = sys.argv[1]
    else:
        idx = json.load(open(os.path.join(news, "index.json"), encoding="utf-8"))
        if not idx.get("dates"):
            print("brief_check : aucun brief publie.")
            return 0
        stem = idx["dates"][0]

    path = os.path.join(news, f"brief-{stem}.json")
    if not os.path.exists(path):
        print(f"brief_check : {path} absent.")
        return 1
    brief = json.load(open(path, encoding="utf-8"))

    session = brief.get("session") or brief["date"]
    floor = dt.date.fromisoformat(session) - dt.timedelta(days=WINDOW_DAYS_BEFORE)
    ceil = dt.date.fromisoformat(brief["date"])

    print(f"brief du {brief['date']} — seance {session}")
    print(f"fenetre acceptee : {floor} a {ceil}\n")
    print(f"{'RUBRIQUE':<12}{'SOURCE':<22}{'DECLARE':<12}{'REEL':<12}VERDICT")
    print("-" * 74)

    out_of_window: list[str] = []
    unverified_undeclared: list[str] = []
    mismatch: list[str] = []

    for section, items in brief.get("sections", {}).items():
        for item in items:
            url = item.get("url", "")
            declared = item.get("published")
            found = real_date(url)

            if found is None:
                # Page inaccessible : on se rabat sur la date portee par l'URL,
                # en verifiant qu'elle confirme bien ce que le JSON declare.
                from_url = date_in_url(url)
                if from_url and declared == from_url:
                    found = from_url
                    d = dt.date.fromisoformat(found)
                    verdict = "OK (url)" if floor <= d <= ceil else ">>> HORS FENETRE (url)"
                    if not (floor <= d <= ceil):
                        out_of_window.append(f"{section} / {item['source']} ({found})")
                elif from_url and declared != from_url:
                    verdict = f">>> URL indique {from_url}"
                    mismatch.append(f"{section} / {item['source']}")
                else:
                    verdict = "INVERIFIE"
                    if not item.get("date_unverified"):
                        verdict += "  <<< champ date_unverified manquant"
                        unverified_undeclared.append(f"{section} / {item['source']}")
            else:
                d = dt.date.fromisoformat(found)
                if floor <= d <= ceil:
                    verdict = "OK"
                else:
                    verdict = ">>> HORS FENETRE"
                    out_of_window.append(f"{section} / {item['source']} ({found})")
                if declared and declared != found:
                    verdict += f"  (declare {declared})"
                    mismatch.append(f"{section} / {item['source']}")

            print(f"{section:<12}{item['source'][:20]:<22}"
                  f"{str(declared or '—'):<12}{str(found or '—'):<12}{verdict}")

    print()
    factset_problems = check_factset(brief)
    print()
    if factset_problems:
        print(f"{len(factset_problems)} probleme(s) sur l'encart FactSet :")
        for x in factset_problems:
            print(f"  {x}")
    if out_of_window:
        print(f"{len(out_of_window)} article(s) HORS FENETRE, a retirer du brief :")
        for x in out_of_window:
            print(f"  {x}")
    if mismatch:
        print(f"{len(mismatch)} date(s) declaree(s) fausse(s) :")
        for x in mismatch:
            print(f"  {x}")
    if unverified_undeclared:
        print(f"{len(unverified_undeclared)} page(s) invérifiable(s) sans le champ "
              f"date_unverified :")
        for x in unverified_undeclared:
            print(f"  {x}")

    if out_of_window or mismatch or unverified_undeclared or factset_problems:
        return 1
    print("Toutes les dates d'article sont coherentes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
