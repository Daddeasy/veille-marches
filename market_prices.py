#!/usr/bin/env python3
"""
Releve quotidien des marches — 14 indicateurs, sources multiples avec repli.

Aucune dependance externe : uniquement la bibliotheque standard.
Pas de yfinance (scraper non officiel qui casse a chaque changement de Yahoo),
pas de requests. Rien a installer, rien a mettre a jour.

Sorties :
  latest.json                     adresse fixe lue par l'app
  history/markets-AAAA-MM-JJ.json archive datee
  series.csv                      serie cumulee append-only (date,instrument,valeur,source)

Usage :  py market_prices.py
"""

from __future__ import annotations

import concurrent.futures
import csv
import datetime as dt
import io
import json
import os
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- reglages ---

TIMEOUT = 40          # FRED est parfois lent
RETRIES = 3
HISTORY_YEARS = 2     # profondeur demandee aux sources
MAX_ERRORS_OK = 4     # au-dela, le job sort en code 1 pour declencher l'alerte GitHub

# Nombre d'instruments interroges en parallele. Le travail est presque
# exclusivement de l'attente reseau, donc des fils suffisent — inutile de sortir
# l'asynchrone. Mesure : la collecte sequentielle a mis 12 min 47 sur un runner
# GitHub, pour une limite de job fixee a 25 minutes. FRED est lent par
# intermittence et le script reessaie jusqu'a trois fois avec 40 s d'attente :
# une seule serie recalcitrante coutait deux minutes a elle seule.
# Plafonne a 6 pour ne pas se faire limiter par les sources.
WORKERS = 6

# Age minimal de meta.regularMarketTime pour considerer que la seance est close
# et que le prix est etabli plutot qu'intraday. Voir yahoo() pour le detail.
META_CLOSE_MIN_AGE_H = 2.0

UA = {"User-Agent": "Mozilla/5.0 (compatible; veille-marches/1.0)"}

# Racine du script — gere l'absence de __file__ (notebook, REPL)
try:
    ROOT = os.path.dirname(os.path.abspath(__file__))
except NameError:
    ROOT = os.getcwd()


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------- HTTP ---

def _ssl_context() -> ssl.SSLContext | None:
    """Magasin de certificats a utiliser, ou None pour celui du systeme.

    certifi s'il est installe. Motif precis : le poste Windows sur lequel ce depot
    est tenu n'a pas la chaine de api.statistiken.bundesbank.de dans son magasin
    systeme et echoue en CERTIFICATE_VERIFY_FAILED, la ou un runner Ubuntu l'a.

    Optionnel a dessein. Le workflow n'installe aucune dependance — c'est un choix
    documente — donc certifi ne peut pas devenir obligatoire : sans lui on retombe
    sur le magasin systeme, qui suffit en integration continue.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:                                 # noqa: BLE001
        return None


_SSL_CTX = _ssl_context()


def _get(url: str, timeout: int = TIMEOUT) -> bytes:
    """GET avec reprise exponentielle. Leve la derniere exception si tout echoue."""
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=_SSL_CTX) as resp:
                return resp.read()
        except Exception as exc:                      # noqa: BLE001
            last = exc
            if attempt < RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last                                        # type: ignore[misc]


Series = list[tuple[dt.date, float]]


def _clean(points: Series) -> Series:
    """Trie, deduplique par date (derniere valeur gagne), retire les non-finis."""
    by_date: dict[dt.date, float] = {}
    for d, v in points:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv != fv or fv in (float("inf"), float("-inf")):   # NaN / inf
            continue
        by_date[d] = fv
    return sorted(by_date.items())


def _start_date() -> str:
    return (dt.date.today() - dt.timedelta(days=365 * HISTORY_YEARS + 10)).isoformat()


# ---------------------------------------------------------------- sources ---
# Chaque source renvoie une SERIE, jamais un point isole.
# Une variation quotidienne exige deux clotures consecutives : un point isole
# donne le niveau, pas le mouvement. La serie sert aussi a detecter un flux fige.

# Nature de la valeur publiee. Ce n'est PAS un detail cosmetique : appeler
# "cloture" un fixing de 14h15 et une cloture de seance revient a comparer deux
# choses differentes sous le meme nom. L'attribut est porte par la SOURCE et non
# par l'instrument, pour rester exact quand un repli se declenche.
CLOSE = "cloture de seance"
ECB_FIX = "fixing BCE 14h15 CET"
H15 = "releve H.15, ~15h30 New York"
EOD = "reference fin de journee"
CNO = "fixing CNO quotidien"
BUBA = "structure par termes Bundesbank a 10 ans"
MONTHLY_AVG = "moyenne mensuelle"
UTC_CLOSE = "cloture 00h UTC"


def fred(series_id: str, basis: str = EOD):
    """Reserve federale de St. Louis — CSV keyless. Reference pour les taux US."""

    def fetch() -> Series:
        url = ("https://fred.stlouisfed.org/graph/fredgraph.csv"
               f"?id={series_id}&cosd={_start_date()}")
        raw = _get(url).decode("utf-8", "replace")
        rows = list(csv.reader(io.StringIO(raw)))
        out: Series = []
        for row in rows[1:]:                          # saute l'en-tete
            if len(row) < 2:
                continue
            date_s, val_s = row[0].strip(), row[1].strip()
            if val_s in (".", "", "NaN"):             # FRED marque les trous par un point
                continue
            try:
                out.append((dt.date.fromisoformat(date_s), float(val_s)))
            except ValueError:
                continue
        return _clean(out)

    fetch.label = f"fred:{series_id}"                 # type: ignore[attr-defined]
    fetch.basis = basis                               # type: ignore[attr-defined]
    return fetch


def ecb(key: str, basis: str = ECB_FIX):
    """Banque centrale europeenne — API keyless. Reference pour le change."""

    def fetch() -> Series:
        url = (f"https://data-api.ecb.europa.eu/service/data/{key}"
               f"?startPeriod={_start_date()}&format=csvdata")
        raw = _get(url).decode("utf-8", "replace")
        out: Series = []
        for row in csv.DictReader(io.StringIO(raw)):
            date_s = (row.get("TIME_PERIOD") or "").strip()
            val_s = (row.get("OBS_VALUE") or "").strip()
            if not date_s or not val_s:
                continue
            try:
                if len(date_s) == 7:                  # mensuel "2026-06"
                    y, m = date_s.split("-")
                    date = dt.date(int(y), int(m), 1)
                else:
                    date = dt.date.fromisoformat(date_s)
                out.append((date, float(val_s)))
            except ValueError:
                continue
        return _clean(out)

    fetch.label = f"ecb:{key.split('/')[0]}"          # type: ignore[attr-defined]
    fetch.basis = basis                               # type: ignore[attr-defined]
    return fetch


def bundesbank(series_key: str, tag: str, basis: str = BUBA):
    """Bundesbank — structure par termes des taux des emprunts federaux cotes,
    methode de Svensson, echeance residuelle de dix ans. Serie QUOTIDIENNE,
    publique, sans inscription : 19 669 observations au premier relevé, jusqu'au
    jour meme.

    C'est la source officielle allemande, et elle comble le trou symetrique de
    celui du 10 ans francais — a la difference qu'elle ne demande, elle, aucune
    cle. Eurostat ne publie pas de serie quotidienne et la BCE ne descend pas au
    niveau pays : sa courbe est un agregat zone euro.

    Precaution a ne pas perdre de vue : ce n'est PAS le rendement de l'emprunt de
    reference, le Bund dit « on the run », mais un point de courbe ajustee.
    L'ecart est reel et mesure — au 24/07/2026 la serie donne 3,24 % la ou la
    presse citait 3,18 % sur l'emprunt phare. D'ou le `basis` explicite, que le
    site affiche en infobulle et que le brief doit nommer plutot que de laisser
    croire a une divergence de donnees.

    Format : un CSV dont l'en-tete tient sur cinq lignes de metadonnees, puis une
    ligne par jour calendaire. Les jours sans cotation portent un point.
    """
    def fetch() -> Series:
        raw = _get("https://api.statistiken.bundesbank.de/rest/download/BBSIS/"
                   f"{series_key}?format=csv&lang=en").decode("utf-8", "replace")
        out: Series = []
        for line in raw.splitlines():
            champs = line.split(",")
            if len(champs) < 2:
                continue
            jour = champs[0].strip().strip('"﻿')
            # Filtre par la forme de la date : ecarte les cinq lignes d'en-tete
            # sans avoir a les compter, ce qui casserait si la Bundesbank en
            # ajoutait une.
            if len(jour) != 10 or jour[4] != "-" or jour[7] != "-":
                continue
            try:
                date, valeur = dt.date.fromisoformat(jour), float(champs[1])
            except ValueError:
                continue                              # « . » les jours sans cotation
            out.append((date, valeur))
        if not out:
            raise ValueError("bundesbank : aucune observation")
        return _clean(out)

    fetch.label = f"bundesbank:{tag}"                 # type: ignore[attr-defined]
    fetch.basis = basis                               # type: ignore[attr-defined]
    return fetch


def webstat(series_key: str, dataset: str = "FM", basis: str = CNO):
    """Banque de France (Webstat) — TEC 10 quotidien, source de reference
    francaise. Seule voie gratuite vers un 10Y France en quotidien : l'ECB ne
    publie la France qu'en mensuel (les series pays du dataset FM renvoient 404)
    et Stooq est inaccessible depuis un runner.

    Necessite une cle gratuite (inscription sur webstat.banque-france.fr/signup),
    lue dans la variable d'environnement WEBSTAT_CLIENT_ID. Sans cle, la source
    est ignoree et le repli FRED mensuel prend le relais.

    ATTENTION : la documentation d'authentification est derriere un login, donc
    le nom exact du porteur de cle n'a pas pu etre verifie. La cle est envoyee
    a la fois en en-tete et en parametre, et le parseur accepte plusieurs formes
    de reponse. A confirmer au premier run — le repli garantit qu'un echec ici
    ne casse rien.
    """

    def fetch() -> Series:
        client_id = os.environ.get("WEBSTAT_CLIENT_ID", "").strip()
        if not client_id:
            raise ValueError("WEBSTAT_CLIENT_ID absent")

        url = (f"https://api.webstat.banque-france.fr/webstat-fr/v1/data/"
               f"{dataset}/{series_key}?format=json&client_id="
               + urllib.parse.quote(client_id))
        req = urllib.request.Request(url, headers={
            **UA,
            "X-IBM-Client-Id": client_id,
            "Accept": "application/json",
        })
        raw = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode(
            "utf-8", "replace")

        payload = json.loads(raw)
        out: Series = []

        def walk(node):
            """Cherche des couples date/valeur sans presumer de l'emboitement."""
            if isinstance(node, dict):
                date_s = next((node[k] for k in
                               ("periode", "date", "TIME_PERIOD", "time_period")
                               if isinstance(node.get(k), str)), None)
                val = next((node[k] for k in
                            ("valeur", "value", "OBS_VALUE", "obs_value")
                            if node.get(k) not in (None, "")), None)
                if date_s and val is not None:
                    try:
                        d = (dt.date.fromisoformat(date_s[:10]) if len(date_s) >= 10
                             else dt.date(int(date_s[:4]), int(date_s[5:7]), 1))
                        out.append((d, float(str(val).replace(",", "."))))
                    except (ValueError, TypeError):
                        pass
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(payload)
        if not out:
            raise ValueError("webstat: aucune observation reconnue dans la reponse")
        return _clean(out)

    fetch.label = f"webstat:{series_key.split('.')[-2]}"  # type: ignore[attr-defined]
    fetch.basis = basis                                   # type: ignore[attr-defined]
    return fetch


