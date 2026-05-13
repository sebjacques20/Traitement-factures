# Changelog

Notes de release pour Traitement de factures. Le format est utilisé par la CI
pour générer `version.json` et alimenter la bannière de mise à jour dans l'app.

Format : `## vX.Y — AAAA-MM-JJ` suivi de bullets `- texte`. Le premier bullet
est affiché en gros sur la bannière, les autres dans le détail.

## v2.4 — 2026-05-13

- Regroupement automatique des factures par PO dans des sous-dossiers (toutes les 1090 ensemble, toutes les 1113 ensemble, etc.)
- Factures sans PO détecté placées dans un dossier "SANS_PO" pour repérage facile
- Le champ Lieu reste disponible comme override manuel (remplace le PO comme nom de sous-dossier si saisi)

## v2.3 — 2026-05-13

- Reconnaissance des PO alphanumériques (BL1090, MR1113, 1107-P1475, KG 11-13)
- Extraction des chiffres canoniques pour grouper les factures par projet
- Log enrichi avec la valeur brute lue par l'IA en plus de la valeur normalisée

## v2.2 — 2026-05-13

- Affichage clair des erreurs API au lieu d'un traitement silencieusement vide
- Détection automatique des problèmes récurrents (clé invalide, crédit épuisé, réseau bloqué)
- Migration vers Claude Sonnet 4.6 (meilleure qualité, support long terme)

## v2.1 — 2026-05-13

- Possibilité de scinder manuellement un groupe trop gros dans la fenêtre de révision
- Meilleure détection des ruptures entre factures (heuristique sur fournisseur/n° facture)
- Sauvegarde automatique du log de traitement dans le dossier de sortie
- Correction du champ Lieu pré-rempli avec le chemin complet

## v2.0 — 2026-03-31

- Première version publique
