#!/usr/bin/env python3
"""Verifie que latest.json contient bien tout ce que index.html lit.

Une incoherence de forme entre le pipeline et l'app est le defaut le plus
probable et le plus silencieux : la page s'affiche, mais des tuiles restent
vides sans qu'aucune erreur ne soit levee. Ce script transforme ce risque en
echec explicite.

Usage :  py selfcheck.py
"""

import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# Groupes declares dans index.html — doivent couvrir tous les instruments.
GROUPS = {
    "Actions": ["S&P 500", "Nasdaq 100", "CAC 40", "Euro Stoxx 50", "Nikkei 225",
                "Shanghai Comp.", "KOSPI"],
    "Change": ["EUR/USD"],
    "Taux": ["10Y US", "10Y France"],
    "Volatilité & sentiment": ["VIX", "Fear & Greed crypto"],
    "Matières & crypto": ["Or", "Brent", "Bitcoin"],
}

REQUIRED = ["level", "date", "unit", "dec", "source", "basis", "target_date"]
VALID_UNITS = {"pct", "bp", "pts"}

problems: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def main() -> int:
    path = os.path.join(ROOT, "latest.json")
    if not os.path.exists(path):
        print("latest.json absent — lancer d'abord market_prices.py")
        return 1

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    for key in ("date", "generated_at", "markets", "diagnostics"):
        if key not in data:
            fail(f"cle racine manquante : {key}")
    markets = data.get("markets", {})
    if not markets:
        fail("markets vide")
        print("\n".join(problems))
        return 1

    # 1. Couverture : chaque instrument doit etre dans un groupe de l'app,
    #    sinon il tombe dans "Autres" et l'ordre d'affichage part en vrac.
    declared = {label for labels in GROUPS.values() for label in labels}
    for label in markets:
        if label not in declared:
            warn(f"{label} n'est dans aucun groupe de index.html → ira dans 'Autres'")
    for label in declared:
        if label not in markets:
            fail(f"index.html attend '{label}' mais le pipeline ne le produit pas")

    # 2. Champs et coherence par instrument
    for label, e in markets.items():
        if "error" in e:
            warn(f"{label} en erreur : {e['error'][:60]}")
            continue

        for key in REQUIRED:
            if key not in e:
                fail(f"{label} : champ '{key}' manquant")

        if e.get("unit") not in VALID_UNITS:
            fail(f"{label} : unit='{e.get('unit')}' inconnu de index.html")

        if not isinstance(e.get("dec"), int) or not 0 <= e["dec"] <= 6:
            fail(f"{label} : dec invalide ({e.get('dec')!r})")

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.get("date", "")):
            fail(f"{label} : date mal formee ({e.get('date')!r})")

        # Les taux ne doivent PAS porter de pourcentage : afficher "+1,56 %"
        # sur un rendement au lieu de "+5 bp" est une faute de lecture.
        if e.get("unit") in ("bp", "pts") and e.get("pct") is not None:
            fail(f"{label} : unit={e['unit']} mais pct={e['pct']} est renseigne")

        # Coherence de la variation avec change_from
        if e.get("change") is not None:
            if "change_from" not in e or "change_days" not in e:
                fail(f"{label} : change sans change_from/change_days")
            elif e["change_days"] < 0:
                fail(f"{label} : change_days negatif ({e['change_days']})")

        # Bornes 52 semaines coherentes avec le niveau
        if "hi52" in e and "lo52" in e:
            if not (e["lo52"] <= e["level"] <= e["hi52"]):
                fail(f"{label} : level {e['level']} hors bornes "
                     f"[{e['lo52']}, {e['hi52']}]")

        if e.get("pctile_1y") is not None and not 0 <= e["pctile_1y"] <= 100:
            fail(f"{label} : pctile_1y hors [0,100] ({e['pctile_1y']})")

    # 3. Vue en euros : presente sur les actifs libelles en dollars
    # Perimetre sans EUR/USD : plus de conversion en euros, les actifs en
    # dollars restent en dollars. Rien a verifier ici.

    # 4. La date de reference doit exister parmi les instruments et ne pas
    #    provenir d'un marche ouvert le week-end.
    ref = data.get("date")
    dates = {e["date"] for e in markets.values()
             if "date" in e and not e.get("traded_247")}
    if ref not in dates:
        fail(f"date racine {ref} ne correspond a aucune cloture de marche ferme")

    # 5. Alignement : c'est ce qui garantit la coherence entre le brief presse
    #    et les chiffres. Un instrument marque on_target ne doit pas porter une
    #    date anterieure a la cible, sinon le brief ecrira "hier" a tort.
    diag = data.get("diagnostics", {})
    target = diag.get("target_date") or data.get("target_date")
    if not target:
        fail("diagnostics.target_date absent — le brief ne peut pas verifier l'alignement")
    else:
        for label, e in markets.items():
            if "error" in e or e.get("on_target") is None:
                continue
            own, tgt = e["date"], e.get("target_date", target)
            if e.get("on_target") and own < tgt:
                fail(f"{label} : on_target=true mais {own} < cible {tgt}")
            if e.get("on_target") is False and own >= tgt:
                fail(f"{label} : on_target=false mais {own} >= cible {tgt}")
        declared_off = {t[0] for t in diag.get("off_target", [])}
        actual_off = {k for k, v in markets.items() if v.get("on_target") is False}
        if declared_off != actual_off:
            fail(f"diagnostics.off_target incoherent : {declared_off ^ actual_off}")
        n_off = len(actual_off)
        if n_off:
            warn(f"{n_off} instrument(s) pas encore sur la seance du {target} : "
                 + ", ".join(sorted(actual_off)))

    # 6. series.csv : coherence avec latest.json
    csv_path = os.path.join(ROOT, "series.csv")
    if os.path.exists(csv_path):
        import csv as _csv
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = list(_csv.DictReader(fh))
        keys = {(r["date"], r["instrument"]) for r in rows}
        for label, e in markets.items():
            if "date" in e and (e["date"], label) not in keys:
                fail(f"series.csv : ligne manquante pour {label} au {e['date']}")
        dupes = len(rows) - len(keys)
        if dupes:
            fail(f"series.csv : {dupes} doublons (date, instrument)")
    else:
        warn("series.csv absent")

    # ------------------------------------------------------------- rapport ---
    print(f"Instruments : {len(markets)}   "
          f"ok : {data['diagnostics'].get('ok')}   "
          f"date de reference : {ref}")

    for w in warnings:
        print(f"  avertissement  {w}")
    for p in problems:
        print(f"  ERREUR         {p}")

    if problems:
        print(f"\n{len(problems)} incoherence(s) entre le pipeline et l'app.")
        return 1
    print(f"\nCoherent. {len(warnings)} avertissement(s), aucune incoherence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
