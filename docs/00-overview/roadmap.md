# Roadmap & état d'avancement

Légende : ✅ fait · 🟡 en cours · ⬜ à faire

## Lot 1 — SPECS ✅ (fondation)
- ✅ Architecture OS Epsilon (boot chain, slots A/B, carte mémoire) → [os-architecture.md](../01-specs/os-architecture.md)
- ✅ Variantes hardware — 2 familles confirmées : Graphique **N01xx** / Scientifique **N02xx** (N0200 = STM32U073) → [hardware-variants.md](../01-specs/hardware-variants.md)
- ✅ Constat émulateur (pas d'USB) + stratégie appareil DFU virtuel → [emulators-and-usb-analysis.md](../01-specs/emulators-and-usb-analysis.md)
- ✅ Protocole USB/DFU côté hôte (commandes, DfuSe, platforminfo) → [usb-dfu-protocol.md](../01-specs/usb-dfu-protocol.md)
- ✅ Outillage code : registre modèles + client DFU hôte + **device virtuel Niveau 1** + lecture identité + CLI + 7 tests verts (`src/nwupdater/`, `tests/`)
- ⬜ Niveau 2 : gadget USB Linux (dummy_hcd) en Docker pour énumération réelle + capture usbmon

> **Renumérotation (ordre de construction croissant)** : Catalogue et Transfert passent
> avant Apps, car le moteur DFU d'écriture (Transfert) est réutilisé pour installer les apps.

## Lot 2 — Catalogue MàJ ✅
- ✅ Client catalogue firmware (`firmwares.json`, public, snapshot offline) + parsing versions
- ✅ Croiser le catalogue avec l'identité → MàJ compatibles + CLI `catalog`
- Réf : [../02-update-catalog/](../02-update-catalog/) · code `catalog/`

## Lot 3 — Transfert & installation ✅
- ✅ Moteur DFU/DfuSe headless (`dfu/protocol.py`) + `Installer`
- ✅ Flash slot inactif A/B + vérif read-back + `FirmwareImage` (raw/synthetic/DfuSe) + CLI `install`
- Réf : [../03-transfer-install/](../03-transfer-install/) · code `install/`, `formats/`

## Lot 4 — Apps tierces ✅
- ✅ Format `.nwa` (`formats/nwa.py`) + store communautaire + filtrage compat
- ✅ Install `.nwa` en zone external-apps via le moteur du Lot 3 + CLI `apps`
- Réf : [../04-third-party-apps/](../04-third-party-apps/) · code `apps/`

## Lot 5 — Packaging UI ✅
- ✅ Cœur headless expose une API HTTP locale (stdlib, loopback)
- ✅ Page web locale autonome (choix MàJ / apps) + CLI `ui` (ouvre le navigateur)
- ✅ Packaging décrit (PyInstaller / Docker) — `package-data` déclaré
- Réf : [../05-packaging-ui/implementation.md](../05-packaging-ui/implementation.md) · code `server/`

## Lot 6 — Authentification & téléchargement du firmware officiel ✅
- ✅ Auth `my.numworks.com` façon *bring-your-own-token* (`catalog/auth.py`) : on ne conserve
  que le cookie `remember_user_token` (0600, hors dépôt), jamais le mot de passe.
- ✅ Téléchargement `.dfu` officiel par modèle+canal (`catalog/download.py`) : validation du
  modèle, vérif signature DfuSe + taille, journal de provenance (SHA-256).
- ✅ Acquisition matériel réel (`dfu/usbio.py`, pyusb injecté) + `install --download`.
- Réf : [../01-specs/n02xx-firmware-format.md](../01-specs/n02xx-firmware-format.md) · code `catalog/`, `dfu/usbio.py`.

## Reste optionnel (post-lots)
- **Validation sur matériel réel** par des volontaires — le seul vrai trou. L'outil est prêt
  (chemin `dfu/usbio.py`), mais il n'a jamais été testé sur USB réel ici : **la machine de
  développement a les ports USB désactivés**. Tout test/capture USB doit donc être fait sur
  une **autre machine (USB actif), via un harnais autonome exécutable par un humain sans
  assistance** — à concevoir sur `develop`.
- *Nice-to-have (faible priorité)* : gadget USB Linux (`dummy_hcd`, Linux uniquement) pour
  produire un **pcap de référence** de l'énumération. N'apporte **aucune** portabilité (l'app
  est déjà Mac/Windows/Linux) et ne remplace pas la validation sur vraie calculatrice → non
  retenu pour l'instant.

## Décisions tranchées
1. **Langage du cœur headless** : ✅ **Python + pyusb** (client DFU transport-agnostique ;
   pyusb requis seulement pour le hardware réel).
2. **Périmètre variantes** : ✅ **deux familles** — Graphique **N01xx** & Scientifique
   **N02xx** (cf. [hardware-variants.md](../01-specs/hardware-variants.md)).
3. **Appareil virtuel** : ✅ **Niveau 1 (mock) d'abord** — fait ; **Niveau 2 (gadget
   Linux/Docker)** ensuite.

## Point d'attention
- **Légalité/éthique** : rejouer les endpoints NumWorks pour télécharger firmwares/apps →
  usage perso/défensif ; on ne contourne aucune signature (impossible de signer un firmware
  tiers de toute façon). L'outil lit l'identité en **lecture seule** et n'active jamais le
  mode examen.
