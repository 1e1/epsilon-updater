# Format du firmware N02xx (Scientifique) — rétro-ingénierie

> ⚠️ Projet indépendant, non officiel. Analyse faite par observation d'un binaire officiel
> téléchargé légitimement pour interopérabilité. Aucune clé, aucun contournement de
> chiffrement — voir [`DISCLAIMER.md`](../../DISCLAIMER.md).

## Résumé

Contrairement à l'Epsilon **graphique** (N01xx), qui est distribué **en clair** avec des
en-têtes lisibles (`SlotInfo`, `KernelHeader`, `UserlandHeader`) et des chaînes de version,
le firmware **Scientifique (N02xx)** est livré comme **un unique blob chiffré/opaque**. On
peut le **télécharger, vérifier (taille + SHA-256), mettre en cache et flasher verbatim** (vers
`0x98000000`, **hors ligne** — cf. plus bas). La **charge utile** n'est pas introspectable
(chiffrée), mais la **version** est lisible dans le bloc **FirmwareHeader** (`0xFACECAFE`,
lecture seule @ `0x080040C0`) et/ou le manifeste.

## Source analysée

`GET my.numworks.com/firmwares/n0200/stable.dfu` (authentifié), **v3.0.0**, patch `8059a46`,
**237 606 octets**.

## Conteneur DfuSe

Le conteneur est standard (identique au graphique) :

| Champ | Valeur |
|---|---|
| Préfixe | `DfuSe`, version 1 |
| Cibles (targets) | 1 (`alt=0`, nom `ST...`) |
| Éléments | **1 seul** |
| Adresse de l'élément | **`0x98000000`** |
| Taille de l'élément | 237 297 o |
| Suffixe `idVendor` | `0x0483` (STMicroelectronics) |
| Suffixe `idProduct` | **`0xA51A`** (bootloader NumWorks — même PID que le graphique) |
| Suffixe `bcdDevice` | `0x0000` (générique — cf. installer, on n'exige pas l'égalité) |

**Adresse `0x98000000`** : espace d'adressage DFU propre au N0200 (distinct de la flash CPU
STM32U0 en `0x08000000`). C'est l'adresse que le bootloader attend pour la région firmware ;
c'est donc là qu'on écrit. Pas de QSPI, **pas de double-slot A/B**.

> **[CONFIRMÉ matériel — capture du flux officiel + lecture]** La N0200 s'énumère en `0483:A51A`
> (bcd `0x0200`, Product `NumWorks Scientific Calculator`) et n'annonce dans sa chaîne de layout DFU
> qu'**une** région : `@FirmwareHeader/0x080040C0/01*64Ba` — **64 octets en lecture seule** (type
> `a`, `01*64B` = 64 **octets**), la **fenêtre d'identité** (voir *FirmwareHeader* ci-dessous),
> **pas** la cible d'écriture. **Ce layout est trompeur** : le mode `0xA51A` **accepte directement
> les écritures DfuSe vers `0x98000000`** bien qu'aucune région inscriptible n'y soit annoncée —
> il n'y a **pas** de « mode flasher » séparé à déclencher.

> **[CONFIRMÉ — capture WebUSB du flux officiel, N0200 réelle]** Voir
> [../reference/official-webusb-analysis.md](../reference/official-webusb-analysis.md). **Aucune
> bascule de mode, aucun changement de PID** — tout se fait dans `0xA51A`. Séquence :
> `SET_ADDRESS 0x98000000` **par bloc de 2048 o** + `DNLOAD`, **sans aucune commande ERASE** (le
> bootloader efface implicitement) ; handshake de fin `SET_ADDRESS 0x08000000` + `DNLOAD` de
> longueur nulle (boot). Les seuls appels serveur (`POST /devices/<serial>`, avant/après) sont de la
> **télémétrie de compte**, **pas** une attestation ; le `.dfu` est un **téléchargement statique
> protégé par compte** (`401` sans login). Chrono capturé : ~8 s d'écriture.
>
> **➡️ Le flash hors-ligne du firmware N0200 EST viable** (corrige la conclusion antérieure « ni
> viable ni sûr ») : télécharger le `.dfu` → écrire l'élément à `0x98000000` en DfuSe, sans erase.
> `install/installer.py` le fait **déjà** (mono-slot, `flash_erase=False`). **Réserve mono-slot** :
> on écrit le firmware actif (pas de repli A/B), mais le **bootloader `0xA51A` persiste** (hors
> `0x98000000`) → un flash interrompu reste **re-flashable** (risque de brick faible). Firmware
> **officiel signé uniquement** (on ne signe pas). Le mode examen : voir ci-dessous.

### FirmwareHeader — identité (lecture seule @ `0x080040C0`)

Bloc de **32 octets** lu par DfuSe `UPLOAD`, encadré par le magic **`0xFACECAFE`** :
`magic` (u32) · `taille firmware` (u32) · `checksum` (u32) · `version` (chaîne, ex. `3.0.0`) ·
`commit` (chaîne, ex. `8276cd0`) · `magic` (u32). **La version est donc lisible on-device** (pas
seulement dans le manifeste), même si la **charge utile** à `0x98000000` reste chiffrée/opaque.

