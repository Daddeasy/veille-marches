# Brief presse quotidien — instructions de génération

Spécification du brief quotidien. Déclenchée par la commande `/brief` dans
Claude Code, depuis ce dossier. Tourne sur l'abonnement Claude : aucune clé API
facturée, aucun coût au token.

---

## Tâche

1. **Lire `latest.json`** à la racine du dépôt : niveaux et variations réels des
   14 indicateurs, chacun avec sa propre date de clôture.

2. **Chercher** dans la presse financière spécialisée les faits de la dernière
   séance (voir la liste de domaines plus bas).

   **Une recherche dédiée par rubrique, pas une seule recherche marchés
   recyclée.** C'est l'erreur à ne pas commettre : une requête du type « stock
   market close » remonte ce que les articles boursiers mentionnent de la
   géopolitique et de la macro *en passant*, ce qui produit des puces creuses du
   genre « les investisseurs évaluaient les développements du conflit ». Lancer
   au minimum :

   - une requête **géopolitique** sur les faits eux-mêmes (conflits, frappes,
     négociations, détroits, sanctions), pas sur leur effet de marché
   - une requête **macro** sur les publications du jour (PMI, inflation, emploi,
     interventions de banquiers centraux)
   - une requête **micro** sur les résultats et opérations d'entreprises
   - une requête **marchés** pour les indices
   - une requête **obligataire et crédit**, sinon les mouvements de taux ne sont
     jamais expliqués

   Constat de terrain : `boursorama.com` et `zonebourse.com` donnent la meilleure
   couverture francophone d'une séance précise, souvent avec un titre horodaté.
   Les interroger en français, avec la date.

3. **Écrire `news/brief-AAAA-MM-JJ.json`** dans la structure ci-dessous, puis
   ajouter la date **en tête** du tableau `dates` de `news/index.json`.

4. **Lancer `py privacy_check.py`** avant tout commit. Le dépôt est public :
   aucun nom de personne, adresse, téléphone ou nom de société ne doit y entrer.
   Un article de presse peut contenir de telles données — ne jamais les recopier.
   Si le script sort en erreur, corriger le brief et relancer. Ne pas committer
   tant qu'il n'est pas vert.

5. **Commiter et pousser** les deux fichiers.

---

## Structure — l'ordre du weekly interne

| Clé | Titre affiché | Contenu |
|---|---|---|
| `focus` | Le focus du jour | **Un seul** sujet : celui qui a dominé la séance, en un paragraphe. Le thème transverse, pas le plus gros titre. |
| `macro` | Contexte macroéconomique | statistiques, banques centrales, inflation, emploi, activité |
| `geo` | Géopolitique | conflits, commerce, énergie, réglementation |
| `micro` | Contexte microéconomique | résultats, opérations, introductions, notations |
| `actions` | Marchés actions | dans l'ordre **US → Europe → Asie → matières premières et crypto** |
| `obligations` | Marchés obligataires | souverains d'abord, crédit ensuite |

Regroupement **par thème et non par zone** : une histoire de tensions
sino-américaines appartiendrait aux deux zones, un mouvement du pétrole à aucune.
La géographie vit à l'intérieur de la rubrique `actions`, dans l'ordre ci-dessus.

**C'est un quotidien, pas un hebdomadaire.** La structure vient du weekly
interne, le contenu non : une seule séance, celle de `target_date`. Pas de
récapitulatif de semaine, pas de performance depuis le début de l'année, pas de
« graphique de la semaine », pas de tableau de performances — la bande
d'indicateurs en haut du site joue déjà ce rôle, en plus compact.

### Encart FactSet Earnings Insight, dans la rubrique `micro`

Seule exception au « une seule séance » : la rubrique micro ouvre sur un encart
reprenant les **Key Metrics** de *FactSet Earnings Insight*, le point
hebdomadaire sur la saison de résultats du S&P 500. Il donne à la rubrique le
seul chiffre qu'une séance ne fournit pas — où en est la saison dans son
ensemble : taux de surprise, croissance des bénéfices, révisions, valorisation.

