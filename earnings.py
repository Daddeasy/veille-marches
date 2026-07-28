#!/usr/bin/env python3
"""Calendrier des publications de resultats, pour la rubrique micro du brief.

Ce que la rubrique micro n'avait pas : qui publie, quel jour, et avant l'ouverture
ou apres la cloture. C'est l'information la plus utile du bloc — un resultat tombe
apres la cloture de New York se lit sur la seance du lendemain, pas sur celle du
jour, et le brief doit pouvoir le dire sans que le redacteur aille le chercher.

Source retenue : le calendrier du Nasdaq, `api.nasdaq.com/api/calendar/earnings`.
JSON public, sans inscription, et surtout il porte le champ `time` avec les valeurs
`time-pre-market` et `time-after-hours` — le seul flux gratuit identifie qui donne
le creneau. Les autres pistes examinees demandaient une cle (Finnhub, FMP) ou ne
publiaient pas le creneau.

Limite a dire clairement : ce calendrier couvre les societes **cotees aux
Etats-Unis**. LVMH, Safran ou Orange n'y figurent pas. Pour l'Europe, l'agenda de
presse reste la source, et le brief le mentionne.

Filtrage. Sans lui le bloc est illisible : 149 societes le 28/07/2026, 291 le
lendemain. Deux bornes, une de capitalisation et un plafond par jour, qui gardent
les noms dont le marche parle.

Usage :
    py earnings.py                 ecrit dans le brief du jour
    py earnings.py 2026-07-28      ecrit dans un brief precis
    py earnings.py --dry-run       affiche sans ecrire
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys
import urllib.request

# La console Windows est en cp1252 et ne sait pas ecrire le signe moins
# typographique employe par les montants negatifs : le script plantait a
# l'affichage apres avoir correctement collecte.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
NEWS = os.path.join(ROOT, "news")

API = "https://api.nasdaq.com/api/calendar/earnings?date={}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
      "Accept": "application/json"}
TIMEOUT = 30

# Bornes du filtre. 50 milliards de dollars laisse passer les grandes
# capitalisations sans noyer le bloc ; le plafond journalier protege des journees
# a trois cents publications, ou meme le seuil ne suffit pas.
CAP_MIN = 50_000_000_000
PAR_JOUR_MAX = 8

CRENEAU = {
    "time-pre-market": "avant l'ouverture",
    "time-after-hours": "après la clôture",
    "time-not-supplied": "horaire non communiqué",
}

# Noms tels que le flux les rend, allonges de mentions juridiques qui n'apportent
# rien dans un brief. Coupees a l'affichage.
SUFFIXES = (" Inc.", " Inc", " Corporation", " Corp.", " Corp", " Company (The)",
            " Company", " Co.", " plc", " PLC", " Holdings PLC", " N.V.", " S.A.",
            " Limited", " Ltd.", " Group", " (The)", ",")


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _cap(txt: str) -> int:
    """Capitalisation en dollars. Rend 0 si illisible.

    Deux formats a avaler, et c'est le piege : le calendrier des resultats rend
    « $673,938,031,023 », le screener rend « 38944540758.00 ». Une premiere version
    ne gardait que les chiffres — elle multipliait donc les capitalisations du
    screener par cent, et le filtre des grandes valeurs laissait passer des
    nanocaps et des bons de souscription.
    """
    brut = (txt or "").replace("$", "").replace(",", "").replace(" ", "").strip()
    if not brut:
        return 0
    try:
        return int(float(brut))
    except ValueError:
        return 0


def _nom(txt: str) -> str:
    nom = (txt or "").strip()
    change = True
    while change:                                     # plusieurs suffixes empiles
        change = False
        for s in SUFFIXES:
            if nom.endswith(s):
                nom, change = nom[: -len(s)].strip(), True
    return nom


def _eps(txt: str) -> str | None:
    """« $3.23 » -> « 3,23 $ ». Les parentheses du flux notent un negatif :
    « ($0.34) » -> « −0,34 $ »."""
    brut = (txt or "").strip()
    if not brut or brut in ("N/A", "-"):
        return None
    negatif = brut.startswith("(") and brut.endswith(")")
    valeur = brut.strip("()").replace("$", "").strip()
    if not valeur:
        return None
    return ("−" if negatif else "") + valeur.replace(".", ",") + " $"


def _milliards(cap: int) -> str:
    return f"{cap / 1e9:.0f} Md$".replace(".", ",")


def semaine_de(jour: dt.date) -> list[dt.date]:
    """Du jour au vendredi de sa semaine.

    Les jours ecoules sont exclus, et ce n'est pas un choix esthetique : passe la
    publication, le calendrier du Nasdaq efface le creneau — `time-not-supplied` —
    et le benefice de l'an dernier. Verifie sur le 27/07/2026, ou AstraZeneca
    ressortait sans horaire ni comparatif, quand le 29/07 portait bien
    `time-after-hours` et 3,65 dollars pour Microsoft. Garder ces jours remplissait
    le tableau de lignes appauvries, alors que ce qui s'est deja publie est traite
    par les puces de la rubrique.
    """
    # Un samedi ou un dimanche, on part du lundi suivant : rendre les deux jours de
    # week-end plus la semaine entiere donnait sept dates, dont deux sans cotation.
    depart = jour if jour.weekday() < 5 else jour + dt.timedelta(days=7 - jour.weekday())
    vendredi = depart + dt.timedelta(days=4 - depart.weekday())
    return [depart + dt.timedelta(days=i)
            for i in range((vendredi - depart).days + 1)]


def collecte(jours: list[dt.date]) -> tuple[list[dict], list[str]]:
    """Un objet par jour, societes filtrees et triees par capitalisation."""
    sortie: list[dict] = []
    echecs: list[str] = []
    for jour in jours:
        try:
            payload = _get(API.format(jour.isoformat()))
        except Exception as exc:                       # noqa: BLE001
            echecs.append(f"{jour} : {type(exc).__name__}")
            continue
        lignes = ((payload.get("data") or {}).get("rows")) or []
        retenues = []
        for ligne in lignes:
            cap = _cap(ligne.get("marketCap"))
            if cap < CAP_MIN:
                continue
            retenues.append({
                "name": _nom(ligne.get("name")),
                "symbol": (ligne.get("symbol") or "").strip(),
                "when": CRENEAU.get(ligne.get("time"), "horaire non communiqué"),
                "eps_forecast": _eps(ligne.get("epsForecast")),
                "eps_last_year": _eps(ligne.get("lastYearEPS")),
                "cap": _milliards(cap),
                "_cap": cap,
            })
        retenues.sort(key=lambda c: -c["_cap"])
        retenues = retenues[:PAR_JOUR_MAX]
        for c in retenues:
            c.pop("_cap", None)
        if retenues:
            sortie.append({"date": jour.isoformat(), "companies": retenues})
    return sortie, echecs


SCREENER = ("https://api.nasdaq.com/api/screener/stocks?tableonly=true"
            "&limit=5000&offset=0&download=true")

# Seuil des « grandes valeurs » pour les mouvements. Plus haut que celui des
# publications : un mouvement n'a d'interet dans un brief que s'il concerne un nom
# dont le marche parle, et 100 milliards de dollars est la borne qui les cerne.
CAP_MOUVEMENT = 100_000_000_000
MOUVEMENTS_MAX = 6
# En dessous, ce n'est pas un mouvement, c'est du bruit de seance.
SEUIL_PCT = 3.0


def _pct(txt: str) -> float | None:
    brut = (txt or "").replace("%", "").replace(",", "").strip()
    try:
        return float(brut)
    except ValueError:
        return None


def mouvements() -> tuple[list[dict], list[dict], str | None]:
    """Plus fortes hausses et baisses parmi les grandes capitalisations.

    Ce que les resultats seuls ne montrent pas : une valeur qui decroche ou
    s'envole sur autre chose qu'une publication — un contrat, une enquete, une
    rumeur d'operation. Le script rend les candidats ; la RAISON du mouvement
    n'est pas dans le flux et reste a chercher dans la presse. Une ligne sans
    explication attribuee n'a rien a faire dans le brief.

    Le parametre de tri du screener est ignore par l'API — les deux sens rendaient
    la meme liste alphabetique. Le tri se fait donc ici.
    """
    try:
        payload = _get(SCREENER)
    except Exception as exc:                           # noqa: BLE001
        return [], [], f"{type(exc).__name__}"

    data = payload.get("data") or {}
    lignes = data.get("rows") or (data.get("table") or {}).get("rows") or []
    retenues = []
    for ligne in lignes:
        pct = _pct(ligne.get("pctchange"))
        cap = _cap(ligne.get("marketCap"))
        if pct is None or cap < CAP_MOUVEMENT or abs(pct) < SEUIL_PCT:
            continue
        retenues.append({
            "name": _nom(ligne.get("name", "").replace(" Common Stock", "")
                                              .replace(" Class A", "")),
            "symbol": (ligne.get("symbol") or "").strip(),
            "pct": f"{pct:+.2f} %".replace(".", ",").replace("+-", "−")
                                  .replace("-", "−"),
            "last": (ligne.get("lastsale") or "").strip(),
            "sector": (ligne.get("sector") or "").strip(),
            "cap": _milliards(cap),
            "_pct": pct,
        })
    retenues.sort(key=lambda c: -c["_pct"])
    hausses = [dict(c) for c in retenues[:MOUVEMENTS_MAX] if c["_pct"] > 0]
    baisses = [dict(c) for c in retenues[::-1][:MOUVEMENTS_MAX] if c["_pct"] < 0]
    for c in hausses + baisses:
        c.pop("_pct", None)
    return hausses, baisses, None


def bloc(jours: list[dict], aujourdhui: dt.date) -> dict:
    return {
        "as_of": aujourdhui.isoformat(),
        "source": "Nasdaq",
        "url": "https://www.nasdaq.com/market-activity/earnings",
        "note": "Sociétés cotées aux États-Unis dont la capitalisation dépasse "
                "50 milliards de dollars, huit au plus par jour, les plus grandes "
                "d'abord. Le calendrier du Nasdaq ne couvre pas les cotations "
                "européennes : pour celles-ci, l'agenda de presse reste la source.",
        "days": jours,
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dry = "--dry-run" in sys.argv

    aujourdhui = dt.date.today()
    stem = args[0] if args else aujourdhui.isoformat()
    chemin = os.path.join(NEWS, f"brief-{stem}.json")

    jours, echecs = collecte(semaine_de(dt.date.fromisoformat(stem)))
    total = sum(len(j["companies"]) for j in jours)
    print(f"calendrier des resultats : {len(jours)} jour(s), {total} societe(s) "
          f"retenue(s) au-dessus de {_milliards(CAP_MIN)}")
    for j in jours:
        marque = "  <- aujourd'hui" if j["date"] == aujourdhui.isoformat() else ""
        print(f"  {j['date']}{marque}")
        for c in j["companies"]:
            eps = f", BPA attendu {c['eps_forecast']}" if c["eps_forecast"] else ""
            print(f"     {c['symbol']:<6} {c['name'][:30]:<32}{c['when']}{eps}")
    for e in echecs:
        print(f"  echec {e}")

    if not jours:
        print("Aucune societe retenue — bloc non ecrit.")
        return 1 if echecs else 0

    hausses, baisses, echec_mvt = mouvements()
    print()
    print(f"mouvements sur les grandes valeurs (plus de {_milliards(CAP_MOUVEMENT)}, "
          f"variation d'au moins {SEUIL_PCT:.0f} %)")
    if echec_mvt:
        print(f"  echec du screener : {echec_mvt}")
    for titre, lot in (("hausses", hausses), ("baisses", baisses)):
        print(f"  {titre} :" if lot else f"  {titre} : aucune")
        for c in lot:
            print(f"     {c['symbol']:<6} {c['name'][:30]:<32}{c['pct']:>10}"
                  f"   {c['sector'][:24]}")
    if hausses or baisses:
        print("  -> la RAISON de chaque mouvement n'est pas dans le flux :")
        print("     la chercher dans la presse, ou ne pas citer la ligne.")

    if dry:
        return 0
    if not os.path.exists(chemin):
        print(f"{chemin} absent — lancer d'abord py refresh.py start")
        return 1

    brief = json.load(open(chemin, encoding="utf-8"))
    brief["earnings"] = bloc(jours, aujourdhui)
    if hausses or baisses:
        brief["earnings"]["movers"] = {"up": hausses, "down": baisses}
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(brief, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"bloc `earnings` ecrit dans {os.path.relpath(chemin, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
