# Brief presse quotidien — instructions de génération

Prompt exécuté chaque matin par une tâche planifiée Claude Code. Il tourne sur
l'abonnement Claude : aucune clé API facturée, aucun coût au token.

---

## Tâche

1. **Lire `latest.json`** à la racine du dépôt : niveaux et variations réels des
   14 indicateurs, chacun avec sa propre date de clôture.

2. **Chercher** dans la presse financière spécialisée les faits de la dernière
   séance (voir la liste de domaines plus bas).

3. **Écrire `news/brief-AAAA-MM-JJ.json`** dans la structure ci-dessous, puis
   ajouter la date **en tête** du tableau `dates` de `news/index.json`.

4. **Commiter et pousser** les deux fichiers.

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

Court, donc : **2 à 4 puces par rubrique**, deux à quatre phrases chacune. Pas de
titre sur les puces — un paragraphe suivi de sa source.

### Schéma de `news/brief-AAAA-MM-JJ.json`

```json
{
  "date": "2026-07-24",
  "generated_at": "2026-07-25T06:20:00Z",
  "focus": {
    "title": "Titre court du sujet dominant",
    "body": "Un paragraphe de trois à cinq phrases."
  },
  "sections": {
    "macro": [
      { "text": "Un paragraphe factuel, avec attribution.",
        "source": "Nom du média", "url": "https://..." }
    ],
    "geo": [], "micro": [], "actions": [], "obligations": []
  }
}
```

Les cinq clés de `sections` doivent être présentes, même vides. L'ordre de rendu
est fixé par le site.

### Schéma de `news/index.json`

```json
{ "dates": ["2026-07-24", "2026-07-23"] }
```

Ordre décroissant — le site affiche le premier élément par défaut.

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
- Préférer un article **daté de la séance concernée**. Une reprise plus tardive
  ajoute du bruit sans information.
