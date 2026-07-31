#!/usr/bin/env python3
"""Pilote du brief quotidien : deux commandes au lieu d'une dizaine d'etapes.

Pourquoi ce script existe. Mesure faite le 28/07/2026, l'outillage n'est pas le
goulot : market_prices 3,1 s, brief_check 4,6 s, selfcheck 0,2 s, privacy_check
0,5 s — huit secondes en tout. Le temps part ailleurs :

  1. la recherche de presse, incompressible, qui demande de lire ;
  2. la reextraction complete du calendrier chaque matin, alors que les evenements
     de la semaine ne bougent pas d'un jour sur l'autre — seuls les chiffres
     publies s'y ajoutent ;
  3. le recopiage a la main de l'encart FactSet et des quarante lignes de
     calendrier, identiques a la veille ;
  4. quatre appels de scripts separes, chacun un aller-retour.

Les points 2 a 4 sont mecaniques, donc automatisables. Ce script les prend :

    py refresh.py start     releve les cours, controle la coherence, et ecrit un
                            brief prerempli — dates a jour, encart FactSet et
                            calendrier reportes de la veille, rubriques vides.
                            Affiche les chiffres du pipeline prets a citer.

    py refresh.py finish    verifie les dates d'articles, la confidentialite,
                            indexe le brief, commite et pousse.

Reste a faire a la main entre les deux, et c'est le coeur du travail : la
recherche de presse, l'ecriture des rubriques, la mise a jour des chiffres publies
du calendrier et de l'encart FactSet le vendredi.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import subprocess
import sys

# Le pilote reaffiche la sortie des scripts qu'il lance, et celle-ci contient des
# signes moins typographiques et des accents. La console Windows etant en cp1252,
# il plantait en plein milieu — apres avoir pourtant fait le travail. Chaque
# collecteur protege deja sa propre sortie ; il fallait proteger celle-ci aussi.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
NEWS = os.path.join(ROOT, "news")

RESET, GREEN, RED, DIM, YELLOW, BOLD = (
    "\033[0m", "\033[32m", "\033[31m", "\033[2m", "\033[33m", "\033[1m")

# Au-dela de ce delai, l'encart FactSet reporte de la veille est perime : le
# rapport parait le vendredi, huit jours veut donc dire qu'une edition a ete
# manquee. Meme seuil que le site et que brief_check.
FACTSET_MAX_AGE = 8


def log(msg: str = "") -> None:
    print(msg, flush=True)


def run(cmd: list[str], titre: str) -> int:
    """Lance un script du depot et rend son code de sortie, sortie affichee."""
    log(f"{BOLD}> {titre}{RESET}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    out = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    for ligne in (out.stdout or "").rstrip().split("\n"):
        log(f"  {ligne}")
    if out.returncode != 0 and out.stderr:
        log(f"{RED}  {out.stderr.strip()[:400]}{RESET}")
    return out.returncode


def briefs_existants() -> list[str]:
    idx = os.path.join(NEWS, "index.json")
    if not os.path.exists(idx):
        return []
    return json.load(open(idx, encoding="utf-8")).get("dates", [])


def lundi_de(jour: dt.date) -> dt.date:
    return jour - dt.timedelta(days=jour.weekday())


# ------------------------------------------------------------------- start ---

def squelette(aujourdhui: dt.date, precedent: dict | None,
              target: str) -> tuple[dict, list[str]]:
    """Brief prerempli. Rend aussi la liste des points a verifier a la main.

    Ce qui est reporte de la veille : l'encart FactSet, hebdomadaire par nature,
    et le calendrier, dont les evenements de la semaine ne changent pas. Ce qui
    ne l'est pas : les rubriques, qui portent l'actualite du jour et doivent etre
    ecrites.
    """
    alertes: list[str] = []
    brief = {
        "date": aujourdhui.isoformat(),
        "session": target,
        "generated_at": dt.datetime.now(dt.timezone.utc)
                          .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "focus": {"title": "", "body": ""},
    }

    if precedent and precedent.get("factset"):
        fs = json.loads(json.dumps(precedent["factset"]))       # copie profonde
        brief["factset"] = fs
        try:
            age = (aujourdhui - dt.date.fromisoformat(fs["as_of"])).days
            if age > FACTSET_MAX_AGE:
                alertes.append(f"encart FactSet vieux de {age} j — relever le PDF "
                               f"du vendredi (EarningsInsight_MMJJAA.pdf)")
            elif aujourdhui.weekday() == 4:
                alertes.append("vendredi : une nouvelle edition FactSet parait "
                               "dans la journee, la relever")
        except (KeyError, ValueError):
            alertes.append("encart FactSet sans as_of lisible")
    else:
        alertes.append("aucun encart FactSet a reporter — a construire")

    if precedent and precedent.get("calendar"):
        cal = json.loads(json.dumps(precedent["calendar"]))
        semaine = lundi_de(aujourdhui).isoformat()
        if cal.get("week_of") != semaine:
            alertes.append(f"calendrier reporte : il porte la semaine du "
                           f"{cal.get('week_of')} alors qu'on entre dans celle du "
                           f"{semaine} — le reextraire entierement")
        else:
            jours = [j["date"] for j in cal.get("days", [])]
            manquants = [j for j in jours if j < aujourdhui.isoformat()
                         and not any(e.get("actual") for e in
                                     next(d for d in cal["days"] if d["date"] == j)
                                     .get("events", []))]
            alertes.append("calendrier reporte de la veille : completer les "
                           "chiffres publies (champ actual) des jours ecoules"
                           + (f", dont {', '.join(manquants)}" if manquants else ""))
        cal["week_of"] = semaine
        brief["calendar"] = cal
    else:
        alertes.append("aucun calendrier a reporter — a construire")

    brief["sections"] = {k: [] for k in
                         ("macro", "geo", "micro", "actions", "obligations")}
    return brief, alertes


def table_pipeline(latest: dict) -> None:
    """Les chiffres a citer, dans l'ordre ou le brief les utilise, avec ce qui
    interdit de les citer : le drapeau suspect ou perime, et l'alignement."""
    m = latest["markets"]
    diag = latest.get("diagnostics", {})
    log(f"{BOLD}Chiffres du pipeline — seance {latest['target_date']}{RESET}")
    log(f"{DIM}  tout chiffre de cloture cite dans le brief vient de cette table{RESET}")
    log(f"  {'instrument':22s}{'niveau':>12s}{'var':>10s}{'u':>4s}  {'date':11s} drapeaux")
    log(f"  {'-' * 74}")
    for label, e in m.items():
        if "error" in e:
            log(f"  {RED}{label:22s}{'indisponible':>12s}{RESET}")
            continue
        chg = e.get("change")
        drapeaux = []
        if e.get("suspect"):
            drapeaux.append(f"{RED}SUSPECT{RESET} " + (e.get("suspect_reason") or "")[:52])
        if e.get("stale"):
            drapeaux.append(f"{YELLOW}PERIME{RESET}")
        if e.get("on_target") is False:
            drapeaux.append(f"{YELLOW}en retard, dater explicitement{RESET}")
        if (e.get("change_days") or 0) > 4:
            drapeaux.append(f"{YELLOW}variation sur {e['change_days']} j{RESET}")
        log(f"  {label:22s}{e['level']!s:>12}"
            f"{(chg if chg is not None else '—')!s:>10}{e.get('unit', ''):>4}  "
            f"{e['date']:11s} {' · '.join(drapeaux)}")
    if diag.get("ignored_after_session"):
        log(f"{DIM}  {len(diag['ignored_after_session'])} instrument(s) avaient des "
            f"points posterieurs a la seance : ecartes.{RESET}")


