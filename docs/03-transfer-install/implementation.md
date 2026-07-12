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
cf. [../01-specs/usb-dfu-protocol.md §8.3](../01-specs/usb-dfu-protocol.md)).

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
- **Signature** : on ne signe rien (impossible). Flasher un firmware **officiel signé**
  récupéré tel quel fonctionne ; un firmware tiers non signé bootera avec clearance réduite
  (mode examen verrouillé) — comportement natif de l'OS, pas contourné.