C'est un document **hebdomadaire, publié le vendredi**. Il est donc repris à
l'identique pendant toute la semaine qui suit, et **sa date doit être affichée**
sous la forme « au JJ/MM/AAAA ». Sans cette date, un lecteur du jeudi croirait
lire des chiffres de la veille alors qu'ils ont six jours.

**Retrouver le fichier de la semaine.** L'URL est déterministe :

```
https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_MMJJAA.pdf
```

où `MMJJAA` est la date du **vendredi le plus récent**, au format américain
mois-jour-année sur deux chiffres chacun : le 24 juillet 2026 donne
`EarningsInsight_072426.pdf`, le 31 juillet donnera `EarningsInsight_073126.pdf`.
Vérifier par une requête `HEAD` : le fichier du vendredi n'est en ligne qu'en
cours de journée américaine. Sur un 404, reculer d'une semaine et corriger
`as_of` en conséquence — jamais afficher la date demandée si c'est le fichier de
la semaine précédente qui a répondu.

**Lire le PDF.** Aucune extraction de texte n'est disponible par défaut sur le
poste ; `py -m pip install --user pypdf` puis
`PdfReader(chemin).pages[0].extract_text()` suffit, les Key Metrics tiennent
entièrement sur la page 1.

**Ne rien recopier d'autre que les métriques.** Le pied de page 1 porte le nom
de l'analyste signataire et deux adresses e-mail. `privacy_check.py` les
refuserait, et à juste titre : le dépôt est public.

Les chiffres de l'encart **ne viennent pas de `latest.json`** — c'est la seconde
exception admise à la règle sur les chiffres, au même titre qu'une statistique
macro. Elle tient parce qu'ils sont attribués et datés : la source est nommée,
le lien pointe sur le PDF, et `as_of` dit de quel jour ils parlent. Les
reproduire tels quels, sans arrondi ni recalcul, aux conventions françaises près
(virgule décimale, espace avant le pourcent).

Structure de la clé `factset`, à la racine du brief :

```json
"factset": {
  "as_of": "2026-07-24",
  "quarter": "T2 2026",
  "url": "https://advantage.factset.com/hubfs/.../EarningsInsight_072426.pdf",
  "metrics": [
    { "label": "Bilan des publications",
      "text": "Pour le T2 2026, 27 % des sociétés du S&P 500 ayant publié leurs résultats réels, 86 % d'entre elles annoncent un bénéfice par action supérieur aux attentes et 80 % un chiffre d'affaires supérieur aux attentes." }
  ]
}
```

Cinq entrées dans `metrics`, dans l'ordre du document : bilan des publications
(*Earnings Scorecard*), croissance des bénéfices, révisions, prévisions des
entreprises (*guidance*), valorisation.

**Reprendre les cinq puces telles quelles, une phrase entière par puce.** Le
rapport présente ses Key Metrics sous cette forme, et c'est la forme utile : la
phrase porte la comparaison en même temps que le chiffre — « 37,9 %, soit la plus
forte croissance depuis le T3 2021 » se lit d'un trait. Ne pas découper en
libellé, chiffre et commentaire : le site rend l'encart en puces, `label` en gras
suivi de `text`. Traduire, convertir aux conventions françaises, ne rien
résumer ni recalculer.

La clé est optionnelle : si le PDF est introuvable, l'omettre plutôt que la
remplir de valeurs approchées, et le dire dans le compte rendu au lecteur.

### Le calendrier de la semaine, en clôture du brief

Le brief regarde derrière lui — une séance close, des faits acquis. Le dernier
bloc regarde devant : **ce qui tombe cette semaine, et quel jour**. C'est la
seule partie du brief où une date future est légitime.

#### Ce qui entre, et le filtre des trois étoiles

