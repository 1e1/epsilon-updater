# Analyse du stack WebUSB/WebDFU « officiel » (côté hôte)

But : comprendre les **fonctionnalités officielles** du Workshop `my.numworks.com` en lisant le
code hôte réellement servi/dérivé, puis **recouper chaque structure avec le firmware `epsilon`**
(vérité on-device). Convention repo : **[confirmé]** (lu en source) vs **[inféré]**.

## Provenance

Le [blog NumWorks](https://www.numworks.com/blog/webusb-firmware-update/) confirme **[confirmé]** :
mise à jour **WebUSB dans Chrome**, via un **« Workshop »** navigateur. Il ne nomme aucune lib.
Le stack se lit dans deux artefacts publics que NumWorks a essaimés / la communauté maintient :

| Couche | Fichier(s) | Origine |
|---|---|---|
| Transport DFU/DfuSe | `dfu.js`, `dfuse.js` | lib **WebDFU** (devanlai) forkée ; miroir `TI-Planet/webdfu_numworks` (`n0100/`, `n0110/`) |
| Métier (classe `Numworks`) | `Numworks.js`, `Storage.js`, `Recovery.js` | `Omega-Numworks/numworks.js` (npm `numworks.js`, auteur M4x1m3) |

> Ces libs sont **communautaires** mais implémentent le **même** protocole WebUSB+WebDFU que le
> Workshop. Toute structure ci-dessous est **recoupée avec `epsilon`** (autorité). Citations JS =
> `Fichier:ligne` de la version lue en juillet 2026.

> **Attestation : aucune (hors ligne).** Recherche `fetch`/`XMLHttpRequest`/`WebSocket`/`http(s)://`
> dans tout le flux : rien de réseau pendant le flash (seuls des `navigator.usb.*`). Le seul contact
> serveur = le **téléchargement** du `.dfu` pré-signé (protégé par compte). L'authenticité
> (« officiel » / mode examen) est vérifiée **on-device par le bootloader** (signature Ed25519 du
> slot, au boot à froid) — détail dans
> [../01-specs/firmware-authenticity.md](../01-specs/firmware-authenticity.md).

## Architecture en 3 couches (= la nôtre)

```
navigator.usb (WebUSB, Chrome)          control transfers bruts
  └─ dfu.js / dfuse.js (WebDFU)         DFU/DfuSe : SET_ADDRESS, ERASE_SECTOR, UPLOAD/DNLOAD, FSM
       └─ Numworks / Storage / Recovery fonctions métier du Workshop
```

Miroir exact de `nwupdater` : `dfu/protocol.py` = couche WebDFU ; `catalog`/`apps`/identité = métier.

## Cartographie des fonctions (côté hôte)

| Fonction Workshop | Méthode JS | DFU | Adresse / magic | Recoupé firmware |
|---|---|---|---|---|
| Détecter | `detect` / `autoConnect` | `requestDevice(VID 0x0483, PID 0xA291)`, poll 1×/s | — | ✓ `Numworks.js:148,339` |
| Modèle | `getModel` | somme tailles segments DFU | 64K int+8M ext=`0110` ; 1M int=`0100` | ✓ `:45-83` |
| platforminfo | `getPlatformInfo` | `UPLOAD` 100 o | **fixe `0x080001C4`**, magik `0xF00DC0DE`, version@0x04, commit@0x0C, storage.addr@0x14 / size@0x18 | ✓ `:306` |
| Flash interne | `flashInternal` | erase+DNLOAD + **reboot** (`manifestationTolerant=true`) | `0x08000000` | ✓ `:90` |
| Flash externe | `flashExternal` | erase+DNLOAD, **sans reboot** | `0x90000000` | ✓ `:100` |
| Lire scripts | `backupStorage` | `UPLOAD(storage.addr, size+8)` → parse | SRAM `0x20…` | ✓ `:441` |
| Écrire scripts | `installStorage` | ré-encode **tout** → `DNLOAD(storage.addr, blob, false)` | SRAM `0x20…` | ✓ `:427` |
| Recovery | `Recovery.flashRecovery` | bootloader **ROM ST**, flasher **en RAM** | `0x20030000` (=`FlasherOffset`) | ✓ `Recovery.js:63` |
| Apps `.nwa` | — **ABSENT** | *(aucune méthode)* | — | flux propre à `my.numworks.com/apps` |

## Scripts Python — format recoupé (JS ↔ firmware)

`Storage.js` encode/parse **exactement** le file system `epsilon` :

- **Magic** : octets `BA DD 0B EE`, lu big-endian `0xBADD0BEE` (`Storage.js:68,138`) = little-endian
  `0xEE0BDDBA` = `file_system.h:159`. **Mêmes octets. En TÊTE uniquement.**
- **Record** : `[Size u16 LE][FullName"."ext + \0][Body]`, `Size` = longueur totale (`:84-96,143-149`).
- **Body `.py`** : `[octet autoImport 0/1][code UTF-8][\0]` (`:42-50,191-197`) = `Status` bit0 du firmware.
- **Fin de zone** : mot **`Size = 0x0000`** (`:99` écrit `[0,0]` ; `:145` s'arrête à `size===0`).
  Recoupé firmware : `overrideSizeAtPosition(newRecord, 0)` [`file_system.cpp:223`] ; idem après
  suppression avec `memmove` de compaction [`:349,:366`]. **Ce n'est pas un second magic.**
- Objet manipulé : `{name, type:"py", autoImport, code, position?}`. `position` (u16) = extension
  **Upsilon** uniquement (`:24-26,:193`).

Le firmware **compacte par `memmove`** à chaque `destroyRecord` → le store est un **tableau packé,
sans trous internes** (une seule zone libre = la queue jusqu'à `k_totalSize = 42 KiB`).

## Deux confirmations importantes

1. **Storage = SRAM (volatile).** `Numworks.js:194-202` **ajoute manuellement** le segment RAM
   `0x20000000–0x20040000` (`erasable:false, writable:true`) car *« the device doesn't expose that
   normally »*. Le code officiel lit/écrit donc les scripts **en RAM**. Corollaire matériel :
   la « persistance à l'extinction » = **rétention SRAM en veille** (`Ion::Power::suspend`), **pas**
   un backup flash (aucun dans la source) → **batterie vide/retirée ⇒ scripts perdus**.
2. **Read-modify-write de TOUTE la région.** `installStorage` (`:427-434`) réassemble
   l'intégralité du store (`encodeStorage(size)`) et le `DNLOAD` d'un bloc. **Aucune écriture
   unitaire** dans le flux officiel : on lit tout → on modifie côté PC → on renvoie tout.
3. **Bonus** : `dfuse.erase()` **saute les segments `erasable:false`** (`dfuse.js:199-205`) →
   écrire les scripts (SRAM) **n'efface rien** ; en flash il efface les secteurs couverts, avec
   `SET_ADDRESS` à **chaque** chunk (`:244`, style `dfu.py`).

> **Précision [CONFIRMÉ matériel — N0120]** : là où `numworks.js` doit *ajouter à la main* le
> segment SRAM (point 1), le **N0120 (H725) l'expose lui-même** comme une **alt-setting DFU
> distincte** : alt 0 `@Flash/0x90000000`, alt 1 **`@SRAM/0x24000000` (writable)**. Un `DNLOAD`
> ne s'applique qu'à la mémoire de l'**alt courante** : écrire les scripts alors que l'alt
> `@Flash` est sélectionnée est accepté mais **silencieusement ignoré**. `nwupdater` **découvre**
> les régions par alt (chaînes de layout, `usbio`) et **route** chaque écriture vers l'alt
> propriétaire de l'adresse (`DfuClient`), avec vérification par relecture (`scripts.write_storage`).
> C'est plus robuste que l'ajout en dur d'un segment : aucune adresse par modèle, donc
> N0100 … futur N0130 fonctionnent automatiquement.

## Divergences à connaître

- **Apps `.nwa` : rien** dans ces libs (grep vide sur `installApp|.nwa|external_app|0xDEC0BEBA`).
  `my.numworks.com/apps` écrit le `.nwa` en zone external-apps par un flux **propriétaire**.
  Notre `apps/installer.py` (écriture zone external-apps, alignée secteur 64K, magic `0xDEC0BEBA`)
  va **plus loin** que cette lib — adossé à `external_apps.cpp`, pas à ce JS.
- **platforminfo à `0x080001C4` (fixe)** = layout **classique mono-image** (N0100 / vieux OS).
  Le Workshop moderne **double-slot** et `nwupdater` suivent les **pointeurs SlotInfo** en SRAM
  (cf. `usb-dfu-protocol.md §7`). **Ne pas recopier** l'adresse fixe pour n0110 récent.

## Implications pour `nwupdater`

- **Algorithme de référence pour les scripts** : `backupStorage`/`installStorage` + le codec
  `Storage.js` → à porter tel quel dans un `StorageCodec` (§ region.py proposé). Zéro DFU nouveau.
- **Valide l'abstraction générique** : firmware/apps/scripts = même transport ; seuls changent
  alt (0/1), erase (secteur/aucun), base. L'officiel traite firmware **et** storage avec la même
  `do_download`, `manifestationTolerant` faisant seul la différence (reboot ou non).

Sources : `Omega-Numworks/numworks.js`, `TI-Planet/webdfu_numworks`, `UpsilonNumworks/upsilon.js`,
blog NumWorks WebUSB. Recoupement firmware : `shared/ion/.../storage/file_system.{h,cpp}`,
`.../drivers/external_apps.cpp`, `.../userland/drivers/userland_header.cpp`, `include/n0110/config/board.h`.

## Flux de flash officiel — capturé sur matériel réel

Le flux WebUSB officiel a été **instrumenté** (Chromium natif + shim `navigator.usb` journalisant
chaque transfert DFU ; réseau + `.dfu` capturés) sur une **N0120** et une **N0200** réelles.
Traces non commitées (règle : pas de firmware réel dans le dépôt).

**Aucune attestation en ligne** (les deux modèles) : le flash est une transaction locale
WebUSB→DfuSe sur un `.dfu` pré-téléchargé et **protégé par compte** (`401` sans login). Les seuls
appels serveur sont `POST /devices/<serial>` avant/après = **télémétrie de compte**
(`{device_model, software_version, software_patch_level}`), **pas** d'attestation ni de blocage.

### N0120 (graphique)
DFU userland `0x0483:0xA291`, filtres `[0xA291, 0xA51A]`, **une seule `requestDevice`, aucune
bascule de PID** (interface 0, alt 0 `@Flash` + alt 1 `@SRAM`). Séquence : **26× ERASE** du slot
**inactif** (secteurs de 64 Kio), puis `SET_ADDRESS` par bloc de 2 Kio + `DNLOAD` (~1,48 Mio) ;
rafraîchit les **secteurs persistants** `0x903f0000`/`0x907f0000` (exam-bytes — **optionnel**, le
firmware ré-initialise à « Off » un état non initialisé) ; écrit ~42 Kio en **SRAM** (`alt 1`,
sauvegarde/restauration du storage utilisateur). **N'écrit PAS la flash interne `0x08000000`** —
ce qui confirme que notre approche « slot inactif seul » est correcte. **Chrono : ~27 s
d'écriture, ~37 s connexion→fin** (à parité avec notre outil : 26,3 s).

### N0200 (scientifique)
Mode `0x0483:0xA51A` (pas de bascule de PID, pas de mode flasher séparé ; le layout RO annoncé
`@FirmwareHeader/0x080040C0/64Ba` est trompeur — il accepte les écritures DfuSe). Écrit un
**élément unique à `0x98000000`** (~237 Kio), **sans ERASE**, `SET_ADDRESS` par bloc + `DNLOAD`.
`.dfu` = DfuSe standard (1 cible / 1 élément `0x98000000`, suffixe 16 o pid `0xA51A`, **aucune
signature ajoutée** après le suffixe). **Chrono : ~8,4 s d'écriture, ~13 s connexion→fin.**

### Terminaison → reste « officiel » (les deux modèles)
Le flux termine par un `SET_ADDRESS 0x08000000` + **`DNLOAD` de longueur nulle** = `leave` vers la
**base flash interne (le bootloader)**. `0x08000000` n'étant **pas** un secteur reflashable, le
firmware fait `Reset::core()` (**boot à froid**) → le bootloader **re-vérifie la signature** →
**officiel, sans RESET manuel**. Un `leave` *dans* un slot (ce que faisait notre `boot()`) le
marque « UNOFFICIAL SOFTWARE ». D'où le correctif `boot()` → `leave(BOOTLOADER_RESET_ADDRESS)`.
Voir [../01-specs/firmware-authenticity.md](../01-specs/firmware-authenticity.md).
