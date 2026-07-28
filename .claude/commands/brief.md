---
description: Génère le brief presse du jour et le publie sur le site
---

Génère le brief presse quotidien de ce dépôt.

## Marche à suivre

1. **`py refresh.py start`.** Relève les cours, contrôle la cohérence
   pipeline / app, et écrit `news/brief-<aujourd'hui>.json` préremplí : dates à
   jour, encart FactSet et calendrier reportés de la veille, rubriques vides. Il
   affiche les chiffres du pipeline prêts à citer, avec les drapeaux qui
   interdisent de les citer — suspect, périmé, en retard, variation
   pluri-séances. Il refuse d'écrire si un brief porte déjà la date du jour.

   Si la collecte échoue, il s'arrête : un brief écrit sur des cours faux est
   pire que pas de brief.

2. **Lis `news/BRIEF_PROMPT.md`** et suis-le à la lettre. C'est la spécification
   complète : structure des rubriques, conventions d'écriture, règles sur les
   chiffres, domaines de presse autorisés et interdits.

3. **Une recherche dédiée par rubrique** — géopolitique sur les faits eux-mêmes,
   macro sur les publications du jour, micro sur les résultats, marchés sur les
   indices, et une requête obligataire. Une requête unique produit des puces
   creuses.

   **Élargis aux sources anglophones de qualité et traduis.** Un brief à 76 %
   sur un seul média est arrivé, et il ratait quatre faits : sur des frappes
   américaines en Iran, les sources de premier rang sont anglophones. Viser une
   dizaine d'articles distincts et aucune source au-delà de la moitié des puces.

4. **Écris les rubriques et le focus** dans le fichier prérempli. Tout chiffre de
   clôture vient de la table affichée à l'étape 1. Les relevés intraday et les
   chiffres de presse sont cités attribués, avec leur heure.

5. **Mets à jour ce que le report ne peut pas deviner**, signalé à l'étape 1 :
   les chiffres publiés du calendrier (champ `actual`), le calendrier entier si
   l'on entre dans une nouvelle semaine, et l'encart FactSet le vendredi.

6. **`py refresh.py finish`.** Vérifie la date de publication réelle de chaque
   article cité, passe le contrôle de confidentialité, indexe le brief, commite
   avec un auteur neutre et pousse. S'arrête à la moindre alerte plutôt que de
   publier. `--no-push` pour tout contrôler sans rien commiter.

7. **Donne-moi le lien** vers `https://daddeasy.github.io/veille-marches/` et
   résume en trois lignes ce que dit le brief, pour que je sache s'il vaut la
   peine d'être ouvert. Signale les chiffres que tu as écartés et pourquoi.

## Ce qui prend du temps, et ce qui n'en prend pas

Mesuré : l'outillage tient en huit secondes — `market_prices` 3,1 s,
`brief_check` 4,6 s, les deux autres moins d'une seconde. Le temps part dans la
recherche de presse, qui demande de lire, et il partait aussi dans le recopiage
du calendrier et de l'encart FactSet, que `refresh.py` reporte désormais.

Donc : ne pas multiplier les allers-retours. Une recherche par rubrique, ne
récupérer que les articles qu'on citera, et écrire le fichier d'un trait plutôt
qu'en vingt retouches.

## Si un jour de bourse est férié

Refuse d'écrire seulement si un brief porte déjà la date d'aujourd'hui —
`refresh.py start` s'en charge. Une séance déjà citée n'est pas un motif de
refus : le brief du lundi cite la clôture du vendredi, comme celui du vendredi
soir.
