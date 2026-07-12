# Harnais matériel — diagnostic & capture USB (lecture seule)

> **Pourquoi** : la machine de développement a **l'USB désactivé** ; on ne peut donc rien
> tester sur une vraie calculatrice ici. Ce harnais est un **outil autonome** qu'un
> **volontaire** exécute sur **sa** machine (USB actif, une vraie calculatrice NumWorks) pour
> valider l'énumération/lecture et **capturer le dialogue USB** — sans aucune assistance.

## Garantie de sûreté

**Lecture seule.** Le harnais énumère la calculatrice, lit son identité (modèle, version,
en-têtes) et enregistre les transferts USB. Il **n'écrit rien** : aucune commande d'effacement
(`erase`), aucun bloc de données envoyé, seulement des lectures (`UPLOAD`) et le
positionnement du pointeur d'adresse (`set address`, qui ne modifie pas la flash).
**Aucun risque de brick.** (Vérifié par le test `test_diagnose_is_strictly_read_only`.)

## Pré-requis (sur la machine du volontaire)

- Python ≥ 3.10 et l'outil : `pip install "nwupdater[usb]"` (installe `pyusb`).
- libusb : **macOS** rien à faire ; **Linux** droits USB (groupe `plugdev` / règle udev) ;
  **Windows** pilote WinUSB (souvent automatique, sinon Zadig).
- Une calculatrice NumWorks branchée en USB, sur l'écran « branchez à un ordinateur »
  (mode DFU). Câble **données** (pas seulement charge).

## Utilisation

```bash
nwupdater diagnose
# → écrit nwupdater-diagnostic-<horodatage>.json et affiche un résumé.
```

Renvoyez le fichier JSON. Il contient : identité lue (modèle, famille, version OS/kernel,
commit, zone apps), identifiants USB (VID/PID/bcdDevice), et la **liste horodatée de tous les
transferts de contrôle** (setup + payload en hexa) — c'est la capture de référence du
dialogue.

### Auto-test (sans matériel)

```bash
nwupdater diagnose --virtual n0110   # exécute le harnais contre le device virtuel
```

## Côté code (pour les contributeurs)

- `src/nwupdater/dfu/capture.py` — `CapturingDevice` : enveloppe transparente qui journalise
  chaque `ctrl_transfer` avant délégation (aucun changement de logique).
- `src/nwupdater/diagnose.py` — `diagnose(device, …)` : lecture d'identité + assemblage du
  rapport. Transport-agnostique → **entièrement testé ici** contre le device virtuel ; seule
  l'énumération pyusb réelle tourne chez le volontaire.
- CLI : `nwupdater diagnose` (réel) / `--virtual` (auto-test).

## Capture de séquence — scénario « scientifique, 1er allumage »

Capture **les deux canaux** — USB (calc↔Mac) et WEB (Mac↔my.numworks.com) — pour ce flux
exact : s'authentifier, lire la calculatrice, **tenter** le téléchargement de l'OS **sans le
flasher** (séquence rejouable). Un **refus serveur** (calculatrice non enregistrée au premier
allumage) est un **résultat capturé**, pas une erreur.

Sûreté : **rien n'est écrit** sur la calculatrice ; secrets **caviardés** (mot de passe, CSRF,
cookies) ; le firmware n'est **jamais** inclus dans le dump (taille + sha256 seulement).

### Deux façons de capturer sur du vrai matériel

**A. L'app packagée** (recommandé, double-clic) — elle embarque désormais `pyusb` + `libusb`
(`libusb-package`) et **détecte la vraie calculatrice** au démarrage. Se connecter, brancher
la calculatrice, cliquer **« Capturer la séquence »** → le navigateur télécharge
`nwupdater-capture-<ts>.json`.

**B. La CLI** (équivalent headless) :
```bash
python3 -m pip install "nwupdater[usb]"     # pyusb + libusb-package (backend inclus)
nwupdater login                              # jeton NumWorks (voir README Lot 6)
# brancher la calculatrice (écran « branchez à un ordinateur »)
nwupdater capture                            # → nwupdater-capture-<ts>.json  (aucun flash)
```

Renvoie le fichier `nwupdater-capture-*.json`. Auto-test sans matériel :
`nwupdater capture --virtual n0200` (le côté WEB reste réel).

> Côté code : `net_capture.RecordingTransport` (HTTP, caviardage), `capture_session.run_capture`
> (USB via `diagnose` + WEB via `download`, jamais de flash) ; CLI `capture` et bouton
> « Capturer la séquence » dans l'UI (endpoint `POST /api/capture`).

## Suite (sur `develop`)

- Analyseur de la capture (comparaison au protocole DFU attendu, annotations).
- Éventuel gadget USB Linux (`dummy_hcd`) pour produire une capture sans matériel (faible
  priorité).
- Flash guidé sur matériel réel (séparé, avec confirmations) — **plus tard**, hors de ce
  harnais lecture seule.
