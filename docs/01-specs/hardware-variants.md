# Lot 1 — Variantes matérielles : Graphique (N01xx) & Scientifique (N0200)

## Deux familles produit bien réelles

Vérification faite (numworks.com/fr/emulateur/, TI-Planet, blog NumWorks), l'énoncé est
**exact** : NumWorks commercialise **deux familles distinctes**, avec un hardware et un
clavier différents :

| Famille | Produit | Cible | Émulateur |
|---------|---------|-------|-----------|
| **Graphique** | *The Graphing Calculator* — série **N01xx** | Lycée / supérieur | https://www.numworks.com/fr/emulateur/graphique/ |
| **Scientifique** | *NumWorks scientifique* — **N0200** (rentrée 2026) | Collège | https://www.numworks.com/fr/emulateur/scientifique/ |

Différences entre les deux familles :
- **Clavier** : la scientifique reprend l'organisation de la graphique mais avec **moins de
  touches** (clavier simplifié, focalisé sur l'essentiel collège).
- **Jeu d'apps** : la scientifique expose un sous-ensemble (pas/peu de graphe, périmètre
  collège) ; la graphique a le graphe, Python, etc.
- **Matériel** : la scientifique n'a **ni bouton reset ni trappe pile**, et a une **batterie
  rechargeable**. MCU et flash très différents (voir tableau).
- **Point commun crucial** : les deux tournent **Epsilon** (même base de code, build
  configuré différemment) et **se mettent à jour gratuitement via le même mécanisme
  WebUSB/DFU**. → **notre updater doit gérer les deux familles.**

Ce qui reste vrai : « scientifique » n'est PAS le mode examen. Le **mode examen /
press-to-test** est une restriction logicielle **orthogonale**, présente sur les deux
familles ; on l'expose en lecture seule (un firmware tiers ne peut pas l'activer).

## Révisions hardware par famille

| Famille | Modèle | Année | MCU | Flash interne | Flash externe QSPI | RAM | Notes |
|---------|--------|-------|-----|---------------|--------------------|-----|-------|
| Graphique | **N0100** | 2017 | STM32F412 | ~1 MiB interne | *aucune* | 256 KiB | 1ère gén. Tout en flash interne, **pas de slots A/B**. |
| Graphique | **N0110** | 2019 | STM32F730 | 64 KiB | 8 MiB | 256 KiB | Intro slots A/B + secure boot. SRAM @`0x20000000`. |
| Graphique | **N0115** | ~2022 | variante N0110 | 64 KiB | 8 MiB | 256 KiB | Révision N0110 (pénurie composants). |
| Graphique | **N0120** | 2023 | STM32H725 | 512 KiB (4×128K) | 8 MiB | 320 KiB | MCU plus puissant. SRAM @`0x24000000` (AXI). |
| Scientifique | **N0200** | 2026 | **STM32U073KC** (Cortex-M0+) | **256 KiB** *(seule mémoire)* | *aucune* | ~40 KiB | Collège. Pas de reset/trappe, batterie rechargeable. Flash très limitée → contraintes de MàJ. |

> **N0200 = architecture proche du N0100** (flash interne uniquement, **pas de slots A/B**,
> pas de QSPI), mais sur un MCU ultra-basse-conso M0+. bcdDevice attendu **`0x0200`**
> (pattern `n%04x`). MCU/flash [confirmé via TI-Planet/recherche] ; PID exact et carte
> mémoire N0200 **à confirmer** (config absente de ce fork). **PID confirmé sur matériel :
> `0xA51A`** (voir la capture plus bas), `bcdDevice=0x0200` confirmé.
>
> **Versionnage propre** : la scientifique n'utilise PAS le schéma daté du graphique. Elle
> a une numérotation entière (Version 1, 2, 3…) ; dernière = **Version 3 (10 juin 2026)**,
> page `numworks.com/fr/scientifique/mise-a-jour/`. Mise à jour via le même portail DFU. Le
> `3.0.0` du catalogue graphique `firmwares.json` est sans rapport (legacy ~2018). Détails :
> [../02-update-catalog/web-api.md](../02-update-catalog/web-api.md).
>
> MCU N0115 à confirmer (probable variante QSPI/MCU du N0110). Configs présentes dans le
> repo : `shared/ion/src/device/include/{n0110,n0115,n0120}/config/`. **N0100 et N0200
> n'ont pas de dossier `config/usb.h`** dans ce fork.

