---
description: Génère le brief presse du jour et le publie sur le site
---

Génère le brief presse quotidien de ce dépôt.

## Marche à suivre

1. **Relever les cours d'abord.** Lance `py market_prices.py`, puis
   `py selfcheck.py`. Si la collecte échoue sur plus de quatre indicateurs,
   arrête-toi et dis-le : un brief écrit sur des cours faux est pire que pas de
   brief.

2. **Lis `news/BRIEF_PROMPT.md`** et suis-le à la lettre. C'est la spécification
   complète : structure des rubriques, conventions d'écriture, règles sur les
   chiffres, domaines de presse autorisés et interdits.

3. **Lis `latest.json`.** Tous les niveaux de clôture cités doivent en venir.
   `target_date` donne la séance à couvrir. Respecte `on_target` : n'écris
   « hier » que sur les instruments dont il vaut `true`.

4. **Une recherche dédiée par rubrique** — géopolitique sur les faits eux-mêmes,
   macro sur les publications du jour, micro sur les résultats, marchés sur les
   indices, et une requête obligataire. Une requête unique produit des puces
   creuses.

5. **Écris `news/brief-<target_date>.json`**, ajoute la date en tête de
   `news/index.json`.

6. **Lance `py privacy_check.py`.** Le dépôt est public. Ne commite pas tant
   qu'il n'est pas vert.

7. **Commite et pousse** sur `main`. Utilise
   `git -c user.name="veille-marches" -c user.email="noreply@localhost" commit`
   pour ne pas exposer d'adresse personnelle dans l'historique public.

8. **Donne-moi le lien** vers `https://daddeasy.github.io/veille-marches/` et
   résume en trois lignes ce que dit le brief, pour que je sache s'il vaut la
   peine d'être ouvert.

## Si un jour de bourse est férié

Si `target_date` est identique à celle du brief déjà publié, ne réécris rien :
dis-le et arrête-toi. Un brief en doublon écrase l'archive du jour précédent.