def yahoo(symbol: str, basis: str = CLOSE, scale: float = 1.0):
    """Yahoo Finance, endpoint chart en JSON brut. Sans yfinance."""

    def fetch() -> Series:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               + urllib.parse.quote(symbol)
               + "?range=2y&interval=1d")
        payload = json.loads(_get(url))
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        out: Series = []
        for ts, close in zip(stamps, closes):
            if close is None:                         # <-- Yahoo bourre de null
                continue                              #     les periodes non cotees
            date = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
            out.append((date, float(close) * scale))
        out = _clean(out)

        # Yahoo publie la derniere cloture dans meta.regularMarketPrice AVANT
        # de l'ajouter au tableau des barres quotidiennes. Sans cela, 13 des 22
        # instruments retardaient d'une seance — verifie : la barre ^GSPC
        # s'arretait a 7408,30 au 23/07 alors que meta donnait 7411,98 au 24/07,
        # exactement la valeur publiee par FRED. C'est bien la cloture officielle.
        #
        # Garde-fou : regularMarketTime est rafraichi en continu tant que le
        # marche est ouvert. Un horodatage vieux de plus de deux heures signifie
        # donc que la seance est close et que le prix est etabli. A 6h UTC, cela
        # accepte le S&P et le CAC (clos depuis des heures) et refuse Shanghai
        # et le Sensex, encore en seance — dont on garde la barre de la veille
        # plutot que d'injecter un cours intraday.
        fetch.used_meta = False                       # type: ignore[attr-defined]
        meta = result.get("meta") or {}
        ts_meta, px_meta = meta.get("regularMarketTime"), meta.get("regularMarketPrice")
        if ts_meta and px_meta is not None:
            quoted = dt.datetime.fromtimestamp(int(ts_meta), dt.timezone.utc)
            age_h = (dt.datetime.now(dt.timezone.utc) - quoted).total_seconds() / 3600
            if age_h >= META_CLOSE_MIN_AGE_H and (not out or quoted.date() > out[-1][0]):
                out.append((quoted.date(), float(px_meta) * scale))
                fetch.used_meta = True                # type: ignore[attr-defined]
                out = _clean(out)
        return out

    fetch.label = f"yahoo:{symbol}"                   # type: ignore[attr-defined]
    fetch.basis = basis                               # type: ignore[attr-defined]
    return fetch


_JP_ERA = {"R": 2018, "H": 1988, "S": 1925}           # Reiwa 1 = 2019, etc.


def _jp_date(raw: str) -> dt.date | None:
    """Convertit une date en ere imperiale japonaise : 'R8.7.1' -> 2026-07-01."""
    raw = raw.strip()
    if len(raw) < 4 or raw[0] not in _JP_ERA:
        return None
    try:
        year, month, day = raw[1:].split(".")
        return dt.date(_JP_ERA[raw[0]] + int(year), int(month), int(day))
    except (ValueError, KeyError):
        return None


