# Lot 3 — Transfert & installation

Moteur d'installation headless bâti sur le client DFU du Lot 1. Testé intégralement contre
le device virtuel — **aucun USB réel**.

## Modules

- `src/nwupdater/formats/headers.py` — pack/unpack des structures flash (SlotInfo,
  KernelHeader, UserlandHeader). Source unique partagée par le device virtuel, le
  synthétiseur d'image et le lecteur d'identité.
- `src/nwupdater/install/image.py` — `FirmwareImage` = liste de segments `(address, data)` :
  - `from_raw_bins(model, internal=…, external=…)` — le format de distribution NumWorks
    (`epsilon.onboarding.internal.bin` @`0x08000000` + `external.bin` @`0x90000000`).
  - `synthetic(model, version)` — image structurellement valide (kernel+userland headers)
    pour exercer flash+vérif+boot sans binaire réel.
  - `from_dfuse(raw)` / `to_dfuse()` — conteneur DfuSe (.dfu) : prefixe `DfuSe`, cibles,
    éléments (adresse+données), suffixe (VID/PID/bcdDevice + CRC32). Permet d'ingérer un
    `.dfu` officiel et d'archiver une image.
- `src/nwupdater/install/installer.py` — `Installer` + `plan_install` :
  - `plan_install(model, image, active_slot)` — pour A/B, **remappe** les segments (écrits
    pour le slot A) vers le **slot inactif** ; l'adresse de boot = userland header de ce slot.
  - `check_compatibility(image)` — refuse un bcdDevice différent ou un segment hors flash.
  - `flash(plan, verify=True)` — écrit chaque segment (erase+dnload) puis **relit pour
    vérifier** (read-back).
  - `install(image, active_slot, verify, boot)` — enchaîne compat → plan → flash → (boot).
  - `read_installed_version(plan)` — relit le userland header flashé pour confirmer la version.

## Sécurité du double-slot (A/B)

On flashe **toujours le slot inactif**, jamais celui en cours d'exécution → un flash
interrompu ne peut pas rendre la calculatrice non bootable (le slot actif reste intact).
Le boot bascule ensuite via `leave(boot_address)` (detach + jump vers `boot_address + 0x30`,
cf. [../01-specs/usb-dfu-protocol.md §8.3](../01-specs/usb-dfu-protocol.md)). ⚠️ Ce **saut DFU**
fait afficher **temporairement** « UNOFFICIAL SOFTWARE » (le noyau ne peut pas vérifier un slot
atteint par saut) ; pour un statut **officiel**, préférer un **démarrage à froid** (RESET) qui
laisse le bootloader re-vérifier la signature — cf.
[../01-specs/firmware-authenticity.md](../01-specs/firmware-authenticity.md).

Les modèles **mono-slot** (N0100, N02xx) n'ont pas de slot inactif : flash direct en flash
interne (l'update officiel gère ce cas via bootloader/rescue).

## CLI

```bash
# n0110 : flashe le slot inactif B, vérifie, puis boot
nwupdater install --virtual n0110 --os-version 23.2.4 --to-version 25.2.0 --boot
# n0200 (scientifique, mono-slot)
nwupdater install --virtual n0200 --os-version 1.0.0 --to-version 1.1.0
# flasher un vrai fichier DfuSe
nwupdater install --virtual n0110 --dfuse epsilon.dfu
```

## Limite connue / à raccorder

- **Obtention du binaire réel** : `firmwares.json` (Lot 2) ne donne pas l'URL `.bin`
  (derrière `/devices/upgrade/` authentifié). Le raccordement « version → binaire » utilise
  la session du compte de test ou une source alternative — non implémenté ici (démo
  synthétique). Une fois le `.bin`/`.dfu` récupéré, `from_raw_bins`/`from_dfuse` +
  `Installer.install` font le reste, à l'identique.
- **Authenticité (« logiciel non officiel ») & examens [CONFIRMÉ sur N0120 réelle — analyse
  détaillée dans [../01-specs/firmware-authenticity.md](../01-specs/firmware-authenticity.md)]** :
  le statut « officiel » est une **signature Ed25519 (64 o) couvrant noyau+userland du slot**,
  **vérifiée par le bootloader (flash interne) au démarrage à froid**, **entièrement hors ligne**
  (aucune attestation réseau — recoupé dans le flux WebUSB officiel). Deux constats matériels :
  (1) flasher l'image **officielle signée** (octet-exact) puis **redémarrer à froid** (RESET) →
  la calc boote **« officiel »** (le bootloader re-vérifie la signature) ; (2) atteindre le slot
  par le **saut DFU** `leave` (le « boot » in-app) → bandeau **« UNOFFICIAL SOFTWARE »**
  **temporaire** : le noyau, sans la clé, rétrograde tout slot atteint par saut ; un démarrage à
  froid efface le bandeau. Donc **la mise à jour hors ligne vers un firmware officiel conforme
  examen EST faisable** — condition : image **officielle signée** + entrée par **boot à froid**
  (pas le saut DFU). On ne peut pas **signer** un firmware modifié → un firmware non signé reste
  « non officiel ». (Ceci **corrige** l'affirmation rc5 « certification examen infaisable hors
  ligne ».)
- **Slot A/B actif protégé [CONFIRMÉ sur N0120 réelle]** : sur un appareil en marche, le slot
  **actif** est protégé en écriture — un `erase` y renvoie `errTARGET` et **fige la session DFU**
  jusqu'à un reset physique. `plan_install` ne flashe donc **que le slot inactif** (détecté via
  `SlotInfo` → `_active_slot`), jamais l'actif ; un `.dfu` complet A+B n'est **pas** écrit verbatim.
- **Reprise après boot [CONFIRMÉ]** : après `leave` (boot du slot flashé), l'appareil quitte le
  DFU ; regagner l'accès DFU en headless exige un **rebranchement USB** physique (l'interface web
  le gère automatiquement via son re-scan à chaud).
- **Où vit le verdict « officiel » [CONFIRMÉ matériel — N0120 réelle]** : dans la **signature du
  slot**, re-vérifiée par le **bootloader à chaque boot à froid** — ce n'est **pas** un drapeau
  persistant ni une attestation en ligne. Le noyau en marche **n'a pas la clé** : tout userland
  atteint par `leave` (saut DFU) est marqué `ThirdParty` → bandeau ; seul un **boot à froid** par
  le bootloader accorde `NumWorks` (officiel). **Correction d'un constat rc5** : un slot flashé
  par cet outil avec les octets officiels **boote bien « officiel » après un démarrage à froid**
  (RESET) — le « UNOFFICIAL » rc5 venait du **saut DFU** utilisé pour booter, pas d'un défaut des
  octets. **Sélection A/B au boot à froid** : le bootloader boote le premier slot à signature
  valide — **slot bas (A) d'abord à version égale** (observé : A gagne 2× sur N0120 avec A et B en
  25.2.0) ; il ne persiste aucun sélecteur. Le DFU userland (`0483:A291`) écrit la QSPI (slots) ;
  sur notre N0120 il n'annonçait **pas** la flash interne `0x08000000` (le bootloader + la clé
  publique y résident et ne sont pas réécrits par cet outil).
