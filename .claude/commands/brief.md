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

5. **Écris `news/brief-<date du jour>.json`** — indexé sur la date de
   PUBLICATION, pas sur la séance. Le JSON porte `date` (aujourd'hui) et
   `session` (la `target_date` de `latest.json`). La fenêtre d'actualité va de la
   publication du brief précédent à maintenant : un lundi, tout le week-end est
   inclus.

6. **Lance `py privacy_check.py`.** Le dépôt est public. Ne commite pas tant
   qu'il n'est pas vert.

7. **Commite et pousse** sur `main`. Utilise
   `git -c user.name="veille-marches" -c user.email="noreply@localhost" commit`
   pour ne pas exposer d'adresse personnelle dans l'historique public.

8. **Donne-moi le lien** vers `https://daddeasy.github.io/veille-marches/` et
   résume en trois lignes ce que dit le brief, pour que je sache s'il vaut la
   peine d'être ouvert.

## Si un jour de bourse est férié

Refuse d'écrire seulement si un brief porte déjà la date d'aujourd'hui. Une
séance déjà citée n'est pas un motif de refus : le brief du lundi cite la clôture
du vendredi, comme celui du vendredi soir.