def mof_jp(maturity_years: int = 10, basis: str = EOD):
    """Ministere des Finances japonais — courbe JGB quotidienne, source officielle.

    Remplace le repli mensuel de FRED : le Japon publie bien du quotidien,
    gratuitement et sans cle. Format Shift-JIS, dates en ere imperiale.
    """

    target = f"{maturity_years}年"

    def parse(raw: str) -> Series:
        rows = list(csv.reader(io.StringIO(raw)))
        col = None
        for row in rows[:10]:
            for idx, cell in enumerate(row):
                if cell.strip() == target:
                    col = idx
                    break
            if col is not None:
                break
        if col is None:
            raise ValueError(f"colonne {target} absente du CSV du MOF")

        out: Series = []
        for row in rows:
            if len(row) <= col:
                continue
            date = _jp_date(row[0])
            if date is None:
                continue
            val_s = row[col].strip()
            if not val_s or val_s == "-":
                continue
            try:
                out.append((date, float(val_s)))
            except ValueError:
                continue
        return out

    def fetch() -> Series:
        # Le MOF publie deux fichiers : jgbcm_all.csv porte tout l'historique
        # mais s'arrete a la fin du mois precedent ; jgbcm.csv contient le mois
        # en cours. Il faut les DEUX — le premier seul renvoyait une valeur
        # vieille de 25 jours, signalee perimee a juste titre par le controle.
        base = "https://www.mof.go.jp/jgbs/reference/interest_rate/"
        merged: Series = []
        errors: list[str] = []
        for name, timeout in (("data/jgbcm_all.csv", 60), ("jgbcm.csv", 40)):
            try:
                raw = _get(base + name, timeout=timeout).decode("shift_jis", "replace")
                merged += parse(raw)
            except Exception as exc:                  # noqa: BLE001
                errors.append(f"{name}: {type(exc).__name__}")
        if not merged:
            raise ValueError("mof: " + " | ".join(errors))
        return _clean(merged)

    fetch.label = f"mof_jp:{maturity_years}y"         # type: ignore[attr-defined]
    fetch.basis = basis                               # type: ignore[attr-defined]
    return fetch


def kraken(pair: str = "XBTUSD", basis: str = UTC_CLOSE):
    """Kraken — clotures quotidiennes reelles, keyless, sans anti-bot."""

    def fetch() -> Series:
        url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=1440"
        payload = json.loads(_get(url))
        if payload.get("error"):
            raise ValueError(f"kraken: {payload['error']}")
        result = payload["result"]
        key = next(k for k in result if k != "last")
        out: Series = []
        for row in result[key]:
            date = dt.datetime.fromtimestamp(int(row[0]), dt.timezone.utc).date()
            out.append((date, float(row[4])))         # index 4 = cloture
        return _clean(out)

    fetch.label = f"kraken:{pair}"                    # type: ignore[attr-defined]
    fetch.basis = basis                               # type: ignore[attr-defined]
    return fetch


def cnbc(symbol: str, basis: str = CLOSE):
    """CNBC — cotation obligataire souveraine, endpoint JSON public.

    Seule voie identifiee vers un 10 ans FRANCAIS QUOTIDIEN sans inscription :
    la BCE ne publie la France qu'en mensuel (ses series pays du dataset FM
    renvoient 404, jokers compris), Eurostat ne diffuse pas de serie quotidienne,
    DBnomics ne mirroite pas le jeu « marches financiers » de la Banque de
    France, et Stooq, Boursorama et Zonebourse sont hors d'atteinte.

    Aucune protection n'est contournee : une requete ordinaire avec un
    User-Agent suffit, contrairement a l'equivalent de CNN qui renvoie 418 tant
    qu'on ne falsifie pas l'en-tete Referer. C'est la meme categorie que
    l'endpoint chart de Yahoo, sur lequel repose deja la moitie des indicateurs.

    Deux limites assumees :
      - endpoint non documente, donc susceptible de changer sans preavis. Le
        repli FRED mensuel reste derriere pour que rien ne casse.
      - il renvoie un INSTANTANE, pas une serie. On reconstruit donc deux points
        — la cloture precedente et la derniere — ce qui suffit a la variation
        quotidienne mais ne donne ni percentile ni variation 1M. series.csv
        accumulera l'historique jour apres jour.

    Recoupe a la main : US10Y-US donnait 4,681 % la ou FRED plus Yahoo
    ressortaient a 4,679 %, soit 0,2 pb d'ecart.
    """

    def fetch() -> Series:
        url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/"
               f"symbolType/symbol?symbols={urllib.parse.quote(symbol)}"
               "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
        payload = json.loads(_get(url))
        quotes = payload["FormattedQuoteResult"]["FormattedQuote"]
        if not isinstance(quotes, list):
            quotes = [quotes]
        q = quotes[0]

        def num(raw) -> float | None:
            if raw in (None, ""):
                return None
            try:
                return float(str(raw).replace("%", "").replace(",", "").strip())
            except ValueError:
                return None

        last = num(q.get("last"))
        prev = num(q.get("previous_day_closing") or q.get("bond_prev_day_closing_price"))
        stamp = q.get("last_time") or ""
        if last is None or len(stamp) < 10:
            raise ValueError(f"cnbc {symbol} : reponse inexploitable")
        date = dt.date.fromisoformat(stamp[:10])

        out: Series = [(date, last)]
        if prev is not None:
            out.append((prev_business_day(date), prev))
        return _clean(out)

    fetch.label = f"cnbc:{symbol}"                    # type: ignore[attr-defined]
    fetch.basis = basis                               # type: ignore[attr-defined]
    return fetch


