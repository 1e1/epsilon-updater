# Roadmap & état d'avancement

Légende : ✅ fait · 🟡 en cours · ⬜ à faire

## Lot 1 — SPECS ✅ (fondation)
- ✅ Architecture OS Epsilon (boot chain, slots A/B, carte mémoire) → [os-architecture.md](../01-specs/os-architecture.md)
- ✅ Variantes hardware — 2 familles confirmées : Graphique **N01xx** / Scientifique **N02xx** (N0200 = STM32U073) → [hardware-variants.md](../01-specs/hardware-variants.md)
- ✅ Constat émulateur (pas d'USB) + stratégie appareil DFU virtuel → [emulators-and-usb-analysis.md](../01-specs/emulators-and-usb-analysis.md)
- ✅ Protocole USB/DFU côté hôte (commandes, DfuSe, platforminfo) → [usb-dfu-protocol.md](../01-specs/usb-dfu-protocol.md)
- ✅ Fonctions atelier « My Devices » (appairage / n° de série) & « My Scripts » (format storage + scripts) → [scripts-and-device-pairing.md](../01-specs/scripts-and-device-pairing.md)
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

## Outillage matériel (branche `develop`)
- 🟡 **Harnais diagnostic + capture USB (lecture seule)** — FAIT (1er livrable `develop`) :
  `nwupdater diagnose` énumère, lit l'identité et capture les transferts USB **sans rien
  écrire**, produit un rapport JSON à renvoyer. Cœur testé ici contre le device virtuel ;
  l'énumération réelle tourne chez un volontaire (la machine de dev a **l'USB désactivé**).
  Réf : [../reference/hardware-harness.md](../reference/hardware-harness.md).
- ✅ **Capture de séquence USB+WEB (sans flash)** — bouton UI + CLI `capture` (scénario
  « scientifique 1er allumage ») ; dump JSON, secrets caviardés, firmware non inclus.
  Réf : [../reference/hardware-harness.md](../reference/hardware-harness.md).
- ✅ **Analyseur de capture** + USB tracer + dfu-diff (`tools/`, agent parallèle).
- ✅ **Dump ↔ analyseur alignés** : l'analyseur (`capture_analyze`) lit directement le dump
  `run_capture` (`_from_run_capture`/`load_capture`).
- ✅ **App capable d'USB réel** : `pyusb` + `libusb` bundlés (`libusb-package`) ; l'app détecte
  la vraie calculatrice (repli démo sinon). Capture possible en double-clic *ou* via la CLI.
- ⬜ Flash guidé sur matériel réel (séparé, avec confirmations).
- ⬜ *(faible priorité)* gadget USB Linux `dummy_hcd` pour capturer sans matériel.

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

## Idées / à explorer (backlog)

Pistes notées pour plus tard (non planifiées) :

- ✅ **Réduire la taille du binaire** empaqueté (PyInstaller) — élagage du TOC des extensions C
  inutilisées (codecs CJK, `_decimal`, `pyexpat`, `readline`, `_sqlite3`, `_curses`), `strip` +
  `optimize=2`, et **Mac découpé par architecture** (`ditto --arch`, arm64 / x86_64 au lieu d'un
  binaire universel). Résultat mesuré : **Linux 20,9 → 9,86 Mo (−53 %)**, **Mac 16 → 8,25 (arm64)
  / 7,21 (Intel)**, **Windows 8,84 → 7,98 Mo**. Voir `packaging/nwupdater.spec`.
- ⬜ **Porter `nwlink` pour se passer de Node** — installer une app distribuée (ELF) **sans**
  Node/npm. Analyse & plan : [../04-third-party-apps/nwlink-port-plan.md](../04-third-party-apps/nwlink-port-plan.md).
  Stratégie retenue = **B** (lier 1× en CI + relocation pur-Python côté appareil), qui évite de
  réimplémenter `lld` et la vendorisation du runtime EADK ; bloqué en Phase 0 par la question de licence.
- ⬜ **Embarquer une IHM dans le binaire** — fenêtre native (ex. webview système / Qt / Tk) pour ne
  plus dépendre d'un navigateur externe ; le serveur local + les assets web actuels restent le socle.
