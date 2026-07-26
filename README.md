# Veille marchés

Relevé quotidien de 22 instruments (indices, taux, changes, matières premières,
crypto) + brief presse par zone. Gratuit, sans clé API, sans dépendance Python.

- **`market_prices.py`** — collecte multi-sources avec repli et contrôles de fiabilité
- **`.github/workflows/main.yml`** — exécution automatique en jours ouvrés
- **`index.html`** — le site, servi par GitHub Pages
- **`selfcheck.py`** — vérifie la cohérence entre le pipeline et l'app
- **`news/BRIEF_PROMPT.md`** — instructions du brief presse quotidien

---

## Mise en place

### 1. Créer le dépôt

```bash
cd chemin/vers/veille-marches
git init -b main
git add .
git commit -m "Init veille marches"
gh repo create veille-marches --public --source=. --push
```

Le dépôt doit être **public** : c'est ce qui permet à GitHub Pages de servir le
site gratuitement. Les données sont des cours de bourse, rien de confidentiel.
Ne jamais y mettre de secret.

Sans la CLI `gh` : créer le dépôt public à la main sur github.com, puis

```bash
git remote add origin https://github.com/VOTRE-COMPTE/veille-marches.git && git push -u origin main
```

### 2. Autoriser le workflow à écrire

Settings → Actions → General → *Workflow permissions* →
**Read and write permissions** → Save.

Sans cela le workflow collecte les données mais le push échoue.

### 3. Activer GitHub Pages

Settings → Pages → *Source* : **Deploy from a branch** →
Branch **main**, dossier **/ (root)** → Save.

Le site est alors sur `https://VOTRE-COMPTE.github.io/veille-marches/`.

Aucune configuration d'URL n'est nécessaire dans le code : le site lit
`latest.json` en **same-origin**, puisqu'il est servi depuis le dépôt qui le
contient. C'est ce qui évite tout problème de CORS.

### 4. Premier relevé

Actions → *Relevé marchés quotidien* → **Run workflow**.

Puis, en local, pour vérifier :

```bash
py market_prices.py && py selfcheck.py
```

### 5. Brief presse quotidien

Le brief a besoin d'un modèle avec recherche web. Le faire tourner dans GitHub
Actions exigerait une clé API facturée au token ; le faire tourner via Claude Code
utilise l'abonnement, sans surcoût.

Créer une tâche planifiée en jours ouvrés qui exécute les instructions de
`news/BRIEF_PROMPT.md` — dans Claude Code :

```
/schedule chaque jour ouvré à 7h30 : exécuter les instructions de news/BRIEF_PROMPT.md
```

Tant qu'aucun brief n'existe, le site affiche la bande marchés seule.

---

## Sources

Le principe : aller chez **l'émetteur de la donnée** plutôt que chez un
agrégateur. Les banques centrales et les Trésors ont pour mandat de publier — ils
n'ont ni anti-bot, ni CGU commerciales, ni intérêt à bloquer un client.

| Source | Instruments | Fraîcheur mesurée |
|---|---|---|
| **FRED** (Fed de St. Louis) | indices US, taux US, VIX, spreads | J-1 à J-2 |
| **BCE** (Data Portal) | EUR/USD, USD/JPY dérivé, 10Y zone euro | J-1 |
| **MOF Japon** | 10Y japonais | quotidien, J-1 |
| **Banque de France** (Webstat) | TEC 10 français | quotidien, clé gratuite |
| **Kraken** | Bitcoin | temps réel |
| **Yahoo Finance** | indices hors US, or, Brent, DXY | J-1 |

Trois constats issus des mesures, contre-intuitifs :

- **FRED est plus frais que Yahoo sur les indices US** en données historiques.
- **Les séries de change de FRED ont une semaine de retard.** Elles sont donc
  inutilisables comme repli sur EUR/USD ou USD/JPY — un repli qui renvoie de la
  donnée périmée est pire que pas de repli. D'où la BCE en source primaire.
- **`^TNX` n'est pas multiplié par 10** sur l'endpoint `chart`, contrairement à
  une croyance répandue : 4,7030 contre 4,71 pour `DGS10` à la même date.

Stooq n'est pas utilisé : le site sert désormais un challenge JavaScript aux
clients non-navigateurs depuis les IP de datacenter, donc inaccessible depuis un
runner GitHub. Les agrégateurs type Investing.com sont exclus : conditions
d'utilisation restrictives, anti-bot, et données sous licence tierce.

### Le piège de la dernière clôture

Yahoo publie la clôture de la séance la plus récente dans
`meta.regularMarketPrice`, et ne l'ajoute au tableau des barres quotidiennes
qu'avec du retard. Un script qui ne lit que les barres retarde donc d'une séance
sur la majorité des instruments — c'était le cas ici sur 13 des 22.

Preuve que le champ `meta` porte bien la clôture officielle et non un cours
intraday : sur le S&P il donnait 7 411,98 au 24/07, valeur identique au chiffre
publié par FRED.

Le garde-fou est temporel : `regularMarketTime` est rafraîchi en continu tant
qu'un marché est ouvert, donc un horodatage vieux de plus de deux heures signifie
que la séance est close. À 6h UTC cela accepte le S&P et le CAC, et refuse
Shanghai et le Sensex encore en séance — dont on conserve la barre de la veille
plutôt que d'injecter un cours de séance en cours.

### Clé Banque de France (optionnelle)