### Mode examen

La N0200 **n'écrit aucun secteur exam-bytes/persistant** lors du flash (contrairement au graphique
qui rafraîchit `0x903f0000`/`0x907f0000`), n'a **pas de stockage utilisateur** (pas de scripts) et
est classée dans une **famille distincte** côté compte (`device_type_id=6` vs `1` pour le
graphique). Faisceau d'indices : **pas de machinerie exam-bytes façon graphique**. Un « test mode »
LED sans mémoire n'est pas exclu ; à confirmer via la page my.numworks du N0200 ou la doc produit.

## Charge utile : chiffrée / opaque

Mesures sur les 237 297 octets de l'élément :

| Indicateur | Résultat | Interprétation |
|---|---|---|
| Entropie globale | **7,999 bits/octet** | maximale |
| Entropie par fenêtre 4 Kio | aucune fenêtre `< 7,0` | uniforme de bout en bout |
| Octets nuls | 0,37 % | pas de zones vides/structurées |
| Table de vecteurs ARM en tête | **absente** (word0/word1 aléatoires) | pas de code exécutable en clair |
| Chaînes ASCII (`3.0.0`, `NumWorks`, `Epsilon`, commit…) | **0** | rien en clair |
| Magies connues (`0xEFEEDBBA` / `0xDEC00DF0` / `0xDEC0EDFE`) | **0** | pas d'en-tête Epsilon |
| Blocs 16 o répétés (signature ECB) | **aucun** | pas d'AES-ECB |
| Magies de compression (gzip/lz4/zstd/xz) | absentes | pas un simple conteneur compressé |
| Alignement taille | `237297 % 16 == 1` | non aligné bloc → plutôt flux/CTR |

**Conclusion :** contenu **chiffré** (chiffrement par flux ou mode compteur), sans en-tête en
clair. Il n'existe **aucune structure exploitable** dans le binaire : ni version, ni commit,
ni pointeurs de slot.

## Conséquences pour l'updater (modélisation)

- `models.py` : `Model.opaque_firmware = True` pour N0200 ; carte mémoire avec base DFU
  **`0x98000000`**, mono-slot, sans flash externe.
- `install/installer.py` : pour un modèle `opaque_firmware`, `plan_install` écrit l'image
  **verbatim** et met `boot_address = None` (aucun en-tête à viser ; le bootloader démarre au
  détachement). On **n'invente pas** d'offset userland.
- **Version** : disponible **dans le manifeste** (`3.0.0`) **et** dans le bloc FirmwareHeader
  on-device (`0xFACECAFE` @ `0x080040C0`). `read_installed_version` (basé sur l'en-tête userland)
  renvoie `None` sur N02xx — attendu ; lire la version N0200 passe par le FirmwareHeader (chemin
  distinct, à câbler quand utile).
- **Intégrité** : on ne peut pas vérifier le contenu déchiffré, mais on atteste l'octet-à-octet
  via la **taille du manifeste** et l'empreinte **SHA-256** (journal de provenance).

## Diff inter-versions (tentative) — bloquée par la politique serveur

Diffuser deux versions chiffrées peut révéler le **mode** de chiffrement : préfixe commun →
CBC à clé/IV fixes ; forte proportion d'octets identiques au même offset → réutilisation de
keystream (flux/CTR à nonce fixe) ; blocs 16 o identiques → ECB ; ~100 % différent → clé/nonce
par build (rien n'en sort).

**En pratique, impossible aujourd'hui** : le serveur ne sert que le build courant.
- `n0200/stable.dfu` et `n0200/beta.dfu` sont **byte-identiques** (`sha256
  838d8fe3283484ab15b9eb5ab44b8b7f6d0ffe145d06a541947199574017822d`, tous deux 3.0.0, id 319).
- `n0200/{1,2,3,1.0.0,3.0.0}.json` → `"No firmware version named X for N0200"`.
- Accès par id (`firmwares/319.dfu`) et versions explicites → 404. Même chose côté graphique
  (`n0110/24.3.0.dfu` → 404). Les « Version 1/2/3 » de la page de MAJ sont un **changelog**,
  pas des artefacts téléchargeables.

**Stratégie** : archiver le `.dfu` courant + son SHA-256, puis diffuser v3 ↔ v(n+1) quand une
nouvelle version sortira. Le tooling de diff (préfixe commun, histogramme d'égalité par offset,
blocs 16 o communs, delta de taille) est trivial à ajouter le moment venu.

## Limites / à confirmer

- Le **type exact de chiffrement** et l'emplacement d'une éventuelle signature ne sont pas
  déterminables sans une seconde version à diffuser (diff) ni les clés — hors périmètre.
- La **carte mémoire CPU** du STM32U0 (SRAM, taille flash réelle) reste **inférée**
  (`confirmed=False`). Seuls la base DFU `0x98000000` et la nature opaque sont **observés**.
- L'**identité on-device** (lecture `SlotInfo` en SRAM via DFU) n'est **pas** démontrée sur
  N0200 et ne le sera qu'avec du matériel réel.