Source retenue : le **calendrier économique d'Investing.com**, restreint aux
événements qu'il classe **trois étoiles**. Le filtre n'est pas cosmétique — la
semaine du 27 juillet 2026 comptait 338 lignes, dont 17 à trois étoiles. Sans
lui, le bloc est illisible.

Cela déroge à la règle générale sur `investing.com`, qui n'autorise le site que
comme source d'article. La dérogation est **une décision explicite du
propriétaire du dépôt**, prise en connaissance de la restriction : les CGU et le
caractère sous licence des données valent pour les cotations, et l'agenda est
extrait manuellement à raison d'une lecture par jour. Les dates des grands
rendez-vous sont par ailleurs **recoupées sur les calendriers officiels** —
`federalreserve.gov` pour le FOMC, `bea.gov` pour le PIB et les revenus des
ménages. C'est ce recoupement qui fait foi en cas de divergence.

S'y ajoutent, hors filtre étoiles : les **résultats d'entreprises de premier
rang** et la publication du prochain *Earnings Insight*. N'y entrent pas les
commentaires, les objectifs de cours, ni rien qui n'ait de date.

#### La semaine entière, complétée jour après jour

Le calendrier couvre la **semaine entière, du lundi au vendredi**, et non les
seuls jours à venir. Les jours passés ne sont pas retirés : le site les estompe
et marque le jour courant. Un lecteur du jeudi veut voir que la réunion de la
Réserve fédérale est derrière lui, pas la chercher.

Le brief étant régénéré chaque matin, **le champ `actual` se remplit à mesure que
les chiffres sortent**. Un attendu de la veille se retrouve doublé du chiffre
publié sans que la ligne bouge, et le site met le publié au premier plan,
l'attendu en retrait. C'est ce qui donne au bloc sa valeur au fil de la semaine :
lundi il annonce, vendredi il récapitule.

**Une prévision n'est admise qu'attribuée**, comme partout ailleurs. `forecast`
porte le consensus du calendrier ; toute autre anticipation va dans un `label`
avec son détenteur nommé — « une chance sur trois donnée à une hausse de 25 pb
selon l'outil FedWatch du CME Group ».

```json
"calendar": {
  "week_of": "2026-07-27",
  "note": "Événements classés trois étoiles par le calendrier économique d'Investing.com, horaires de Paris.",
  "days": [
    { "date": "2026-07-30",
      "events": [
        { "time": "14:30", "zone": "US",
          "label": "Produit intérieur brut du deuxième trimestre, estimation avancée, sur un trimestre",
          "forecast": "+2,3 %", "previous": "+2,1 %" },
        { "label": "Résultats : Amazon et Apple" }
      ] }
  ],
  "sources": [
    { "source": "Réserve fédérale", "url": "https://...", "kind": "reference" },
    { "source": "CNBC", "url": "https://...", "published": "2026-07-27" }
  ]
}
```

`time` en heure de Paris, `zone` en code court, `label` en français et sans
abréviation anglaise. `actual` est absent tant que le chiffre n'est pas sorti.
Une entrée sans `time` est un repère de la journée — des résultats, un
commentaire attribué.

`sources` **passe le même contrôle de date que les puces** :
`brief_check.py` les vérifie sous la rubrique `calendrier`. Un agenda adossé à un
article de la semaine précédente annoncerait des événements déjà passés.

`kind: "reference"` distingue les **pages permanentes** — un calendrier officiel
n'est pas un article, il ne porte aucune date de publication. Le contrôle de
fenêtre est alors sans objet, et le site les signale comme telles au lieu de les
marquer « date non vérifiable », ce qui ferait passer une source faisant autorité
pour douteuse.

Court, donc : **2 à 4 puces par rubrique**, deux à quatre phrases chacune. Pas de
titre sur les puces — un paragraphe suivi de sa source.

### Schéma de `news/brief-AAAA-MM-JJ.json`

