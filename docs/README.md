# NumWorks Updater — Base de connaissance

Utilitaire pour mettre à jour une calculatrice NumWorks **sans Chrome / WebUSB**, sur le
modèle de l'updater Flipper Zero (cœur *headless* + page web locale), et de la Boîte à
Histoires Lunii (app dédiée qui rejoue le dialogue d'un service en ligne).

> Contrainte absolue du projet : **on ne touche JAMAIS à un USB réel.** Tout est
> développé et testé contre des **appareils virtuels / mocks**. Voir
> [01-specs/emulators-and-usb-analysis.md](01-specs/emulators-and-usb-analysis.md).

## Comment lire cette base

La doc suit les 5 lots du projet. Chaque lot a son dossier ; le dossier `reference/`
contient les specs brutes réutilisables (protocole, API, captures).

> Les lots sont numérotés dans l'**ordre de construction** (croissant). Le moteur DFU
> d'écriture (Lot 3) est réutilisé par les apps tierces (Lot 4), d'où cet ordre.

| Lot | Dossier | Objet |
|-----|---------|-------|
| 1 — SPECS | [`01-specs/`](01-specs/) | Analyse de l'OS, variantes HW Graphique/Scientifique, protocole USB/DFU, reconstitution des émulateurs et méthode d'analyse USB |
| 2 — Catalogue MàJ | [`02-update-catalog/`](02-update-catalog/) | Simuler le dialogue bas niveau pour lister le catalogue de mises à jour |
| 3 — Transfert | [`03-transfer-install/`](03-transfer-install/) | Simuler le transfert et l'installation d'une mise à jour |
| 4 — Apps tierces | [`04-third-party-apps/`](04-third-party-apps/) | Simuler une calculatrice connectée pour récupérer des applications tierces depuis le site officiel |
| 5 — Packaging UI | [`05-packaging-ui/`](05-packaging-ui/) | Module de transfert headless qui ouvre une page locale dans le navigateur |

## Références transverses

- [`01-specs/os-architecture.md`](01-specs/os-architecture.md) — architecture Epsilon (boot chain, slots A/B, carte mémoire)
- [`01-specs/hardware-variants.md`](01-specs/hardware-variants.md) — modèles N0100/N0110/N0115/N0120, Graphique vs Scientifique
- [`01-specs/usb-dfu-protocol.md`](01-specs/usb-dfu-protocol.md) — protocole DFU/DfuSe côté hôte (le cœur à réimplémenter)
- [`01-specs/emulators-and-usb-analysis.md`](01-specs/emulators-and-usb-analysis.md) — pourquoi l'émulateur officiel n'aide pas, et comment obtenir un appareil DFU virtuel
- [`reference/sources.md`](reference/sources.md) — liens sources (repos, docs officielles, communauté)

## État d'avancement

Voir [`00-overview/roadmap.md`](00-overview/roadmap.md).
