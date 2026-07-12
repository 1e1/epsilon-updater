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