## Identification USB par modèle

Extrait de `shared/ion/src/device/include/<model>/config/usb.h` et `calculator.h` :

| Modèle | idVendor | idProduct (PID) | bcdDevice | ProductString |
|--------|----------|-----------------|-----------|---------------|
| N0100 | `0x0483` | `0xA291` (userland) / `0xDF11` (bootloader ST) | `0x0100` | `NumWorks Calculator` |
| N0110 | `0x0483` (STMicro) | `0xA291` | `0x0110` | `NumWorks Calculator` |
| N0115 | `0x0483` | `0xA291` | `0x0115` | `NumWorks Calculator` |
| N0120 | `0x0483` | `0xA291` | `0x0120` | `NumWorks Calculator` |
| N0200 (scientifique) | `0x0483` | **`0xA51A`** (observé matériel) | `0x0200` (confirmé) | `NumWorks Scientific Calculator` (confirmé) |

> **Capture sur N0200 réelle [CONFIRMÉ matériel, lecture seule]** : PID **`0xA51A`** (pas
> `0xA291` comme supposé), `bcdDevice=0x0200`, `bcdUSB=0x0210`, Manufacturer `NumWorks`,
> Product **`NumWorks Scientific Calculator`** (distinct du graphique `NumWorks Calculator`),
> numéro de série 16 car. base64. Interface DFU unique (classe `0xFE`/`0x01`/`0x02`), descripteur
> fonctionnel DFU `bmAttributes=0x03` (dnload+upload), `wTransferSize=2048`, `bcdDFUVersion=0x0100`
> (DfuSe). Chaîne de layout mémoire annoncée : **`@FirmwareHeader/0x080040C0/01*64Ba`** (1 secteur
> de 64 KiB, base `0x08000000` = flash CPU) — à distinguer de la base `0x98000000` du fichier
> `.dfu` 3.0.0 (voir [n02xx-firmware-format.md](n02xx-firmware-format.md)). `read_identity` en tire
> correctement modèle/famille/série et l'absence de slots A/B & de zone apps, mais **os_version /
> kernel / commit reviennent `None`** — c'est **attendu** sur N0200, pas un échec : le firmware
> est opaque/chiffré et n'expose aucune version lisible sur le device (elle vient du **manifeste**
> `3.0.0`, cf. [n02xx-firmware-format.md](n02xx-firmware-format.md)). Le resolver de capacités
> donne bien `firmware_update` seul (`external_apps=False`,
> `scripts=False`, `ab_slots=False`).

PID additionnels vus dans `tools/device/dfu.py` : `0xDF11` (bootloader ST standard),
`0xA291` (mode DFU NumWorks, graphique), `0xA51A` (**confirmé présent sur N0200** — la
scientifique s'énumère à ce PID lorsqu'elle est branchée).