```json
{
  "date": "2026-07-27",
  "session": "2026-07-24",
  "generated_at": "2026-07-27T06:20:00Z",
  "focus": {
    "title": "Titre court du sujet dominant",
    "body": "Un paragraphe de trois à cinq phrases."
  },
  "factset": { "as_of": "2026-07-24", "quarter": "T2 2026",
               "url": "https://...", "metrics": [] },
  "sections": {
    "macro": [
      { "text": "Un paragraphe factuel.",
        "source": "Nom du média", "url": "https://...",
        "published": "2026-07-27", "updated": "2026-07-27" }
    ],
    "geo": [], "micro": [], "actions": [], "obligations": []
  }
}
```

Les cinq clés de `sections` doivent être présentes, même vides. L'ordre de rendu
est fixé par le site.

## Indexation : date de publication, pas séance de marché

Le fichier se nomme `news/brief-<AAAA-MM-JJ>.json` où la date est **celle du jour
où le brief est écrit**, et non celle de la séance de marché. Le JSON porte les
deux :

- `date` — jour de publication, celui du nom de fichier
- `session` — séance de marché à laquelle se rapportent les cours de `latest.json`

Les deux diffèrent dès qu'un jour non ouvré s'intercale. **Le brief du lundi
matin est le cas normal, pas l'exception** : il est publié le lundi, les cours
sont ceux de la clôture du vendredi, et il doit couvrir **toute l'actualité
depuis vendredi soir — samedi et dimanche compris**. C'est le brief le plus utile
de la semaine, celui qui rattrape deux jours de géopolitique et de communiqués.

La fenêtre d'actualité à couvrir va donc de la **publication du brief précédent**
(voir la première date de `news/index.json`) à maintenant. Pas « la dernière
séance ».

Ne jamais écrire que le marché a bougé pendant un jour non ouvré. Les cours sont
ceux de `session` ; les faits peuvent être postérieurs. Le site affiche les deux
dates séparément.

**Refuser d'écrire uniquement si un brief porte déjà la date de publication du
jour.** Une séance déjà couverte n'est pas un motif de refus : deux briefs
successifs peuvent légitimement citer la même clôture.

### Date de l'article — contrôle obligatoire

Chaque puce porte deux champs de date, qu'il ne faut **jamais confondre** :

- **`published`** — date de publication d'origine, `AAAA-MM-JJ`
- **`updated`** — date de dernière modification si elle est visible, sinon absente

La distinction n'est pas cosmétique. Un article publié en mars et remis à jour
hier n'est pas un article d'hier : son corps peut être ancien.

**Le piège des live blogs.** Une page de suivi en continu porte dans son URL la
date de sa *création*, pas celle de son contenu. Exemple vécu dans ce dépôt :
`cnbc.com/2026/07/23/stock-market-today-live-updates.html` a été citée pour la
séance du 24 — la date de l'URL indiquait le 23. Elle n'était pas fausse, elle ne
répondait simplement pas à la question. Préférer un article figé ; si l'on cite un
live blog, le signaler dans `updated` et vérifier que le passage cité porte bien
sur la fenêtre couverte.

**Comment établir la date** :

1. Le titre, quand il l'affiche — Boursorama horodate les siens
   (`- 24/07/2026 à 18:02 -`). Attention : c'est souvent l'heure de mise à jour.
2. L'URL — indice utile mais **non probant** pour les pages mises à jour.
3. **Aller lire la page** quand un doute subsiste. C'est le seul moyen fiable de
   distinguer publication et mise à jour.

**Si la date de publication reste introuvable, écarter l'article.** Ne pas
laisser `published` à `null` en se disant que ce n'est pas grave : un article non
daté peut avoir six mois, et rien ne le signalera au lecteur.

**Fenêtre acceptable** : le *contenu* doit porter sur la période allant de la
publication du brief précédent à maintenant. C'est le contenu qui décide, pas
l'horodatage de la page.

### Schéma de `news/index.json`

```json
{ "dates": ["2026-07-24", "2026-07-23"] }
```

Ordre décroissant des **dates de publication** — le site affiche le premier
élément par défaut.

---

## Conventions d'écriture

