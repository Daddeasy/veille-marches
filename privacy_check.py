#!/usr/bin/env python3
"""Garde-fou : interdit toute donnee personnelle dans le depot public.

Le depot est public et le brief est redige chaque matin par un agent qui lit la
presse. Rien n'empeche structurellement un nom, une adresse ou un telephone de
se retrouver recopie depuis un article. Ce script transforme ce risque en echec
de build.

Deux niveaux de detection :

  1. MOTIFS STRUCTURELS, en dur ici — adresses e-mail, numeros de telephone,
     chemins de repertoire personnel, IBAN. Ils ne nomment personne, donc les
     ecrire dans le code n'expose rien.

  2. TERMES NOMINATIFS, lus depuis la variable d'environnement PRIVACY_DENYLIST
     (valeurs separees par des virgules). C'est deliberé : inscrire « Untel » ou
     le nom d'une societe dans ce fichier exposerait precisement ce que l'on
     cherche a cacher. La liste vit dans un secret GitHub, jamais dans le depot.

Usage :
    py privacy_check.py
    PRIVACY_DENYLIST="Nom,Societe" py privacy_check.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

# Motifs structurels. Aucun ne nomme quiconque.
PATTERNS: list[tuple[str, str]] = [
    ("adresse e-mail",
     r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ("telephone francais",
     r"(?<![\d.])(?:\+33|0)\s?[1-9](?:[\s.\-]?\d{2}){4}(?![\d.])"),
    ("telephone international",
     r"\+\d{1,3}[\s.\-]?\(?\d{2,4}\)?(?:[\s.\-]?\d{2,4}){2,}"),
    ("chemin personnel Windows",
     r"[A-Za-z]:\\+Users\\+[^\\\s\"']+"),
    ("chemin personnel Unix",
     r"/(?:home|Users)/[A-Za-z0-9._-]+"),
    ("IBAN", r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}\b"),
]

# Faux positifs legitimes, a exclure ligne par ligne.
ALLOW = re.compile(
    r"noreply|users\.noreply|github-actions\[bot\]|"
    r"example\.(com|org)|"
    r"presse@banque-france\.fr|"          # adresse publique citee en doc
    r"SUPPORT-TECHNIQUE-WEBSTAT",
    re.I,
)

# Fichiers a ne pas inspecter (binaires, donnees de marche pures).
SKIP_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".msg", ".xlsx")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    if out.returncode != 0:
        print("privacy_check : pas un depot git, rien a verifier.")
        return []
    return [f for f in out.stdout.splitlines()
            if f and not f.lower().endswith(SKIP_SUFFIX)]


def denylist() -> list[str]:
    raw = os.environ.get("PRIVACY_DENYLIST", "")
    return [t.strip() for t in raw.split(",") if len(t.strip()) >= 3]


def scan() -> list[str]:
    hits: list[str] = []
    terms = denylist()

    for path in tracked_files():
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue

        for n, line in enumerate(lines, 1):
            if ALLOW.search(line):
                continue
            for label, pattern in PATTERNS:
                m = re.search(pattern, line)
                if m:
                    hits.append(f"{path}:{n} — {label} : {m.group(0)[:40]}")
            for term in terms:
                if term.lower() in line.lower():
                    # N'affiche PAS le terme trouve : le journal d'execution
                    # d'un workflow public serait sinon une fuite a son tour.
                    hits.append(f"{path}:{n} — terme interdit (liste privee)")
    return hits


def check_history() -> list[str]:
    """L'auteur d'un commit est visible publiquement, et un rebase ne l'efface
    pas d'un depot deja pousse. Verifie avant qu'il ne soit trop tard."""
    out = subprocess.run(
        ["git", "log", "--format=%H|%an|%ae|%cn|%ce|%s"],
        capture_output=True, text=True)
    if out.returncode != 0:
        return []
    hits = []
    terms = denylist()
    for line in out.stdout.splitlines():
        if ALLOW.search(line):
            continue
        sha = line.split("|", 1)[0][:8]
        for label, pattern in PATTERNS:
            if re.search(pattern, line):
                hits.append(f"commit {sha} — {label} dans l'auteur ou le message")
                break
        for term in terms:
            if term.lower() in line.lower():
                hits.append(f"commit {sha} — terme interdit (liste privee)")
                break
    return hits


def main() -> int:
    hits = scan() + check_history()
    n_terms = len(denylist())

    print(f"privacy_check : {len(tracked_files())} fichiers, "
          f"{len(PATTERNS)} motifs structurels, "
          f"{n_terms} terme(s) nominatif(s) depuis PRIVACY_DENYLIST")
    if not n_terms:
        print("  note : PRIVACY_DENYLIST non definie — seuls les motifs "
              "structurels sont verifies.")

    if hits:
        print(f"\n{len(hits)} probleme(s) de confidentialite :")
        for h in hits:
            print(f"  {h}")
        print("\nCorriger avant de pousser. Un depot public deja pousse garde "
              "une trace meme apres correction.")
        return 1

    print("Aucune donnee personnelle detectee.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