def fng_crypto(basis: str = "publication quotidienne 00h UTC"):
    """Indice Fear & Greed crypto d'alternative.me.

    API publique documentee, gratuite, sans cle et sans en-tete particulier :
    c'est une source legitime, contrairement a l'equivalent de CNN dont
    l'endpoint renvoie 418 tant qu'on ne se fait pas passer pour son propre
    site. Echelle 0 a 100 : 0 = peur extreme, 100 = avidite extreme.
    """

    def fetch() -> Series:
        url = "https://api.alternative.me/fng/?limit=800"
        payload = json.loads(_get(url))
        if (payload.get("metadata") or {}).get("error"):
            raise ValueError(f"alternative.me : {payload['metadata']['error']}")
        out: Series = []
        for row in payload.get("data", []):
            try:
                date = dt.datetime.fromtimestamp(
                    int(row["timestamp"]), dt.timezone.utc).date()
                out.append((date, float(row["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        if not out:
            raise ValueError("alternative.me : aucune observation")
        return _clean(out)

    fetch.label = "alternative.me:fng"                # type: ignore[attr-defined]
    fetch.basis = basis                               # type: ignore[attr-defined]
    return fetch


def combine(*sources, basis: str | None = None):
    """Fusionne plusieurs sources en une seule serie, les suivantes completant
    la premiere. Sert quand une source porte l'historique et une autre la
    fraicheur.

    Cas reel : le CSI 300 sur 000300.SS (flux Shanghai) offre deux ans
    d'historique mais s'arrete une semaine en arriere ; sur 399300.SZ (flux
    Shenzhen) il donne le niveau du jour mais un seul point, quelle que soit
    la profondeur demandee. Ni l'une ni l'autre ne suffit.
    """

    def fetch() -> Series:
        merged: Series = []
        errors: list[str] = []
        for source in sources:
            try:
                merged += source()
            except Exception as exc:                   # noqa: BLE001
                errors.append(f"{getattr(source, 'label', '?')}: {type(exc).__name__}")
        if not merged:
            raise ValueError(" | ".join(errors) or "aucune source")
        return _clean(merged)

    fetch.label = "+".join(                            # type: ignore[attr-defined]
        getattr(s, "label", "?") for s in sources)
    fetch.basis = basis or getattr(sources[0], "basis", EOD)  # type: ignore[attr-defined]
    return fetch


def derived_usdjpy(cache: dict):
    """USD/JPY reconstruit depuis la BCE : EUR/JPY / EUR/USD.

    Verifie a la main : 186,38 / 1,1377 = 163,80 contre 163,79 chez Yahoo.
    Les series de change de FRED accusent une semaine de retard et sont
    donc inutilisables comme repli.
    """

    def fetch() -> Series:
        eurjpy = dict(ecb("EXR/D.JPY.EUR.SP00.A")())
        eurusd = dict(ecb("EXR/D.USD.EUR.SP00.A")())
        out: Series = []
        for date, jpy in eurjpy.items():
            usd = eurusd.get(date)
            if usd:
                out.append((date, jpy / usd))
        return _clean(out)

    fetch.label = "ecb:derive"                        # type: ignore[attr-defined]
    fetch.basis = ECB_FIX                             # type: ignore[attr-defined]
    return fetch


# ------------------------------------------------------------ instruments ---
# kind pilote l'unite de variation, la borne de plausibilite et la tolerance
# de fraicheur :
#   index/price/fx -> variation en %
#   yield/spread   -> variation en points de base (un 10Y qui passe de 3,20 a
#                     3,25 fait +5 bp, pas "+1,56 %")
#   points         -> variation en points (VIX)

KIND_RULES = {
    "index":  {"unit": "pct", "bound": 8.0,  "stale": 5, "dec": 2},
    "price":  {"unit": "pct", "bound": 10.0, "stale": 5, "dec": 2},
    "fx":     {"unit": "pct", "bound": 3.0,  "stale": 5, "dec": 4},
    "yield":  {"unit": "bp",  "bound": 50.0, "stale": 5, "dec": 3},
    "spread": {"unit": "bp",  "bound": 50.0, "stale": 5, "dec": 3},
    "points": {"unit": "pts", "bound": 8.0,  "stale": 5, "dec": 2},
}

USD_DENOM = {"S&P 500", "Nasdaq 100", "Or", "Brent", "Bitcoin"}


class Instrument:
    def __init__(self, label, zone, kind, sources, stale_days=None, note="",
                 traded_247=False, xcheck_tol=2.0, dec=None, freq="daily",
                 ticker="", ccy=""):
        self.label = label
        self.ticker = ticker          # ticker de marche usuel, pas le symbole source
        self.ccy = ccy                # devise de cotation, ou unite pour un taux
        self.zone = zone
        self.kind = kind
        self.sources = sources
        self.note = note
        self.traded_247 = traded_247
        self.xcheck_tol = xcheck_tol      # tolerance de divergence entre sources
        self.freq = freq                  # daily | monthly — exclut du controle
        rules = KIND_RULES[kind]          #   d'alignement les series mensuelles
        self.unit = rules["unit"]
        self.bound = rules["bound"]
        self.dec = dec if dec is not None else rules["dec"]
        self.stale_days = stale_days if stale_days is not None else rules["stale"]


I = Instrument

SPOT = "prix comptant quotidien"
FUT = "reglement du contrat a terme"

# Neuf instruments, volontairement. Choix de flux verifies a la mesure :
#
#   Chine — le CSI 300 (000300.SS) est le meilleur repere sur le fond mais son
#   flux Yahoo est troue : 18 barres sur un mois, 5 valeurs nulles, derniere
#   barre au 17/07 alors que meta donne le 24/07. La variation quotidienne y est
#   donc incalculable. Le Shanghai Composite a un flux propre (22 barres,
#   1 nulle) et reste l'indice cite par la presse.
#
#   Japon — le TOPIX serait preferable (ponderation par capitalisation, la ou le
#   Nikkei 225 est pondere par les cours et donc deforme par quelques titres
#   cheres). Mais ^TOPX n'existe pas sur Yahoo et 1306.T est un ETF, ecarte pour
#   ne pas substituer un proxy a un indice. Donc Nikkei 225.
#
# Consequence du perimetre : sans EUR/USD, il n'y a plus de conversion en euros.
# Les actifs en dollars sont affiches en dollars, comme demande.

INSTRUMENTS = [
    # --- Actions -----------------------------------------------------------
    # FRED s'est revele plus frais que Yahoo sur les indices US en historique.
    I("S&P 500",       "US", "index", [fred("SP500", CLOSE), yahoo("^GSPC")],
      ticker="SPX", ccy="USD"),
    I("Nasdaq 100",    "US", "index", [fred("NASDAQ100", CLOSE), yahoo("^NDX")],
      ticker="NDX", ccy="USD"),
    I("CAC 40",        "EU", "index", [yahoo("^FCHI")], ticker="CAC", ccy="EUR"),
    I("Euro Stoxx 50", "EU", "index", [yahoo("^STOXX50E")], ticker="SX5E", ccy="EUR"),
    I("Nikkei 225",    "JP", "index", [yahoo("^N225")], ticker="NKY", ccy="JPY"),
    I("Shanghai Comp.", "CN", "index", [yahoo("000001.SS")], ticker="SHCOMP", ccy="CNY"),
    # Flux verifie propre : 21 lignes, aucun trou. Cote en wons.
    I("KOSPI",         "KR", "index", [yahoo("^KS11")], ticker="KOSPI", ccy="KRW"),

    # --- Change ------------------------------------------------------------
    # BCE en primaire, PAS FRED : ses series de change accusent une semaine de
    # retard, verifie a la mesure. A savoir, c'est un fixing de 14h15 CET et non
    # une cloture de seance — le champ basis le dit.
    I("EUR/USD", "FX", "fx",
      [ecb("EXR/D.USD.EUR.SP00.A"), yahoo("EURUSD=X")],
      ticker="EURUSD", ccy="USD"),

    # --- Taux --------------------------------------------------------------
    # Verifie : ^TNX n'est PAS multiplie par 10 sur l'endpoint chart (4,7030
    # contre 4,71 pour DGS10 a la meme date). FRED porte l'historique H.15 de
    # reference, ^TNX apporte la derniere cloture via son champ meta — sans quoi
    # le 10Y retarde d'une seance sur les actions. Les deux references horaires
    # different de quelques bp, d'ou le libelle mixte.
    I("10Y US", "US", "yield",
      [combine(fred("DGS10", H15), yahoo("^TNX"),
               basis="H.15 en historique, cloture pour le dernier point")],
      ticker="US10Y", ccy="%"),
    # Banque de France en primaire (TEC 10 quotidien, cle gratuite), repli FRED
    # mensuel. Serie mensuelle publiee avec ~six semaines de decalage, d'ou le
    # seuil de fraicheur elargi : sinon elle est signalee perimee chaque jour et
    # l'alerte devient du bruit qu'on cesse de lire.
    # Trois sources en cascade. CNBC en primaire : c'est la seule voie identifiee
    # vers un 10 ans francais QUOTIDIEN sans inscription. Webstat ensuite si la
    # cle est presente (source de reference, le TEC 10 de la Banque de France).
    # FRED mensuel en dernier recours.
    # freq reste "daily" et le seuil de fraicheur serre a 5 jours : si CNBC
    # disparait et qu'on retombe sur le mensuel, l'alerte doit se declencher
    # bruyamment plutot que de laisser passer une moyenne pour une cloture.
    I("10Y France", "EU", "yield",
      [cnbc("FR10Y-FR"),
       webstat("FM.D.FR.EUR.FR2.BB.FRMOYTEC10.HSTA"),
       fred("IRLTLT01FRM156N", MONTHLY_AVG)],
      ticker="FR10Y", ccy="%",
      note="CNBC en quotidien ; BdF TEC 10 si cle ; sinon FRED mensuel"),

    # Pendant allemand du 10 ans francais, meme convention et meme cascade.
    #
    # Deux conventions coexistent sur cette echeance et elles ne se rejoignent pas.
    # Releve au 24/07/2026 : l'emprunt de reference cotait 3,17 % chez Bloomberg et
    # 3,183 % dans la presse, la courbe ajustee de la Bundesbank donnait 3,24 %, et
    # CNBC 3,127 %. Trois chiffres pour une meme seance.
    #
    # CNBC en primaire malgre l'ecart de 4 a 5 pb avec Bloomberg : c'est la
    # convention de l'emprunt phare, celle que cite la presse, et la meme source que
    # le 10 ans francais — deux instruments compares dans le brief doivent au moins
    # partager leur mode de calcul, sinon l'ecart France-Allemagne ne veut rien dire.
    # La Bundesbank derriere, comme filet officiel si l'endpoint CNBC disparait : le
    # `basis` bascule alors tout seul et le site affiche la nature reelle.
    #
    # xcheck_tol relevee a 6 % : les deux sources divergent de 3,6 % par
    # construction, et une alerte qui se declenche chaque jour n'est plus une alerte.
    I("10Y Allemagne", "EU", "yield",
      [cnbc("DE10Y-DE"),
       bundesbank("D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A", "DE10Y")],
      ticker="DE10Y", ccy="%", xcheck_tol=6.0,
      note="emprunt de reference via CNBC ; courbe Bundesbank en repli"),

    # --- Matieres premieres / crypto, en dollars --------------------------
    # --- Volatilite -------------------------------------------------------
    # Meilleur cas de recoupement du lot : FRED et Yahoo publient tous deux la
    # cloture CBOE et concordaient a la decimale (18,70 des deux cotes). La
    # fusion est donc sans caveat et ne sert qu'a recuperer la derniere seance
    # via le champ meta de Yahoo. Variation en points, pas en pourcentage.
    I("VIX", "US", "points",
      [combine(fred("VIXCLS", CLOSE), yahoo("^VIX"), basis=CLOSE)],
      ticker="VIX", ccy="pts"),
    # Echelle 0-100, donc une variation de 20 points en un jour serait aberrante.
    # Cote le week-end comme le bitcoin, d'ou traded_247.
    I("Fear & Greed crypto", "CRY", "points", [fng_crypto()],
      traded_247=True, dec=0, ticker="FNG", ccy="0-100",
      note="alternative.me — 0 = peur extreme, 100 = avidite extreme"),

    # --- Matieres premieres / crypto, en dollars --------------------------
    I("Or", "COM", "price", [yahoo("GC=F", FUT)], ticker="XAU", ccy="USD"),
    # Yahoo en primaire : la presse cote le contrat a terme du mois avant, pas le
    # comptant physique, et le comptant FRED retarde de quatre jours. FRED reste
    # en recoupement, ce qui conserve le garde-fou contre l'artefact de contrat.
    # L'ecart comptant/terme de quelques pourcents est structurel (report ou
    # deport), d'ou la tolerance elargie : sinon l'alerte sonne chaque jour.
    I("Brent", "COM", "price",
      [yahoo("BZ=F", FUT), fred("DCOILBRENTEU", SPOT)],
      xcheck_tol=6.0, ticker="BRENT", ccy="USD",
      note="contrat a terme du mois avant ; recoupe avec le comptant FRED"),
    I("Bitcoin", "CRY", "price", [kraken("XBTUSD"), yahoo("BTC-USD", UTC_CLOSE)],
      traded_247=True, ticker="BTC", ccy="USD"),
]


# ------------------------------------------------------------- indicateurs ---

def prev_business_day(today: dt.date) -> dt.date:
    """Derniere journee ouvree strictement avant today (lundi -> vendredi)."""
    d = today - dt.timedelta(days=1)
    while d.weekday() >= 5:                           # 5 = samedi, 6 = dimanche
        d -= dt.timedelta(days=1)
    return d


def _base_source(source: str) -> str:
    """Racine d'un libelle de source : « yahoo:^FCHI+meta » et « yahoo:^FCHI »
    designent la meme serie, releve du champ meta ou de la barre quotidienne."""
    return (source or "").split("+")[0]


def load_stored_series(path: str) -> dict[str, list[tuple[dt.date, float, str]]]:
    """Points deja releves, lus depuis series.csv, par instrument.

    Sert a combler les trous des sources. Cas qui a impose ce chargement : les
    barres quotidiennes de Yahoo n'ont aucun point au 24/07 — elles sautent du 23
    au 27 — pour le CAC, le S&P et le Nikkei a la fois. Cette cloture n'a jamais
    existe que dans meta.regularMarketPrice, champ qui ne la porte que jusqu'a
    l'ouverture suivante. Passe ce moment, la valeur est introuvable a la source
    alors qu'elle est deja dans series.csv, releve le samedi.
    """
    if not os.path.exists(path):
        return {}
    out: dict[str, list[tuple[dt.date, float, str]]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                point = (dt.date.fromisoformat(row["date"]), float(row["value"]),
                         row.get("source", ""))
            except (KeyError, TypeError, ValueError):
                continue                              # ligne abimee : on l'ignore
            out.setdefault(row["instrument"], []).append(point)
    for label in out:
        out[label].sort()
    return out


def merge_stored(stored: Series, fresh: Series) -> Series:
    """Complete la serie fraiche par les points deja releves.

    **Le stocke prime a date egale**, et c'est contre-intuitif : on prefere
    d'ordinaire la donnee la plus recente. Mesure faite en inversant la regle, elle
    condamne exactement ce que ce module cherche a preserver. Pour le 24/07,
    l'archive portait l'or a 4070,80 et le 10 ans francais a 3,980 — les cloturés
    captees le samedi, quand meta.regularMarketPrice les publiait encore. Relancé
    le lundi, le frais ne propose plus pour cette meme date que la barre
    quotidienne, 4067,60, et un releve CNBC a 3,9158. Faire primer le frais
    remplacait donc une cloture par une valeur de moindre qualite, et le brief
    citait 4 070,80 quand la bande d'indicateurs affichait 4 067,60.

    Une cloture archivee a ete captee au plus pres de l'evenement : elle fait foi.
    Le frais n'apporte que les dates absentes. Le prix de cette regle est qu'une
    revision de source sur une seance passee n'est pas reprise — cas rare sur des
    cloturés quotidiennes, et les bornes de plausibilite continuent de s'appliquer
    a la valeur finale.
    """
    points = dict(fresh)
    points.update(dict(stored))
    return sorted(points.items())


def clamp_to_session(series: Series, target: dt.date) -> tuple[Series, list[str]]:
    """Coupe la serie a la seance cible, et rend les dates ecartees.

    Sans cette coupe, le fichier depend de l'heure a laquelle le script tourne.
    Cas reel : lance un lundi a 13h57 UTC, vingt-sept minutes apres l'ouverture de
    New York et l'Europe cotant encore, il a ecrit le S&P 500 a 7452,48 date du
    27/07 et le Brent a 90,47 — des relevés en seance, etiquetes « cloture de
    seance », a cote d'un target_date au 24/07. Le CAC etait intraday, le Nikkei
    une vraie cloture du lundi : un melange qu'aucun lecteur ne peut demeler.

    Couper plutot que refuser d'ecrire : un lancement manuel en pleine seance
    reproduit alors exactement le fichier du matin, au lieu de ne rien faire ou,
    pire, de publier un panache. La collecte de 5h UTC, elle, ne perd rien — a
    cette heure toutes les places citees sont fermees.

    S'applique aussi aux actifs cotant en continu. Le bitcoin et l'indice Fear &
    Greed sont ainsi cales sur la seance actions : un brief qui cite la cloture de
    vendredi ne doit pas donner le bitcoin de dimanche soir dans la meme phrase.
    """
    kept = [(d, v) for d, v in series if d <= target]
    dropped = [d.isoformat() for d, _ in series if d > target]
    # Une serie entierement posterieure a la cible ne devrait pas exister ; si
    # cela arrive, mieux vaut la valeur brute qu'un instrument en erreur.
    return (kept or series), dropped


def check_alignment(entry: dict, inst: Instrument, target: dt.date,
                    today: dt.date) -> None:
    """Compare la date de l'instrument a la date cible attendue.

    C'est la piece qui rend le brief presse coherent avec les chiffres. Aucune
    combinaison de sources ne peut aligner tous les instruments sur une meme
    date : verifie a la main, la donnee de taux du 24/07 n'existait ni chez
    FRED ni chez Yahoo. C'est une contrainte de publication, pas de sourcing.

    Plutot que de pretendre le contraire, on expose l'ecart : le brief n'a le
    droit d'ecrire "hier" que sur les instruments alignes, et doit dater
    explicitement les autres.
    """
    # Une seule cible pour tout le monde, y compris les actifs cotant en continu.
    # Ils avaient auparavant la leur — la journee calendaire precedente —, ce qui
    # datait le bitcoin du dimanche quand les actions etaient au vendredi. Deux
    # dates dans la meme bande d'indicateurs, et un brief oblige de s'en expliquer.
    own_target = target
    entry["target_date"] = own_target.isoformat()

    if inst.freq == "monthly":
        # Une serie mensuelle ne peut structurellement pas etre alignee.
        entry["on_target"] = None
        return

    own = dt.date.fromisoformat(entry["date"])
    # Egalite stricte, et non `>=`. C'est ce comparateur qui laissait passer le
    # relevé du 27/07 comme « aligne » sur une cible au 24/07 : plus recent n'est
    # pas aligne, c'est une autre seance. Le diagnostic annoncait « 15 sur la
    # seance » alors qu'aucun des quinze n'etait a la date cible.
    entry["on_target"] = (own == own_target)
    if own < own_target:
        entry["lag_days"] = (own_target - own).days


def _at_or_before(series: Series, target: dt.date) -> float | None:
    """Derniere valeur a une date <= target (gere week-ends et jours feries)."""
    for date, value in reversed(series):
        if date <= target:
            return value
    return None


def _variation(kind: str, current: float, previous: float | None) -> float | None:
    if previous is None or previous == 0:
        return None
    if kind in ("yield", "spread"):
        return (current - previous) * 100.0     # points de base
    if kind == "points":
        return current - previous               # points
    return (current - previous) / abs(previous) * 100.0


def compute(inst: Instrument, series: Series) -> dict:
    last_date, level = series[-1]
    prev = series[-2][1] if len(series) >= 2 else None

    # Arrondi a la precision d'affichage + 2 : evite de trainer des artefacts de
    # flottant (96.779999 au lieu de 96.78) jusque dans series.csv, qui sert
    # aussi d'export.
    prec = inst.dec + 2

    out: dict = {
        "level": round(level, prec),
        "date": last_date.isoformat(),
        "ticker": inst.ticker,
        "ccy": inst.ccy,
        "zone": inst.zone,
        "kind": inst.kind,
        "unit": inst.unit,
        "dec": inst.dec,
    }
    if inst.note:
        out["note"] = inst.note
    if inst.traded_247:
        out["traded_247"] = True

    change = _variation(inst.kind, level, prev)
    if change is not None:
        out["change"] = round(change, 4)
        # "pct" reste expose pour compatibilite, mais vaut None sur les taux :
        # afficher un pourcentage sur un rendement n'a pas de sens.
        out["pct"] = round(change, 4) if inst.unit == "pct" else None
        # Date de la valeur de comparaison, et nombre de jours couverts.
        # Sans cela, une variation portant sur cinq seances (marche ferme,
        # source en retard, point manquant) se lit comme une variation
        # quotidienne. C'est aussi ce qui permet a l'app d'ecrire "vs 17/07"
        # plutot que de laisser croire "vs la veille".
        prev_date = series[-2][0]
        out["change_from"] = prev_date.isoformat()
        out["change_days"] = (last_date - prev_date).days

    # Variations sur plusieurs horizons
    for label, days in (("w1", 7), ("m1", 30), ("m3", 91)):
        ref = _at_or_before(series, last_date - dt.timedelta(days=days))
        val = _variation(inst.kind, level, ref)
        if val is not None:
            out[label] = round(val, 4)

    ytd_ref = _at_or_before(series, dt.date(last_date.year, 1, 1))
    ytd = _variation(inst.kind, level, ytd_ref)
    if ytd is not None:
        out["ytd"] = round(ytd, 4)

    # Bornes 52 semaines
    window = [v for d, v in series if d >= last_date - dt.timedelta(days=365)]
    if window:
        out["hi52"] = round(max(window), prec)
        out["lo52"] = round(min(window), prec)

    # Percentile de l'amplitude du mouvement du jour sur un an.
    # C'est ce qui distingue "le 2s10s vaut 0,36" de "ce mouvement est dans
    # le 97e percentile de l'annee" — le second fait cliquer, le premier non.
    if change is not None:
        moves = []
        recent = [(d, v) for d, v in series if d >= last_date - dt.timedelta(days=400)]
        for (d0, v0), (d1, v1) in zip(recent, recent[1:]):
            m = _variation(inst.kind, v1, v0)
            if m is not None:
                moves.append(abs(m))
        if len(moves) >= 30:
            rank = sum(1 for m in moves if m <= abs(change))
            out["pctile_1y"] = round(rank / len(moves) * 100.0, 1)

    return out


def check_freshness(entry: dict, inst: Instrument, today: dt.date) -> None:
    """Le mode de defaillance dangereux n'est pas le plantage : c'est la valeur
    perimee servie sans erreur. Mesure en direct : le CSI 300 chez Yahoo etait
    date du 17/07 quand le Shanghai Composite, meme source, etait au 23/07.
    Rien ne signalait l'anomalie.
    """
    last = dt.date.fromisoformat(entry["date"])
    age = (today - last).days
    entry["age_days"] = age
    if age > inst.stale_days:
        entry["stale"] = True
        entry["stale_reason"] = f"cloture vieille de {age} jours"


def check_plausibility(entry: dict, inst: Instrument) -> None:
    """Attrape les erreurs d'unite (le ^TNX x10 de Yahoo) et les artefacts
    de contrat sur les futures."""
    change = entry.get("change")
    if change is not None and abs(change) > inst.bound:
        entry["suspect"] = True
        entry["suspect_reason"] = (
            f"variation {change:+.2f}{inst.unit} au-dela de la borne "
            f"{inst.bound}{inst.unit}"
        )


def check_crosscheck(entry: dict, others: list[tuple[str, Series]],
                     tol: float = 2.0) -> None:
    """Recoupe les sources qui ont repondu, A DATE IDENTIQUE.

    Comparer les dernieres valeurs sans regarder les dates etait un faux
    positif garanti : FRED donnait le Brent du 20/07 a 86,99 et Yahoo celui
    du 24/07 a 96,78, soit "11 % de divergence" qui n'etait qu'un ecart de
    quatre seances. Une source en retard aurait ete signalee suspecte chaque
    jour, et l'alerte serait devenue du bruit qu'on cesse de lire.
    """
    if not others:
        return
    ref_date = dt.date.fromisoformat(entry["date"])
    ref = entry["level"]
    if ref == 0:
        return

    worst = None
    for label, series in others:
        value = dict(series).get(ref_date)
        if value is None:                             # pas de point a cette date
            continue
        div = abs(value - ref) / abs(ref) * 100.0
        if worst is None or div > worst[2]:
            worst = (label, value, div)

    if worst is None:
        entry["crosscheck"] = {"comparable": False}
        return

    label, value, div = worst
    entry["crosscheck"] = {
        "comparable": True,
        "source": label,
        "value": round(value, 6),
        "divergence_pct": round(div, 3),
        "tolerance_pct": tol,
        "ok": div <= tol,
    }
    if div > tol:
        entry["suspect"] = True
        prev = entry.get("suspect_reason", "")
        entry["suspect_reason"] = (
            (prev + " ; " if prev else "")
            + f"divergence {div:.1f}% avec {label} au {ref_date.isoformat()}"
        )


# ------------------------------------------------------------- collecte -----

def fetch_instrument(inst: Instrument, stored: Series | None = None) -> dict:
    """Essaie les sources dans l'ordre. La premiere qui repond fait foi ;
    les suivantes servent au recoupement. Ne leve jamais."""
    primary: dict | None = None
    primary_series: Series = []
    others: list[tuple[str, Series]] = []
    failures: list[str] = []

    for source in inst.sources:
        label = getattr(source, "label", "source")
        try:
            series = source()
            if not series:
                failures.append(f"{label}: serie vide")
                continue
            if primary is None:
                primary_series = series
                # Trace explicitement que le dernier point vient du champ meta
                # et non d'une barre quotidienne : le JSON doit dire d'ou vient
                # la valeur affichee.
                used_meta = getattr(source, "used_meta", False)
                if used_meta:
                    label += "+meta"
                primary = {"source": label,
                           "basis": getattr(source, "basis", EOD),
                           "used_meta": used_meta}
            else:
                others.append((label, series))
        except Exception as exc:                      # noqa: BLE001
            failures.append(f"{label}: {type(exc).__name__}")

    if primary is None:
        return {"error": " | ".join(failures) or "aucune source disponible",
                "zone": inst.zone, "kind": inst.kind}

    today = dt.date.today()
    target = prev_business_day(today)
    # Historique d'abord, coupe ensuite. L'ordre importe : couper une serie a
    # laquelle il manque la seance cible la ramene a l'avant-veille, alors que la
    # valeur est deja dans series.csv.
    # L'archive ne complete la serie que sur les points ecrits par LA MEME source.
    # Sans ce filtre, un point laisse par une source de repli ecrase la primaire tout
    # en gardant son etiquette : le 10 ans allemand affichait 3,240 — la courbe
    # ajustee de la Bundesbank — sous le libelle cnbc:DE10Y-DE, qui cote l'emprunt de
    # reference a 3,127. Deux conventions melangees et une etiquette qui mentait.
    if stored:
        racine = _base_source(primary["source"])
        memes = [(d, v) for d, v, src in stored if _base_source(src) == racine]
        if memes:
            primary_series = merge_stored(memes, primary_series)
    # Coupe avant tout calcul : niveau, variation, bornes 52 semaines et
    # percentile doivent tous porter sur la meme seance close.
    primary_series, dropped = clamp_to_session(primary_series, target)

    entry = compute(inst, primary_series)
    if dropped:
        entry["ignored_after_session"] = dropped
    # Queue de serie destinee a series.csv. N'archiver que le dernier point rendait
    # l'archive trop clairsemee pour les sources qui ne renvoient qu'une cotation
    # courante : le 10 ans francais s'est retrouve avec juin et le 24/07 pour seuls
    # points, et sa variation « quotidienne » portait sur 53 jours. Retiree du JSON
    # avant ecriture, elle n'a pas a grossir latest.json.
    entry["_recent"] = [[d.isoformat(), v] for d, v in primary_series[-8:]]
    entry["source"] = primary["source"]
    # Nature de la valeur portee par la source qui a effectivement repondu,
    # pas par l'instrument : un repli peut changer la nature (le Brent passe
    # du comptant physique au contrat a terme).
    entry["basis"] = primary["basis"]

    # Note sur la fiabilite de la variation quand le dernier point vient du champ
    # meta : verifie par reconstruction depuis les donnees intrajournalieres, les
    # barres quotidiennes de Yahoo portent bien les vraies clotures et leurs dates
    # s'alignent sur les seances locales, sans decalage de fuseau. L'ecart residuel
    # avec le dernier print intraday (8299,09 contre 8280,76 sur le CAC) n'est que
    # l'enchere de cloture, absente des barres de 30 minutes.
    # La variation meta-vers-barre est donc correcte. Un chiffre de presse
    # contradictoire (CAC a +0,1 %) s'est revele etre un intraday, non une cloture.
    # Les garde-fous qui couvrent ce point restent la borne de plausibilite
    # (8 % sur un indice) et change_days, qui signale un ecart de plusieurs seances.

    if failures:
        entry["fallback_notes"] = failures

    check_freshness(entry, inst, today)
    check_plausibility(entry, inst)
    check_crosscheck(entry, others, inst.xcheck_tol)
    check_alignment(entry, inst, target, today)
    return entry


# ---------------------------------------------------------- vue en euros ----

def add_eur_view(markets: dict) -> None:
    """Un S&P a +1 % avec un euro a +1,2 % est un S&P a plat pour un
    investisseur en euros. C'est la seule lecture juste depuis Paris."""
    eur = markets.get("EUR/USD", {})
    rate, rate_prev_pct = eur.get("level"), eur.get("change")
    if not rate:
        return
    for label in USD_DENOM:
        entry = markets.get(label)
        if not entry or "level" not in entry:
            continue
        entry["eur_level"] = round(entry["level"] / rate, 6)
        pct = entry.get("pct")
        if pct is not None and rate_prev_pct is not None:
            # approximation au premier ordre, suffisante a ces amplitudes
            entry["eur_pct"] = round(pct - rate_prev_pct, 4)


# ------------------------------------------------------------- persistance ---

def write_series_csv(path: str, date_label: str, markets: dict) -> int:
    """Serie cumulee append-only, clef (date, instrument, source).

    Point important : la date de la clef est la date de cloture PROPRE a
    l'instrument, pas la date d'execution du job. Sinon le run du lundi matin
    ecrit des donnees de vendredi dans une ligne datee lundi, et la serie est
    decalee pour toujours.

    La source entre dans la clef, et ce n'est pas cosmetique : deux conventions
    peuvent coexister sur une meme echeance. Le 10 ans allemand en donne le cas —
    3,127 % sur l'emprunt de reference chez CNBC contre 3,240 % sur la courbe
    ajustee de la Bundesbank, le meme jour. Sans la source dans la clef, le
    premier releve archive bloquait le second pour toujours, et la relecture ne
    pouvait plus distinguer les deux.

    C'est aussi, gratuitement, ton export CSV cumule : ouvrable dans Excel.
    """
    rows: dict[tuple[str, str, str], tuple[str, str, str, str]] = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                src_row = row.get("source", "")
                rows[(row["date"], row["instrument"], src_row)] = (
                    row["date"], row["instrument"], row["value"], src_row)

    added = 0
    for label, entry in markets.items():
        if "level" not in entry or "date" not in entry:
            continue
        # Source normalisee a la racine : « yahoo:^FCHI » et « yahoo:^FCHI+meta »
        # designent la meme serie, et les archiver separement creait deux lignes
        # jumelles pour une seule cloture. Le fait que la valeur vienne du champ
        # meta est deja porte par `used_meta` dans latest.json.
        src_label = _base_source(entry.get("source", ""))
        # Toute la queue de serie, et non le seul dernier point : c'est ce qui
        # permet a une variation quotidienne de survivre a une source qui ne
        # publie qu'une cotation courante. Append-only, donc les points deja
        # archives ne sont pas touches.
        for date_pt, valeur in entry.get("_recent") or []:
            cle = (date_pt, label, src_label)
            if cle in rows:
                continue
            added += 1
            rows[cle] = (date_pt, label, f"{valeur:.6f}", src_label)

        key = (entry["date"], label, src_label)
        # Vraiment append-only, comme l'annonce le titre : une ligne deja ecrite
        # n'est plus touchee. Elle l'etait auparavant, et un lancement en seance
        # remplacait alors la cloture archivee de l'or, 4070,80 au 24/07, par la
        # barre quotidienne a 4067,60. L'archive perdait en qualite a chaque
        # relance, sans que rien ne le signale.
        if key in rows:
            continue
        added += 1
        rows[key] = (entry["date"], label, f"{entry['level']:.6f}", src_label)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "instrument", "value", "source"])
        for key in sorted(rows):
            writer.writerow(rows[key])
    return added


# ----------------------------------------------------------------- console ---

RESET, GREEN, RED, DIM, YELLOW, BOLD = (
    "\033[0m", "\033[32m", "\033[31m", "\033[2m", "\033[33m", "\033[1m")


def render_console(payload: dict) -> None:
    if os.name == "nt":
        os.system("")                                 # active l'ANSI sur Windows

    log(f"\n{BOLD}Releve marches — {payload['date']}{RESET}")
    log(f"{DIM}{'-' * 78}{RESET}")
    log(f"{'Instrument':<24}{'Niveau':>14}{'Var.':>12}{'Date':>12}  Source")
    log(f"{DIM}{'-' * 78}{RESET}")

    for label, e in payload["markets"].items():
        if "error" in e:
            log(f"{label:<24}{RED}{'ERREUR':>14}{RESET}  {DIM}{e['error'][:34]}{RESET}")
            continue

        change = e.get("change")
        unit = e.get("unit", "pct")
        suffix = {"pct": "%", "bp": "pb", "pts": "pt"}[unit]
        if change is None:
            var = "n/d"
            color = DIM
        else:
            color = GREEN if change >= 0 else RED
            var = f"{change:+.2f}{suffix}"

        flags = ""
        if e.get("stale"):
            flags += f" {YELLOW}[PERIME]{RESET}"
        if e.get("suspect"):
            flags += f" {RED}[SUSPECT]{RESET}"
        if (e.get("change_days") or 0) > 4:
            flags += f" {DIM}(vs {e['change_from']}, {e['change_days']}j){RESET}"

        dec = e.get("dec", 2)
        log(f"{label:<24}{e['level']:>14,.{dec}f}{color}{var:>12}{RESET}"
            f"{e['date']:>12}  {DIM}{e.get('source','')}{RESET}{flags}")

    diag = payload["diagnostics"]
    log(f"{DIM}{'-' * 78}{RESET}")
    log(f"{diag['ok']} ok  |  {len(diag['errors'])} erreurs  |  "
        f"{len(diag['stale'])} perimes  |  {len(diag['suspect'])} suspects")
    log(f"{DIM}Date cible (derniere seance close) : {diag['target_date']} — "
        f"{len(diag['aligned'])} alignes, {len(diag['off_target'])} en retard, "
        f"{len(diag['not_applicable'])} sans objet{RESET}")

    # Lance marches ouverts : le dire franchement. Les valeurs ecrites sont celles
    # de la seance close, mais l'operateur doit savoir que sa collecte de midi n'a
    # rien apporte de plus que celle du matin.
    ecartes = diag.get("ignored_after_session") or []
    if ecartes:
        log(f"{YELLOW}Lancement en seance : {len(ecartes)} instrument(s) avaient "
            f"des points posterieurs au {diag['target_date']}, ecartes pour ne pas "
            f"prendre un relevé intraday pour une cloture.{RESET}")
        for label, dates in ecartes:
            log(f"{DIM}  {label:<24} {', '.join(dates)}{RESET}")
    for label, date, lag in diag["off_target"]:
        log(f"  {YELLOW}retard{RESET}  {label}: {date} ({lag}j) — "
            f"{DIM}ne pas ecrire \"hier\" dans le brief{RESET}")
    for label, reason in diag["stale"]:
        log(f"  {YELLOW}perime{RESET}  {label}: {reason}")
    for label, reason in diag["suspect"]:
        log(f"  {RED}suspect{RESET} {label}: {reason}")
    for label, reason in diag["errors"]:
        log(f"  {RED}erreur{RESET}  {label}: {reason}")


# -------------------------------------------------------------------- main ---

def main() -> int:
    markets: dict[str, dict] = {}

    log(f"{DIM}Collecte de {len(INSTRUMENTS)} instruments "
        f"({WORKERS} en parallele)...{RESET}")
    started = time.monotonic()

    # Les resultats sont recuperes dans le desordre puis reordonnes selon
    # INSTRUMENTS : l'affichage et le JSON gardent un ordre stable, ce qui evite
    # un diff git bruyant a chaque execution.
    stored = load_stored_series(os.path.join(ROOT, "series.csv"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_instrument, inst, stored.get(inst.label)): inst
                   for inst in INSTRUMENTS}
        gathered: dict[str, dict] = {}
        for future in concurrent.futures.as_completed(futures):
            inst = futures[future]
            try:
                gathered[inst.label] = future.result()
            except Exception as exc:                  # noqa: BLE001
                gathered[inst.label] = {"error": f"{type(exc).__name__}: {exc}",
                                        "zone": inst.zone, "kind": inst.kind}

    for inst in INSTRUMENTS:
        entry = gathered[inst.label]
        markets[inst.label] = entry
        state = "ERREUR" if "error" in entry else entry.get("source", "")
        log(f"{DIM}  {inst.label:<24} {state}{RESET}")
    log(f"{DIM}  collecte en {time.monotonic() - started:.0f} s{RESET}")

    add_eur_view(markets)

    # Date de reference = cloture la plus recente parmi les marches qui ferment.
    # Le bitcoin cote le week-end : l'inclure tirait l'en-tete au samedi alors
    # que les actions dataient du jeudi. Et cette date n'est qu'un repere : elle
    # n'est PAS la meme pour tous les instruments. A 6h UTC l'Asie n'a pas fini
    # sa seance — le Nikkei cloture a 6h UTC, le Sensex a 10h UTC. L'app doit
    # afficher la date propre a chaque instrument.
    dates = [e["date"] for e in markets.values()
             if "date" in e and not e.get("traded_247")]
    ref_date = max(dates) if dates else dt.date.today().isoformat()

    target = prev_business_day(dt.date.today())

    diagnostics = {
        "ok": sum(1 for e in markets.values() if "error" not in e),
        "errors": [(k, v["error"]) for k, v in markets.items() if "error" in v],
        "stale": [(k, v.get("stale_reason", "")) for k, v in markets.items()
                  if v.get("stale")],
        "suspect": [(k, v.get("suspect_reason", "")) for k, v in markets.items()
                    if v.get("suspect")],
        # Alignement : ce que le brief presse doit respecter. Les instruments
        # listes ici ne sont PAS a la date cible et ne peuvent donc pas etre
        # decrits comme "hier" — ils doivent etre dates explicitement.
        "target_date": target.isoformat(),
        "aligned": sorted(k for k, v in markets.items() if v.get("on_target")),
        "off_target": sorted(
            [(k, v["date"], v.get("lag_days", 0)) for k, v in markets.items()
             if v.get("on_target") is False],
            key=lambda t: -t[2]),
        "not_applicable": sorted(k for k, v in markets.items()
                                 if v.get("on_target") is None
                                 and "error" not in v),
        # Points ecartes parce que posterieurs a la seance cible. Non vide veut
        # dire que le script a tourne marches ouverts : la valeur retenue est la
        # bonne, mais il faut pouvoir le constater plutot que le deviner.
        "ignored_after_session": sorted(
            (k, v["ignored_after_session"]) for k, v in markets.items()
            if v.get("ignored_after_session")),
    }

    payload = {
        "date": ref_date,
        "target_date": target.isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "eurusd": markets.get("EUR/USD", {}).get("level"),
        "markets": markets,
        "diagnostics": diagnostics,
    }

    os.makedirs(os.path.join(ROOT, "history"), exist_ok=True)
    latest_path = os.path.join(ROOT, "latest.json")
    archive_path = os.path.join(ROOT, "history", f"markets-{ref_date}.json")
    series_path = os.path.join(ROOT, "series.csv")

    # series.csv d'abord : il consomme les queues de serie, que le JSON ne doit pas
    # porter. Les retirer ensuite, avant d'ecrire latest.json.
    added = write_series_csv(series_path, ref_date, markets)
    for entry in markets.values():
        entry.pop("_recent", None)

    for path in (latest_path, archive_path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    render_console(payload)
    log(f"\n{DIM}latest.json + history/markets-{ref_date}.json ecrits ; "
        f"series.csv +{added} lignes{RESET}")

    # Echouer fort : sans cela, une panne partielle reste silencieuse et
    # GitHub ne t'envoie aucun mail. Or un workflow planifie sur depot public
    # finit desactive apres 60 jours d'inactivite, sans redemarrage automatique.
    n_err = len(diagnostics["errors"])
    if n_err > MAX_ERRORS_OK:
        log(f"\n{RED}{n_err} instruments en erreur (seuil {MAX_ERRORS_OK}) "
            f"— sortie en echec pour declencher l'alerte.{RESET}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