**Règles de détection côté hôte :**
1. Filtrer sur `idVendor == 0x0483` et `idProduct ∈ {0xA291, 0xDF11, 0xA51A}`.
2. Distinguer la **révision** via `bcdDevice` (0x0110 / 0x0115 / 0x0120).
3. Confirmer/raffiner en lisant la structure **platforminfo** par `DFU_UPLOAD`
   (modèle, version d'OS, commit) — voir [usb-dfu-protocol.md](usb-dfu-protocol.md).

Le `ProductString` est identique sur les 3 modèles récents → **ne pas** s'en servir pour
distinguer la révision ; utiliser `bcdDevice` + platforminfo.

## Passer la calculatrice en mode DFU (par modèle)

Deux niveaux de DFU coexistent (cf. [usb-dfu-protocol.md](usb-dfu-protocol.md)) :

- **DFU « userland » (`0483:A291`)** — exposé **automatiquement** par Epsilon dès qu'une
  calculatrice allumée (OS fonctionnel) est branchée en USB. **C'est le mode qu'utilise cet
  updater** (identité, mise à jour, apps, scripts) : **aucune combinaison de touches**, il
  suffit de brancher le câble. *(Vérifié sur matériel : une N0120 sous Epsilon 25.2.0 branchée
  normalement est détectée en `0483:A291`.)*
- **Bootloader ST (`0483:DF11`)** — le bootloader ROM STM32 (« STM32 BOOTLOADER »), utile en
  **récupération** (OS non démarrable) ou pour un flash bas niveau. Atteint par **RESET +
  touche**, ce qui dépend du modèle.

| Modèle | DFU userland (usage normal) | Entrée bootloader de récupération |
|---|---|---|
| **N0100** | Brancher l'USB, calc allumée → `A291`. | Maintenir **6** pendant l'allumage (bouton **RESET**, trou d'épingle au dos). Piles **amovibles** : les retirer/remettre force un démarrage à froid. |
| **N0110 / N0115** | Brancher l'USB, calc allumée → `A291`. | Maintenir **6**, puis appuyer sur **RESET** (trou d'épingle au dos) en gardant **6** → écran noir + LED **rouge** → « STM32 BOOTLOADER » (`0483:DF11`). |
| **N0120** | Brancher l'USB, calc allumée → `A291`. | Même geste (**6** + **RESET**). *(Pilotes MCU non publics → récupération bas niveau limitée, mais l'entrée bootloader par la touche reste identique.)* |
| **N0200** (scientifique) | Brancher l'USB, calc allumée → **`A51A`** (observé, *pas* `A291`). | **Aucun bouton reset ni trappe pile** → pas d'entrée bootloader manuelle ; le DFU exposé par l'OS suffit. |

> Les combos de récupération sont **[communauté / observé]**, pas une documentation officielle
> NumWorks — à réserver au dépannage. Pour l'usage courant de cet outil, **le DFU userland
> suffit** : branchez simplement le câble, calculatrice allumée.
>
> Références (récupération/bootloader) : [WebUSB DFU NumWorks (ti-planet)](https://ti-planet.github.io/webdfu_numworks/n0110/) ·
> [NumWorks Guide — Troubleshooting](https://guide.getomega.dev/docs/troubleshooting/) ·
> [epsilon#1740](https://github.com/numworks/epsilon/issues/1740).

## Descripteurs communs (rappel, source `calculator.h`)

- `bcdUSB = 0x0210` (USB 2.1 → active le BOS/WebUSB).
- BOS + **WebUSB platform descriptor** → landing page `https://my.numworks.com`.
- **Microsoft OS descriptor** `WINUSB` → pilote WinUSB automatique sous Windows (pas de
  Zadig sur les modèles récents ; utile pour libusb côté hôte).
- Interface **DFU** unique, `bcdDFUVersion = 0x0100` (DfuSe), `wTransferSize = 2048`,
  `bmAttributes = 0b0011` (can download + can upload, will-detach).

## Convention de nommage retenue

On généralise par **préfixe de série** (robuste aux futures révisions) :

- **N01xx → famille Graphique** (N0100, N0110, N0115, N0120, …)
- **N02xx → famille Scientifique** (N0200 = la première ; N02xx à venir)

Règle de détection famille côté hôte : lire `bcdDevice`, puis
`famille = "graphique" if 0x0100 <= bcd < 0x0200 else "scientifique" if 0x0200 <= bcd < 0x0300 else "inconnu"`.
Le modèle précis reste `"n%04x" % bcdDevice`. Cette classification pilote : jeu d'apps
attendu, présence de slots A/B (graphique N0110+ oui ; scientifique N02xx non, flash
interne seule comme N0100), et carte mémoire cible du flash.

**Périmètre outil** : gérer les deux familles ; démarrer le développement/mock sur
**N0110** (cas le plus documenté, slots A/B) puis **N0200** (flash interne, contraint).
