# Lot 1 — Protocole USB DFU/DfuSe (référence côté hôte)

Spécification pour **réimplémenter le côté hôte** (l'ordinateur qui flashe) en headless, sans
WebUSB. C'est le cœur des Lots 3/4. Sources citées inline :

- **[epsilon:…]** — firmware local `/Users/agerlier/Documents/repogit/epsilon/…`
- **[dfu.py]** — flasher officiel `tools/device/dfu.py` (pyusb, sans dfu-util)
- **[webdfu]** — `TI-Planet/webdfu_numworks` branche `gh-pages` (`n0110/dfu.js`, `n0110/dfuse.js`)
- **[nwagyu]** — nwagyu.org

> `webdfu_numworks` est un fork de la lib générique WebDFU : rien de spécifique NumWorks
> au-delà de la détection de modèle. Il **corrobore** les codes de requête, la numérotation
> de blocs `(block-2)` et les sous-commandes DfuSe.

## 1. Identité USB (VID / PID / bcdDevice)

| Champ | Valeur | Source |
|---|---|---|
| idVendor | `0x0483` (STMicroelectronics — NumWorks réutilise le VID ST) | calculator.h:48, dfu.py:33 |
| idProduct (Epsilon userland DFU) | `0xA291` | include/n0110,n0115,n0120/config/usb.h |
| bcdUSB | `0x0210` (>0x0200 → active BOS/WebUSB) | calculator.h |
| bMaxPacketSize0 | 64 | calculator.h |
| iManufacturer | `"NumWorks"` | calculator.h |
| iProduct | `"NumWorks Calculator"` | config/usb.h |

**bcdDevice = modèle**, dérivé par l'hôte comme `"n%04x" % bcdDevice` [dfu.py:521-523] :
`0x0100`=n0100, `0x0110`=n0110, `0x0115`=n0115, `0x0120`=n0120, (`0x0200`=n0200 attendu).
`display_model()` valide `{n0100, n0110, n0115, n0120}` [dfu.py:550-555].

**PIDs à scanner** [dfu.py:32-36] :

| VID:PID | Rôle |
|---|---|
| `0483:DF11` | Bootloader **système STM32** (DFU ROM ST), atteint par RESET+touche. Sert à charger un flasher en RAM. |
| `0483:A291` | Calculatrice sous Epsilon, DFU-in-userland (**cas normal**). Confirmé en source. |
| `0483:A51A` | Bootloader/flasher NumWorks custom. *Rôle inféré (dfu.py uniquement), à confirmer.* |

Le device descriptor a class/subclass/protocol = 0 → l'identité DFU est dans **l'interface**.
Pour identifier un DFU quel que soit le PID, matcher l'interface :
`bInterfaceClass==0xFE && bInterfaceSubClass==1 && bInterfaceProtocol∈{1,2}` [dfu.py:470].

## 2. Descripteurs DFU

**Interface** (2 alternate settings sur l'interface 0) [dfu_interfaces_helpers.h, dfu_interfaces.cpp] :

| Champ | Valeur |
|---|---|
| bInterfaceNumber | 0 |
| bAlternateSetting | **0 = Flash**, **1 = SRAM** |
| bNumEndpoints | 0 (control-only, EP0) |
| bInterfaceClass / SubClass / Protocol | `0xFE` / `1` / `2` (**DFU mode**) |
| iInterface | chaîne de layout mémoire (§6.4) |

**DFU Functional Descriptor** (bDescriptorType `0x21`) [calculator.h, dfu_interfaces_helpers.h] :

| Champ | Valeur | Note |
|---|---|---|
| bmAttributes | `0b0011` | canDnload=1, canUpload=1, manifestationTolerant=0, willDetach=0 |
| wDetachTimeOut | `0` | inutilisé (userland) |
| **wTransferSize** | **`2048`** | payload max d'un control-write ; `Endpoint0::MaxTransferSize=2048` |
| bcdDFUVersion | `0x0100` | numérotation DFU 1.0, mais extensions **DfuSe** utilisées |

> `manifestationTolerant=0` → après le download final, l'appareil **reset et doit être
> ré-énuméré**. On ne peut pas continuer sur le même handle après « leave ».

## 3. Jeu de commandes (control transfers)

Toutes les requêtes DFU sont **class / recipient=interface** → `wIndex = 0` (n° interface) :
- Host→Device (OUT) : `bmRequestType = 0x21`
- Device→Host (IN) : `bmRequestType = 0xA1`

| Requête | bRequest | bmReqType | wValue | Data | Action |
|---|---|---|---|---|---|
| DFU_DETACH | 0 | `0x21` | timeout | — | détache |
| DFU_DNLOAD | 1 | `0x21` | wBlockNum | ≤2048 o | écriture / commande (§4) |
| DFU_UPLOAD | 2 | `0xA1` | wBlockNum | renvoie ≤2048 o | lecture (§5) |
| DFU_GETSTATUS | 3 | `0xA1` | 0 | renvoie **6 o** | statut + pilote la FSM |
| DFU_CLRSTATUS | 4 | `0x21` | 0 | — | statut→OK, état→dfuIDLE |
| DFU_GETSTATE | 5 | `0xA1` | 0 | renvoie **1 o** | bState |
| DFU_ABORT | 6 | `0x21` | 0 | — | statut→OK, état→dfuIDLE |

**Réponse GETSTATUS (6 octets)** [dfu_interface.cpp:19-26] :
`[0]=bStatus · [1..3]=bwPollTimeout (24 bits LE, ms) · [4]=bState · [5]=iString`.
`dfu.py` lit l'état en `stat[4]` et dort `stat[1]/1000` s.

**bState** : `appIDLE=0, appDETACH=1, dfuIDLE=2, dfuDNLOAD_SYNC=3, dfuDNBUSY=4,
dfuDNLOAD_IDLE=5, dfuMANIFEST_SYNC=6, dfuMANIFEST=7, dfuMANIFEST_WAIT_RESET=8,
dfuUPLOAD_IDLE=9, dfuERROR=10`.

**bStatus** : `OK=0x00, errTARGET=0x01, errFILE=0x02, errWRITE=0x03, errERASE=0x04,
errCHECK_ERASED=0x05, errPROG=0x06, errVERIFY=0x07, errADDRESS=0x08, errNOTDONE=0x09,
errFIRMWARE=0x0A, errVENDOR=0x0B, errUSBR=0x0C, errPOR=0x0D, errUNKNOWN=0x0E,
errSTALLEDPKT=0x0F`.

## 4. DFU_DNLOAD (wValue = wBlockNum) — sémantique

[dfu_interface.cpp:30-65, 135-153] :

- **wValue == 0** → **commande DfuSe** (`data[0]` = sous-commande, §4.1).
- **wValue == 1** → réservé : stall EP0.
- **wValue ≥ 2** → bloc de données : adresse d'écriture = `(wValue − 2) × 2048 + addressPointer`.
  L'écriture flash réelle a lieu au **2ᵉ GETSTATUS** après le DNLOAD
  (dfuDNLOAD_SYNC → dfuDNBUSY → write → dfuDNLOAD_IDLE).
- **wLength == 0** → leave/manifest : dfuMANIFEST_SYNC → dfuMANIFEST → reset + jump (§8).

> Deux stratégies hôte valides :
> - **dfu.py** : re-`set_address` avant *chaque* chunk de 2048, toujours `wValue=2`.
> - **DfuSe standard (webdfu)** : `set_address` une fois, puis `wValue = 2,3,4,…`.

### 4.1 Sous-commandes DfuSe (DNLOAD, wValue=0), `data[0]` :

| Octet | Nom | Payload | Encodage |
|---|---|---|---|
| `0x21` | **Set Address Pointer** | `[0x21][addr:u32 LE]` (5 o) | appliqué après le GETSTATUS suivant |
| `0x41` | **Erase secteur** | `[0x41][addr:u32 LE]` (5 o) | efface le secteur à `addr` |
| `0x41` | **Mass erase** | `[0x41]` (1 o) | efface tout |
| `0x92` | ReadUnprotect | — | défini, **non implémenté** |

Encodages hôte [dfu.py:198-228] :
```python
set_address(addr): ctrl(0x21, DNLOAD, wValue=0, data=struct.pack("<BI", 0x21, addr))  # 5 o
page_erase(addr):  ctrl(0x21, DNLOAD, wValue=0, data=struct.pack("<BI", 0x41, addr))  # 5 o
mass_erase():      ctrl(0x21, DNLOAD, wValue=0, data=b"\x41")                          # 1 o
```

**Protocole de complétion** (Set-Address, Erase, écritures) : après le DNLOAD,
`GETSTATUS → attendre dfuDNBUSY(4)`, puis `GETSTATUS → attendre dfuDNLOAD_IDLE(5)`.
L'action différée s'exécute pendant ce 2ᵉ GETSTATUS.

## 5. DFU_UPLOAD (lecture mémoire) — wValue = wBlockNum

[dfu_interface.cpp:155-188] :
- wValue==0 → liste des commandes (non implémenté, rien renvoyé).
- wValue==1 → stall.
- **wValue ≥ 2** → adresse lue = `(wValue − 2) × 2048 + addressPointer` ;
  renvoie `min(wLength, 2048)` octets.

**Point clé** : en **alt 0 (Flash backend)** = `DFUFlashBackend(0, UINT32_MAX)`, `read()` est
un simple `memcpy` depuis **n'importe quelle adresse mappée** (flash interne, flash externe,
SRAM), `length ≤ 2048`. → **UPLOAD lit tout header** (SlotInfo, Kernel/Userland headers). Alt
1 = RAM backend (SRAM r/w).

Boucle type : `set_address(base)`, puis UPLOAD `wValue=2` (premiers 2048 o), incrément pour
la suite.

## 6. Carte mémoire & layout DFU

### 6.1 Régions [board.h par modèle]

| Région | Base | Taille | n0110 | n0115 | n0120 |
|---|---|---|---|---|---|
| Flash interne | `0x08000000` | 64 KiB (4×16K) | ✓ | ✓ | — |
| Flash interne | `0x08000000` | 512 KiB (4×128K) | — | — | ✓ |
| Flash externe QSPI | `0x90000000` | 8 MiB | ✓ | ✓ | ✓ |
| SRAM | `0x20000000` | 256 KiB | ✓ | ✓ | — |
| SRAM (AXI) | `0x24000000` | 256 KiB | — | — | ✓ |

Le **bootloader occupe la flash interne** ; l'**OS (kernel+userland) vit en flash externe
QSPI**. Secteurs : n0110/n0115 = `{08000000,08004000,08008000,0800C000,08010000}` (16K) ;
n0120 = `{08000000,08020000,08040000,08060000,08080000}` (128K).

> **N0100 & N0200** : pas de QSPI. OS en flash interne (`0x08000000`). N0200 = 256 KiB total.

### 6.2 Slots externes (n0110/n0115/n0120)
8 MiB = 2 slots de 4 MiB :

| Slot | Origine | Contenu |
|---|---|---|
| **A** | `0x90000000` | SP-header+Kernel(64K) → ExtraData(0/64K) → Userland → Signature → Apps externes → Persisting(64K) |
| Khi | `0x90180000` | slot fork tiers [nwagyu] |
| **B** | `0x90400000` | structure identique |

Userland header ≈ `0x90010000` (sans extra data) ou `0x90020000` (avec) pour slot A ;
+0x400000 pour B. **Ne pas hardcoder** — lire via SlotInfo (§7).

### 6.4 Chaînes de layout DFU (iInterface) — secteurs writables
Format : `@Nom/0xADDR/N*<taille><unité><accès>[,…]`. Accès : `a`=lecture, `e`=lecture+erase,
`g`=lecture+erase+write. Parsées par `get_memory_layout`/`parseMemoryDescriptor`.

```
SRAM  (alt1) n0110/n0115: @SRAM/0x20000000/01*252Ke
SRAM  (alt1) n0120:       @SRAM/0x24000000/01*252Ke
Flash (alt0) auth, slot A: @Flash/0x90030000/61*064Kg,64*064Kg
Flash (alt0) auth, slot B: @Flash/0x90000000/08*004Kg,01*032Kg,63*064Kg/0x90430000/61*064Kg
Flash (alt0) tiers, slot A: @Flash/0x90030000/61*064Kg
Flash (alt0) tiers, slot B: @Flash/0x90430000/61*064Kg
```
Le slot **en cours d'exécution** protège son propre kernel+userland de l'écriture (`+0x30000`),
l'autre slot est pleinement writable.

### 6.5 Détection du slot actif [dfu.py:526-538]
Segment démarrant à `0x90400000` présent → slot **A** actif ; à `0x90000000` → slot **B**
actif ; les deux → « rescue » ; aucun → « unknown ».

## 7. « platforminfo » : SlotInfo → KernelHeader / UserlandHeader

> Attention notation des magics : le littéral C++ est un `uint32_t` little-endian ; nwagyu
> cite l'ordre des octets en flash. Les deux désignent les mêmes octets.

### 7.1 SlotInfo — 16 o, à la base SRAM (`0x20000000` ou `0x24000000` n0120) [usb.h]
| Off | Champ | Valeur |
|---|---|---|
| 0x00 | magic header | C++ `0xEFEEDBBA` → octets `BA DB EE EF` → `0xBADBEEEF` |
| 0x04 | `KernelHeader*` | pointeur flash externe |
| 0x08 | `UserlandHeader*` | pointeur flash externe |
| 0x0C | magic footer | idem |

> SlotInfo n'est peuplé que si le DFU est entré **depuis Epsilon** (`willExecuteDFU()`). En
> DFU ST/bootloader brut, il peut être absent → valider les 2 magics avant de suivre les
> pointeurs.

### 7.2 KernelHeader — 24 o (aussi à `slotOrigin + 8`) [kernel_header.h]
| Off | Taille | Champ | Valeur |
|---|---|---|---|
| 0x00 | 4 | magic | C++ `0xDEC00DF0` → `F0 0D C0 DE` → `0xF00DC0DE` |
| 0x04 | 8 | `m_softwareVersion` | ex. `"23.2.4\0\0"` |
| 0x0C | 8 | `m_commitHash` | hash court ASCII |
| 0x14 | 4 | magic footer | `0xDEC00DF0` |

### 7.3 UserlandHeader — 48 o (0x30) [userland_header.h]
| Off | Champ | Sens |
|---|---|---|
| 0x00 | magic | C++ `0xDEC0EDFE` → `FE ED C0 DE` → `0xFEEDC0DE` |
| 0x04 (8 o) | `m_expectedSoftwareVersion` | **version OS à afficher** |
| 0x0C | `m_storageAddressRAM` | base storage RAM |
| 0x10 | `m_storageSizeRAM` | taille storage |
| 0x14 | `m_externalAppsFlashStart` | zone apps tierces (début) |
| 0x18 | `m_externalAppsFlashEnd` | zone apps tierces (fin) |
| 0x1C / 0x20 | `externalAppsRAMStart/End` | |
| 0x24 / 0x28 | `deviceNameFlashStart/End` | |
| 0x2C | magic footer | `0xDEC0EDFE` |

Validité : tous les pointeurs non nuls ET header==footer==`0xDEC0EDFE`.

## 8. Procédures hôte

### 8.1 Lire modèle + version OS installée (lecture seule, sûre)
1. Énumérer USB ; matcher VID `0x0483` + un PID (§1). `model = "n%04x" % bcdDevice`.
2. `set_configuration`, claim interface 0 ; amener à **dfuIDLE** (boucle GETSTATUS + ABORT/CLRSTATUS).
3. UPLOAD 16 o de SlotInfo depuis la base SRAM → vérifier magic `BA DB EE EF`.
4. Suivre `m_userlandHeaderAddress` (0x08) → UPLOAD 48 o → magic `FE ED C0 DE` → version @0x04.
   Version kernel via `m_kernelHeaderAddress`. Fallback si SlotInfo invalide : UPLOAD direct
   à l'adresse userland-header connue du slot actif (§6.2).
5. Slot actif via la chaîne de layout (§6.5).

### 8.2 Flasher un OS [dfu.py:583-616 `write_elements`]
Pour chaque élément `(addr, data)` du firmware (`.dfu` DfuSe ou `.bin` + adresse) :
1. (Option) `mass_erase()` → GETSTATUS busy→idle.
2. Pour chaque chunk de 2048 o à `addr` :
   a. si pas de mass-erase : `page_erase(page_base)` → busy → idle.
   b. `set_address(addr)` → busy → idle.
   c. DNLOAD `wValue=2`, data=chunk → **dfuDNBUSY** (écriture) → **dfuDNLOAD_IDLE**.
3. Cibles : flash externe `0x90xxxxxx` (n0110+), flash interne `0x08xxxxxx` (n0100/n0200).
   Hors plage → `errTARGET` ; secteur protégé → `errTARGET` à l'erase.

### 8.3 Quitter le DFU + jump [dfu.py:303-320, calculator_userland_leave.cpp]
1. `set_address(jumpAddress)`.
2. DNLOAD `wValue=2` avec **payload vide (wLength=0)** → dfuMANIFEST_SYNC.
3. GETSTATUS → dfuMANIFEST → `msleep(1)` → `leaveDFUAndReset()` (setResetOnDisconnect + detach).
4. **Cible du saut = `addressPointer + sizeof(UserlandHeader)` = `addressPointer + 0x30`**.
   Pour booter un slot, pointer sur son **userland header** ; le firmware saute 0x30 o après
   (init vector du userland).
   - Garde-fou : si `jumpAddress` tombe dans la zone apps externes, `leave()` ne saute pas.
   - `manifestationTolerant=0` → le handle tombe ; ré-énumérer pour reparler.

## 9. Distinguer variantes & compatibilité firmware

- **Discriminant primaire : `bcdDevice`** (§1) ; le seul signal modèle fiable sur DFU.
- Familles MCU : n0110/n0115 (OS en QSPI externe, SRAM `0x20000000`) ; n0120 (SRAM AXI
  `0x24000000` — signe distinctif) ; n0100 (flash interne 1 MiB, pas de slots) ; **n0200
  (STM32U073, flash interne 256K, pas de slots)** [inféré].
- **Ciblage du fichier `.dfu`** [dfu.py:362-459] : le **suffixe** porte
  idVendor/idProduct/bcdDevice + CRC32 ; chaque **élément** porte son adresse absolue.
  Vérifier suffixe `bcdDevice`/`idProduct` vs device connecté, et que les adresses tombent
  dans une région writable (chaîne de layout) avant de flasher. Prefix `"DfuSe"`, suffix
  `"UFD"`, version `0x011A`.
- **Compat kernel↔userland** vérifiée on-device : `UserlandHeader.expectedSoftwareVersion`
  doit matcher `KernelHeader.softwareVersion`. L'hôte lit les deux headers pour prévenir.
- **Authentifié vs tiers** : reflété par la chaîne de layout exposée (§6.4) — un userland
  non signé expose une fenêtre writable plus étroite + clearance réduite.

## 10. Incertitudes
- **N0100 / N0200** : tailles/secteurs de flash interne, PID exact — **inférés** (configs
  absentes de ce fork). Confirmés : bcdDevice pattern, MCU N0200 = STM32U073KC, 256K flash.
- **PID `0xA51A`** : rôle bootloader/flasher **inféré** (dfu.py uniquement).
- **SlotInfo** dépend d'une entrée DFU depuis Epsilon → valider les magics.
