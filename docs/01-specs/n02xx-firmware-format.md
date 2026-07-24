# Format du firmware N02xx (Scientifique) — rétro-ingénierie

> ⚠️ Projet indépendant, non officiel. Analyse faite par observation d'un binaire officiel
> téléchargé légitimement pour interopérabilité. Aucune clé, aucun contournement de
> chiffrement — voir [`DISCLAIMER.md`](../../DISCLAIMER.md).

## Résumé

Contrairement à l'Epsilon **graphique** (N01xx), qui est distribué **en clair** avec des
en-têtes lisibles (`SlotInfo`, `KernelHeader`, `UserlandHeader`) et des chaînes de version,
le firmware **Scientifique (N02xx)** est livré comme **un unique blob chiffré/opaque**. On
peut le **télécharger, vérifier (taille + SHA-256), mettre en cache et flasher verbatim**,
mais on **ne peut pas l'introspecter** : la version ne provient que du manifeste.

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

> **[Observé matériel — capture lecture seule]** Branchée, une N0200 s'énumère en
> `0483:A51A` (bcd `0x0200`, Product `NumWorks Scientific Calculator`) et **annonce** dans sa
> chaîne de layout DFU la région `@FirmwareHeader/0x080040C0/01*64Ba` (1×64 KiB, base flash CPU
> `0x08000000`) — donc distincte de l'adresse d'écriture `0x98000000` du fichier `.dfu`. À garder
> en tête si on implémente un jour la lecture/écriture bas niveau N0200 : l'adresse annoncée par
> le descripteur (reads) et la cible du `.dfu` (write bootloader) ne coïncident pas.

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
- **Version** : elle vient **du manifeste** (`3.0.0`), jamais du binaire. `read_installed_version`
  renvoie `None` sur N02xx — c'est **attendu**, pas un échec.
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
