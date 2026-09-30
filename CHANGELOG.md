# Changelog

Notes de release pour Traitement de factures. Le format est utilisé par la CI
pour générer `version.json` et alimenter la bannière de mise à jour dans l'app.

Format : `## vX.Y — AAAA-MM-JJ` suivi de bullets `- texte`. Le premier bullet
est affiché en gros sur la bannière, les autres dans le détail.

## v2.9 — 2026-09-30

- Correction Mac : la bannière de mise à jour ne s'affichait jamais (certificats SSL inaccessibles dans le bundle) — vérification et téléchargement passent maintenant par les certificats certifi
- Nouveau bouton « Vérifier les mises à jour » dans l'onglet Aide, avec message d'erreur explicite en cas de problème
- La bannière attend que l'interface soit prête avant de s'afficher (premier lancement avec conditions d'utilisation)

## v2.8 — 2026-07-07

- Mise à jour intégrée : le bouton « Mettre à jour » télécharge l'installeur directement dans l'app avec une barre de progression
- Windows : l'installeur se lance automatiquement à la fin du téléchargement
- Mac : le DMG s'ouvre automatiquement, il ne reste qu'à glisser l'app dans Applications
- En cas d'échec du téléchargement, repli automatique vers la page de téléchargement GitHub

## v2.7 — 2026-07-06

- En mode fusion : les factures sont classées par fournisseur, puis par date de facturation (au lieu de l'ordre de numérisation) — idéal pour « repasser » un PDF déjà fusionné
- Détection des doublons potentiels (même fournisseur + même n° de facture) : badge « DOUBLON ? » dans la fenêtre de révision et détail dans le log
- Nouvelle case « Exclure » sur chaque facture dans la fenêtre de révision, pour retirer un doublon avant la sauvegarde
- Reconnaissance améliorée : les préfixes de PO (LS1194, BL1194…) ne corrompent plus le numéro de projet
- Un PO parasite contenant le PO dominant du lot (ex: 1194-P1524 dans un lot 1194) est rabattu automatiquement sur le dominant
- Lecture des dates à 2 chiffres d'année désambiguïsée (format québécois JJ/MM/AA : 23/06/26 = 23 juin 2026)

## v2.6 — 2026-05-13

- Nouvelle option « Fusionner toutes les factures du même PO en un seul PDF » dans le panneau des options de renommage
- En mode fusion : un fichier nommé `<PO>.pdf` par projet, contenant toutes les pages des factures de ce projet
- Les factures sans PO restent séparées dans un sous-dossier `SANS_PO/` même en mode fusion

## v2.5 — 2026-05-13

- Correction d'un crash au démarrage sur Windows (UnboundLocalError dans le chargement des polices)

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