Le 10Y France en quotidien passe par le TEC 10 de Webstat. Clé gratuite sur
[webstat.banque-france.fr/signup](https://webstat.banque-france.fr/signup),
limite de 10 000 appels par jour.

1. Créer le compte, récupérer l'identifiant client.
2. Dépôt → Settings → Secrets and variables → Actions → New repository secret,
   nommé `WEBSTAT_CLIENT_ID`.
3. Ajouter dans le workflow, sous l'étape de collecte :
   `env: { WEBSTAT_CLIENT_ID: "${{ secrets.WEBSTAT_CLIENT_ID }}" }`

Sans clé, la source est ignorée et le repli FRED mensuel prend le relais — rien
ne casse, l'instrument est simplement libellé mensuel.

La documentation d'authentification de Webstat étant derrière un login, le nom
exact du porteur de clé n'a pas pu être vérifié : la clé est envoyée à la fois en
en-tête `X-IBM-Client-Id` et en paramètre `client_id`, et le parseur accepte
plusieurs formes de réponse. À confirmer au premier run.

---

## Les six contrôles de fiabilité

La robustesse ne vient pas du nombre de sources — la plupart des « milliers de
sources » du web sont des revendeurs des trois mêmes flux en amont, ce qui donne
une panne corrélée, pas une redondance. Elle vient de ces contrôles.

1. **Dernière valeur non nulle**, jamais le dernier élément. Yahoo remplit ses
   séries de `null` pour les périodes non cotées.
2. **Fraîcheur par instrument.** Le mode de défaillance dangereux n'est pas le
   plantage, c'est la valeur périmée servie sans erreur. Constaté : le CSI 300
   sur le flux Shanghai datait du 17/07 quand le Shanghai Composite, même source,
   était au 23/07 — sans aucun signal.
3. **Bornes de plausibilité.** Attrape les erreurs d'unité (le `^TNX` ×10 de
   Yahoo) et les artefacts de contrat.
4. **Recoupement entre sources, à date identique.** Comparer les dernières
   valeurs sans regarder les dates produisait un faux positif garanti : « 11 % de
   divergence » sur le Brent qui n'était qu'un écart de quatre séances.
5. **Séries plutôt que points.** Une requête au lieu de deux, et l'on obtient
   gratuitement les variations 1S/1M/3M/YTD, les percentiles et les sparklines.
6. **Échec bruyant.** Au-delà de 4 instruments en erreur, le job sort en code 1
   pour déclencher le mail GitHub — mais commite quand même ce qui a été collecté.

## L'alignement, ou la cohérence texte / chiffres

C'est la contrainte centrale : le brief presse et les chiffres affichés doivent
parler de la même séance, sinon l'outil se contredit tout seul.

Aucune combinaison de sources ne peut aligner les 22 instruments sur une même
date — c'est une contrainte de publication, pas de sourcing. Vérifié : la donnée
de taux du 24/07 n'existait ni chez FRED ni chez Yahoo au moment du relevé.

Le pipeline calcule donc une **date cible** (la dernière séance close avant
aujourd'hui) et marque chaque instrument :

| `on_target` | Signification | Ce que le brief peut écrire |
|---|---|---|
| `true` | sur la séance cible | « hier », « en clôture » |
| `false` | source en retard | date explicite obligatoire, jamais « hier » |
| `null` | série mensuelle | qualifier de mensuel, citer le mois |

Le site affiche un badge `J−n` sur les instruments concernés et les nomme en
clair sous l'en-tête. Quatre retardent structurellement, faute de source gratuite
publiant le jour même : 2Y américain, 10Y japonais, courbe 10Y zone euro, spread
high yield.

## La nature des valeurs

Un fixing de 14h15 et une clôture de séance ne sont pas la même chose. Chaque
instrument porte un champ `basis` qui le dit, et le site l'affiche :

| `basis` | Instruments |
|---|---|
| clôture de séance | indices actions, VIX |
| **fixing BCE 14h15 CET** | EUR/USD, USD/JPY — **pas** une clôture |
| relevé H.15, ~15h30 New York | taux américains |
| fixing CNO quotidien | TEC 10 français |
| règlement du contrat à terme | or, Brent |
| clôture 00h UTC | bitcoin |

---

## Limites connues

- **8 instruments dépendent de Yahoo seul** (CAC 40, Euro Stoxx 50, Nikkei,
  CSI 300, Shanghai, Sensex, or, DXY). Ces indices sont sous licence et leurs
  propriétaires ne les publient pas gratuitement. Si Yahoo change son schéma, ces
  tuiles passent en « indisponible » — un trou visible plutôt qu'un chiffre faux.
- **Le 10Y France est mensuel sans la clé Banque de France** (voir plus haut).
  Ni l'ECB ni aucune source keyless ne publie la France en quotidien : les séries
  pays du dataset ECB `FM` renvoient 404, seule la mensuelle répond.
- **Le 10Y « zone euro AAA » n'est pas le Bund** : c'est un composite des
  souverains euro notés AAA. Un vrai Bund demanderait l'API de la Bundesbank.
- **Le cron est en UTC, sans heure d'été** : 06:00 UTC donne 8h à Paris en été,
  7h en hiver. GitHub ne permet pas de fixer un horaire local.
- **À 6h UTC, l'Asie n'a pas fini sa séance** — le Nikkei clôture à 6h UTC, le
  Sensex à 10h. Les indices asiatiques renvoient la veille. Chaque instrument
  porte donc sa propre date, affichée sur sa tuile.
- **Le CSV du MOF japonais** est un fichier gouvernemental en Shift-JIS avec des
  dates en ère impériale. Le format peut changer sans préavis ; le repli FRED
  mensuel reste en place derrière.
- **Un workflow planifié sur dépôt public est désactivé après 60 jours
  d'inactivité du dépôt.** Le commit quotidien le maintient en vie, mais une
  panne non remarquée finit par éteindre le projet définitivement. C'est la raison
  d'être du contrôle n° 6.