Reprises du weekly interne :

- Points de base : **« pb »**, jamais « bp ». « en hausse de 8 pb ».
- Nombres à la française : virgule décimale, espace comme séparateur de milliers,
  espace avant le signe pourcent. « 7 411,98 », « +1,3 % ».
- Citer un niveau **avec son point de comparaison**, qui est toujours la
  **séance précédente** : « à 4,679 %, contre 4,703 % la veille, soit une baisse
  de 2,4 pb ». Jamais une comparaison hebdomadaire ou mensuelle : ce brief porte
  sur une seule séance.
- Nommer les instruments en français : « le 10 ans américain », « le Bund »,
  « l'OAT ».

---

## Règle absolue : résumer, ne pas interpréter

L'outil restitue ce que la presse a publié. Il ne commente pas, ne relie pas, ne
conclut pas.

**Interdit :**

- **Toute causalité absente de l'article.** Ne pas écrire « le repli du pétrole a
  soulagé la courbe obligataire » si l'article ne l'affirme pas. Deux faits dans
  la même séance ne se relient pas d'eux-mêmes.
- **Les qualificatifs d'ambiance** : « séance à deux vitesses », « marché
  fébrile », « prudence des investisseurs ». Des jugements déguisés en
  description.
- **Les jugements de valeur** : « ce qui fragilise le mouvement », « signe
  rassurant », « inquiétude contenue ».
- **Toute prévision** qui ne soit pas attribuée à une source nommée.

**Attendu :** chaque phrase traçable à l'article cité. Test avant d'écrire :
*pourrais-je souligner cette phrase dans l'article source ?* Si non, elle ne va
pas dans le brief.

Quand une causalité est réellement dans l'article, l'attribuer : « selon
Bloomberg », « d'après CNBC ». La différence entre restituer et affirmer tient à
cette attribution.

---

## Règle absolue sur les chiffres

**Tout chiffre cité provient de `latest.json`.** Sans exception.

Un nombre lu dans un article n'est pas repris tel quel : soit il existe dans
`latest.json` et on utilise cette valeur, soit on décrit le fait sans le
chiffrer. Si la presse et le pipeline divergent, le pipeline fait foi et la
divergence est mentionnée.

**Seule exception** : un chiffre qui n'existe pas dans le pipeline par nature —
un plus-haut intraday, un titre individuel, un volume, une statistique macro —
peut être cité, mais **toujours attribué** (« le Brent, qui avait franchi les
100 dollars »). Les niveaux de clôture, eux, viennent exclusivement du pipeline.

Cas réel : Bloomberg donnait le CAC 40 à +0,1 % là où le pipeline calculait
+0,88 %. Vérification faite, le chiffre de presse était un relevé en séance, pas
une clôture — le pipeline avait raison. Un chiffre de presse n'est pas plus
fiable qu'un chiffre calculé.

Précautions :

- Variations de taux en **points de base**, jamais en pourcentage. Un 10 ans qui
  passe de 3,20 à 3,25 fait **+5 pb**, pas « +1,56 % ».
- Vérifier `change_days` avant d'écrire « hier ». Au-delà de 4, la variation
  couvre plusieurs séances : le dire.
- Un instrument marqué `stale` ou `suspect` n'est pas cité comme un fait établi.
- Chaque puce porte une `url` cliquable.

### Règle d'alignement — la cohérence texte / chiffres

`latest.json` porte un champ `target_date` : la dernière séance close, celle dont
parle la presse ce matin. Chaque instrument porte un booléen `on_target`.

| `on_target` | Signification | Ce que le brief peut écrire |
|---|---|---|
| `true` | sur la séance cible | « hier », « en clôture » |
| `false` | source en retard | date explicite obligatoire, jamais « hier » |
| `null` | série mensuelle | qualifier de mensuel, citer le mois |

Sans cette règle, le texte affirme que le marché obligataire a bougé hier alors
que le chiffre affiché date de l'avant-veille.