def cmd_start(force: bool) -> int:
    aujourdhui = dt.date.today()
    cible = os.path.join(NEWS, f"brief-{aujourdhui.isoformat()}.json")

    if os.path.exists(cible) and not force:
        log(f"{RED}Un brief porte deja la date du jour : {cible}{RESET}")
        log("Le refuser est la regle du depot. --force pour ecraser.")
        return 1

    if run(["py", "market_prices.py"], "relevé des cours") != 0:
        log(f"{RED}La collecte a echoue. Un brief sur des cours faux est pire "
            f"que pas de brief.{RESET}")
        return 1
    if run(["py", "selfcheck.py"], "coherence pipeline / app") != 0:
        log(f"{YELLOW}Incoherence signalee — la corriger avant d'ecrire.{RESET}")

    latest = json.load(open(os.path.join(ROOT, "latest.json"), encoding="utf-8"))
    log()
    table_pipeline(latest)

    dates = briefs_existants()
    precedent = None
    if dates:
        chemin = os.path.join(NEWS, f"brief-{dates[0]}.json")
        if os.path.exists(chemin):
            precedent = json.load(open(chemin, encoding="utf-8"))

    brief, alertes = squelette(aujourdhui, precedent, latest["target_date"])
    with open(cible, "w", encoding="utf-8") as fh:
        json.dump(brief, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    log()
    log(f"{GREEN}Ecrit {os.path.relpath(cible, ROOT)}{RESET}")
    log(f"{DIM}  date {brief['date']} · seance {brief['session']}"
        f" · fenetre d'actualite depuis la publication du brief du "
        f"{dates[0] if dates else '—'}{RESET}")
    # Les deux collecteurs de la rubrique micro, et le radar de presse. Lances ici
    # pour qu'une seule commande rassemble tout le mecanique : sans eux il fallait
    # trois appels de plus, et c'est le nombre d'allers-retours qui allongeait le
    # travail, pas la duree de chacun.
    log()
    run(["py", "earnings.py"], "publications de resultats et mouvements")
    log()
    run(["py", "news_radar.py"], "titres parus depuis le brief precedent")

    log()
    log(f"{BOLD}A faire a la main{RESET}")
    for a in alertes:
        log(f"  {YELLOW}·{RESET} {a}")
    log(f"  {YELLOW}·{RESET} une recherche de presse DEDIEE par rubrique — "
        f"geopolitique, macro, micro, marches, obligataire")
    log(f"  {YELLOW}·{RESET} puis : py refresh.py finish")
    return 0


# ------------------------------------------------------------------ finish ---

def cmd_finish(pousser: bool, message: str | None) -> int:
    aujourdhui = dt.date.today().isoformat()
    cible = os.path.join(NEWS, f"brief-{aujourdhui}.json")
    if not os.path.exists(cible):
        log(f"{RED}{cible} absent — lancer d'abord py refresh.py start{RESET}")
        return 1

    brief = json.load(open(cible, encoding="utf-8"))
    vides = [k for k, v in brief.get("sections", {}).items() if not v]
    if not (brief.get("focus") or {}).get("body"):
        log(f"{RED}Le focus est vide.{RESET}")
        return 1
    if vides:
        log(f"{YELLOW}Rubriques vides : {', '.join(vides)}{RESET}")

    # Indexation avant controle : brief_check lit index.json pour savoir quel
    # brief verifier.
    idx_path = os.path.join(NEWS, "index.json")
    idx = json.load(open(idx_path, encoding="utf-8"))
    if aujourdhui not in idx["dates"]:
        idx["dates"].insert(0, aujourdhui)
        with open(idx_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(idx, ensure_ascii=False) + "\n")
        log(f"{DIM}index.json : {aujourdhui} ajoute en tete{RESET}")

    if run(["py", "brief_check.py"], "dates de publication des articles") != 0:
        log(f"{RED}Des dates d'article ne tiennent pas. Corriger avant de "
            f"pousser.{RESET}")
        return 1
    if run(["py", "privacy_check.py"], "confidentialite") != 0:
        log(f"{RED}Donnee personnelle detectee. Un depot public deja pousse "
            f"garde une trace meme apres correction.{RESET}")
        return 1

    if not pousser:
        log(f"{GREEN}Controles verts. Rien commite (--no-push).{RESET}")
        return 0

    sujet = message or f"Brief du {aujourdhui}, seance du {brief['session']}"
    # Auteur neutre : le depot est public, une adresse personnelle dans
    # l'historique ne s'en efface plus.
    auteur = ["-c", "user.name=veille-marches", "-c", "user.email=noreply@localhost"]
    for cmd, titre in ((["git", "add", "-A"], "git add"),
                       (["git"] + auteur + ["commit", "-q", "-m", sujet], "git commit"),
                       (["git", "push", "-q", "origin", "main"], "git push")):
        if run(cmd, titre) != 0:
            log(f"{RED}{titre} a echoue.{RESET}")
            return 1
    log(f"{GREEN}Pousse. https://daddeasy.github.io/veille-marches/{RESET}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="etape", required=True)
    s = sous.add_parser("start", help="cours, controles, brief prerempli")
    s.add_argument("--force", action="store_true",
                   help="ecraser un brief portant deja la date du jour")
    f = sous.add_parser("finish", help="controles, indexation, commit, push")
    f.add_argument("--no-push", action="store_true", help="ne rien commiter")
    f.add_argument("-m", "--message", help="sujet du commit")
    a = p.parse_args()
    if a.etape == "start":
        return cmd_start(a.force)
    return cmd_finish(not a.no_push, a.message)


if __name__ == "__main__":
    sys.exit(main())
