# Changelog

Notes de release pour Traitement de factures. Le format est utilisé par la CI
pour générer `version.json` et alimenter la bannière de mise à jour dans l'app.

Format : `## vX.Y — AAAA-MM-JJ` suivi de bullets `- texte`. Le premier bullet
est affiché en gros sur la bannière, les autres dans le détail.

## v2.1 — 2026-05-13

- Possibilité de scinder manuellement un groupe trop gros dans la fenêtre de révision
- Meilleure détection des ruptures entre factures (heuristique sur fournisseur/n° facture)
- Sauvegarde automatique du log de traitement dans le dossier de sortie
- Correction du champ Lieu pré-rempli avec le chemin complet

## v2.0 — 2026-03-31

- Première version publique