### Nature des valeurs

Le champ `basis` dit ce que chaque nombre est réellement :

- `cloture de seance` — vraie clôture (indices actions, VIX)
- `fixing BCE 14h15 CET` — EUR/USD : un fixing de milieu de journée, **pas** une
  clôture. Écrire « l'euro s'établissait à… », pas « l'euro a clôturé à… »
- `releve H.15, ~15h30 New York` — taux américains
- `fixing CNO quotidien` — TEC 10 français
- `reglement du contrat a terme` — or, Brent
- `cloture 00h UTC` — bitcoin

---

## Presse : domaines accessibles

Chercher dans la presse **financière spécialisée**, pas généraliste. Une
recherche non dirigée dérive vers des agrégateurs et des reprises de dépêches —
c'est là que naissent les chiffres faux.

**Contrainte vérifiée en testant 54 domaines.** Certains titres bloquent le robot
d'indexation : les lister dans `allowed_domains` fait échouer la requête avec une
erreur 400.

**Bloqués — ne jamais les inclure :** `reuters.com`, `wsj.com`, `ft.com`,
`barrons.com`, `marketwatch.com`, `investors.com`, `economist.com`,
`apnews.com`, `businessinsider.com`, `theguardian.com`, `telegraph.co.uk`,
`thetimes.co.uk`, `lesechos.fr`, `agefi.fr`, `lemonde.fr`, `lefigaro.fr`,
`latribune.fr`, `capital.fr`, `challenges.fr`, `bfmtv.com`, `boursier.com`,
`faz.net`, `expansion.com`, `nrc.nl`

**Accessibles :**

| Zone | Spécialisée | Primaire officielle |
|---|---|---|
| **US** | `bloomberg.com`, `cnbc.com`, `morningstar.com`, `fortune.com`, `axios.com`, `semafor.com` | `federalreserve.gov`, `home.treasury.gov`, `bls.gov`, `bea.gov` |
| **EU** | `handelsblatt.com`, `boerse-online.de`, `ilsole24ore.com`, `eleconomista.es`, `fd.nl`, `euronews.com` | `ecb.europa.eu`, `ec.europa.eu` |
| **FR** | `boursorama.com`, `investir.lesechos.fr`, `zonebourse.com`, `abcbourse.com`, `tradingsat.com`, `morningstar.fr` | `banque-france.fr`, `insee.fr`, `aft.gouv.fr`, `amf-france.org` |
| **JP** | `asia.nikkei.com`, `japantimes.co.jp` | `boj.or.jp`, `mof.go.jp` |
| **CN** | `caixinglobal.com`, `scmp.com` | `pbc.gov.cn`, `stats.gov.cn` |
| **KR** | `bloomberg.com`, `asia.nikkei.com` | `bok.or.kr` |

Deux contournements utiles :

- **`boursorama.com` republie les dépêches Reuters en français**, y compris ses
  revues de presse économique par pays. C'est la voie d'accès au contenu Reuters,
  dont le domaine propre est fermé. Citer « Reuters via Boursorama ».
- **`investir.lesechos.fr` est accessible** alors que `lesechos.fr` est bloqué.

Sur `investing.com` et `tradingeconomics.com` : accessibles, citables comme
**source d'article**. Jamais comme source de prix — CGU restrictives et données
sous licence tierce. Lire un article publié et moissonner un flux de cotations
sont deux choses différentes.

Règles de sourcing :

- Sur une **statistique macro**, la source primaire prime sur son commentaire de
  presse. Citer l'institution qui publie.
- Un fait présent dans une seule source non officielle est recoupé ou écarté.
- **Jamais de nom de personne physique** dans le brief, sauf dirigeant ou
  responsable public s'exprimant à titre officiel (« le président de la Banque
  centrale européenne »). Pas de coordonnées, jamais.
- Préférer un article **daté de la fenêtre couverte**. Une reprise plus tardive
  ajoute du bruit sans information. Voir le contrôle de date ci-dessous.
