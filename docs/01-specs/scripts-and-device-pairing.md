# Lot 1 — « My Devices » (appairage) & « My Scripts » (lecture/écriture des scripts)

Deux fonctions de l'atelier `my.numworks.com` reposent **entièrement** sur des briques déjà
spécifiées ailleurs — elles n'ajoutent aucun protocole USB nouveau, seulement des lectures/
écritures ciblées + un appel HTTP côté serveur. À lire avec :

- **[usb-dfu-protocol.md](usb-dfu-protocol.md)** — commandes DFU, `platforminfo`, carte mémoire.
- **[os-architecture.md](os-architecture.md)** — chaîne de boot, slots.
- **[../02-update-catalog/web-api.md](../02-update-catalog/web-api.md)** & `catalog/auth.py` — auth `my.numworks.com`.

Sources : **[epsilon:…]** firmware local ; **[webdfu]** `TI-Planet/webdfu_numworks`.

> Côté **serveur** (`my.numworks.com`), rien n'est lisible dans le firmware local : les
> requêtes HTTP décrites plus bas sont **inférées** du comportement observable du workshop
> WebUSB et marquées comme telles. Côté **calculatrice**, tout est confirmé en source.

---

## 1. Ce que font les deux fonctions

| Fonction | Rôle | Côté calculatrice | Côté compte |
|---|---|---|---|
| **My Devices** (« Mes calculatrices ») | Associer une calculatrice physique au compte : modèle, n° de série, version OS. Sert au suivi (garantie, historique de MàJ, affichage). | **Lecture seule** : USB descriptors + `platforminfo`. | Le navigateur POST les métadonnées lues vers l'API. |
| **My Scripts** (« Mes scripts ») | Éditer en ligne les scripts Python et les synchroniser avec la calculatrice. | **Lecture** (UPLOAD) et **écriture** (DNLOAD) de la zone *storage* en SRAM. | Stockage des scripts sur le compte + éditeur web. |

Point commun : le navigateur parle en **WebUSB/DfuSe** à la calculatrice (mêmes commandes
qu'au §3 de [usb-dfu-protocol.md](usb-dfu-protocol.md)), puis dialogue en HTTPS avec le
compte. **Aucune authentification cryptographique** entre le PC et la calculatrice : c'est de
l'*identification* (on lit un n° de série), pas de l'*appairage* au sens sécurisé.

---

## 2. My Devices — appairage / identification

### 2.1 Ce que le site lit sur la calculatrice
Trois sources, toutes en lecture seule :

1. **`bcdDevice`** du device descriptor → **modèle** (`"n%04x"`) — cf. usb-dfu-protocol §1.
2. **`iSerialNumber`** (string descriptor **index 3**) → **numéro de série** (§2.2).
3. **`platforminfo`** (SlotInfo → Userland/Kernel headers) → **version OS + commit** —
   cf. usb-dfu-protocol §7–8.1. Pas besoin d'entrer en DFU pour 1–2 (descripteurs USB
   standards) ; 3 nécessite le mode DFU userland.

### 2.2 Le numéro de série — clé de l'appairage
Confirmé en source [epsilon:shared/ion/src/device/shared/drivers/serial_number.cpp] :

```
serial = Base64( 12 octets bruts @ UniqueDeviceIDAddress )   → 16 caractères ASCII
```

- Les 12 octets sont l'**Unique Device ID** du MCU STM32 (registre en ROM système, jamais
  modifiable) [serial_number.cpp:13-16].
- Longueur fixe **16** [serial_number.h:7 `k_serialNumberLength = 16`].
- Adresse de l'UID par famille [include/\<modèle\>/config/serial_number.h] :

  | Modèle | `UniqueDeviceIDAddress` | MCU |
  |---|---|---|
  | n0110 / n0115 | `0x1FF07A10` | STM32F7 |
  | n0120 | `0x1FF1E800` | STM32H7 |
  | n0100 / n02xx | *(non présent dans ce fork)* — **inféré** : registre UID de leur MCU respectif | |

- Exposé tel quel comme `iSerialNumber` #3 du device descriptor
  [calculator.h:54,99,110] → **lisible sans entrer en DFU**, par simple `GET_DESCRIPTOR`.

> Le n° de série est **déterministe** (dérivé de l'UID matériel) : deux lectures de la même
> calculatrice donnent la même valeur ; il identifie donc l'appareil de façon stable.

### 2.3 Flux d'appairage (côté serveur)
1. L'utilisateur est authentifié (cookie de session `my.numworks.com`, cf. Lot 6).
2. WebUSB lit modèle + n° de série + version OS (§2.1) — **notre outil sait déjà le faire en
   DFU** (§2.4), donc sans Chrome.
3. Le navigateur **POST** ces champs au formulaire d'enrôlement (portail
   `/devices/upgrade/`). L'URL exacte + les champs du POST ne sont **pas confirmés en
   source** → à **découvrir par inspection** (§2.5), pas à deviner.
4. Le compte enregistre la calculatrice (n° de série = identifiant unique).

> **Deux « sans Chrome » distincts** :
> - **Création du compte utilisateur** = formulaire web pur (Devise `POST /users`), aucun
>   WebUSB → rejouable en headless exactement comme le login (`auth.login_with_password`).
>   Réserves : CAPTCHA / confirmation e-mail / CGU probables (à confirmer par inspection).
> - **Enrôlement du device** = déclenché par **Chrome/WebUSB** (lecture de la calculatrice
>   puis POST). Le POST est rejouable une fois son gabarit connu → on l'**inspecte** (§2.5).

### 2.5 Inspection de l'enrôlement — ✅ **outillée** (lecture seule)
`capture_session.inspect_enrollment()` fait un **GET** du portail `/devices/upgrade/` (cookie
d'auth) et en extrait le gabarit du formulaire via `net_capture.inspect_forms()` : `action`,
`method`, noms de champs, présence CSRF, présence CAPTCHA. **Aucun POST → rien n'est enrôlé.**
Intégré au dump de la commande `capture` (clé `enrollment`), les formulaires de toute page
HTML capturée sont aussi résumés automatiquement. Un volontaire joue la capture une fois sur
une vraie machine → on obtient le gabarit réel du POST, base d'un futur `nwupdater enroll`.

### 2.4 Réimplémentation headless — ✅ **implémentée** (lecture)
Tout le côté calculatrice est couvert : `dfu/identity.py` lit modèle + version
(`platforminfo`) **et** le numéro de série :

- `DfuClient.get_string_descriptor(index)` [dfu/protocol.py] émet un `GET_DESCRIPTOR(String)`
  standard (`bmRequestType=0x80, bRequest=0x06, wValue=(0x03<<8)|index`) et décode l'UTF-16LE.
  Requête **standard**, valide dans n'importe quel état DFU → n'interfère pas avec la FSM.
  **Transport-agnostique** : même code pour le device virtuel et le matériel réel (c'est ce
  que fait `usb.util.get_string` en interne).
- `read_identity()` peuple `CalculatorIdentity.serial_number` (index 3 par défaut, cf.
  `constants.SERIAL_STRING_INDEX`). Absence tolérée (bootloader ST brut) → `None`.
- Surfacé partout : CLI `identify` + `diagnose` (champ `serial_number` du rapport JSON),
  UI web (ligne « N° de série »), flux `capture`.
- Le device virtuel expose un série synthétique **déterministe** (`_synth_serial` : Base64 de
  12 octets dérivés du bcdDevice) → testable end-to-end sans USB.

> L'**enregistrement sur le compte** `my.numworks.com` reste **hors périmètre** : c'est une
> mutation du compte via des endpoints inférés (non vérifiés en source). L'outil se limite à
> **lire** le n° de série (identification en lecture seule).

---

## 3. My Scripts — lecture/écriture des scripts déjà sur la calculatrice

Les scripts Python sont des **enregistrements** du *file system* embarqué. Les lire = lire la
zone *storage* en SRAM par UPLOAD DfuSe et parser le format ci-dessous. Les écrire =
reconstruire le buffer et le DNLOAD au même endroit.

### 3.1 Où est le storage
La zone est **auto-décrite** par le header userland (ne jamais coder en dur) :

| Source | Champ | Sens |
|---|---|---|
| UserlandHeader @0x0C | `m_storageAddressRAM` | base du storage en SRAM |
| UserlandHeader @0x10 | `m_storageSizeRAM` | taille de la zone |

(cf. usb-dfu-protocol §7.3). Taille interne du file system : **42 KiB**
[epsilon:shared/ion/include/ion/storage/file_system.h:29 `k_totalSize = 42*1024`].

Procédure : suivre `platforminfo` (§8.1) → lire `m_storageAddressRAM/Size` → **UPLOAD** cette
plage (par blocs de 2048, §5 du protocole) → parser (§3.2).

### 3.2 Format du file system
[file_system.h:14-17, file_system.cpp:430-438] :

```
| Magic | Record1 | Record2 | … | 0x0000 |
Magic = 0xEE0BDDBA  (uint32 little-endian) — en TÊTE uniquement
Fin   = un mot Size = 0x0000 (PAS un second magic)
```

Chaque **Record** :

| Champ | Taille | Sens |
|---|---|---|
| `Size` | `uint16` (LE) | **taille totale** de l'enregistrement (ce champ + FullName + Body) |
| `FullName` | ASCII, **null-terminée** | `baseName.extension`, ex. `mandelbrot.py` |
| `Body` | `Size − 2 − len(FullName+\0)` | contenu brut |

- Fin de zone = un mot `Size == 0` (`0x0000`), écrit par `overrideSizeAtPosition(newRecord, 0)`
  [file_system.cpp:223 ; idem après suppression + `memmove` de compaction, :349/:366]. **Ce n'est
  PAS un second magic** — le magic `0xEE0BDDBA` n'est qu'en tête (confirmé côté hôte par
  `Storage.js`, cf. [../reference/official-webusb-analysis.md](../reference/official-webusb-analysis.md)).
- Le store est **compacté** (`memmove`) à chaque suppression → tableau **packé, sans trous
  internes** ; la seule zone libre est la queue jusqu'à `k_totalSize`.
- `record_size_t = uint16` → un record ≤ 64 Kio (borné par les 42 Kio du store).

### 3.3 Format d'un script (`.py`)
Un script = un record d'extension **`py`** [script_store.h:16 `k_scriptExtension = "py"`].
Son **Body** vaut [script.h:7-8, 36-39, 48-84] :

```
Body = | Status (1 octet) | Content (texte Python, null-terminé) |
```

`Status` (1 octet de bits) [script.h:48-84] :

| Bit | Nom | Sens |
|---|---|---|
| 0 | `autoImportation` | script importé automatiquement à l'ouverture de la console (**défaut = 1**) |
| 6 | `fetchedForVariableBox` | garde anti-import circulaire (runtime) |
| 7 | `fetchedFromConsole` | drapeau runtime |

→ Le **contenu éditable** commence à `Body + 1`. Pour l'affichage web, on saute l'octet de
statut ; pour ré-écrire, on le **préserve** (ou on met `0x01` pour un nouveau script auto-
importé, valeur par défaut du constructeur `Status()` [script.h:50]).

Nom : `([a-z_][a-z0-9_]*)\.py`, le nom vide `.py` étant toléré [script.cpp:21-24].

### 3.4 Lire les scripts (lecture seule, sûre)
1. `platforminfo` → `m_storageAddressRAM`, `m_storageSizeRAM` (§3.1).
2. UPLOAD la plage.
3. Vérifier `Magic 0xEE0BDDBA` en tête.
4. Itérer les records : lire `Size` (u16), lire `FullName` jusqu'à `\0`, jusqu'à `Size==0`.
5. Filtrer les `*.py` ; pour chacun : `autoImport = Body[0] & 1`, `code = Body[1:].rstrip('\0')`.

C'est **non destructif** : on ne fait que des UPLOAD (lecture mémoire).

### 3.5 Écrire les scripts (**mutant — implémenté, derrière confirmation**)
Reconstruire le buffer complet du store (magic + records + `0x0000`) et le DNLOAD à
`m_storageAddressRAM` (alt setting **1 = SRAM**, cf. usb-dfu-protocol §6.4). Contraintes :

> **[CONFIRMÉ matériel — N0120]** Le choix de l'**alt-setting** est décisif : un `DNLOAD` en SRAM
> alors que l'alt `@Flash` est sélectionnée est **accepté (status OK) mais silencieusement
> ignoré** — l'écriture n'atterrit pas. La N0120 expose deux alt-settings — `@Flash/0x90000000`
> (alt 0) et **`@SRAM/0x24000000` (alt 1, writable)** — et un `DNLOAD` ne s'applique qu'à la
> mémoire de l'alt **courante** (les `UPLOAD`/lectures marchent partout). L'app **découvre** ces
> régions dans les chaînes de layout de chaque alt (`usbio`) et **route** chaque écriture vers
> l'alt dont la région contient l'adresse (`DfuClient`) — donc rien codé en dur par modèle, et
> N0100…futur N0130 marchent automatiquement. `write_storage` **vérifie par relecture** et lève
> si l'écriture n'a pas atterri (plus de faux succès silencieux). Validé write→verify→rollback
> sur une vraie N0120.

- Respecter `k_totalSize = 42 KiB` : refuser si le total dépasse.
- Le storage est en **SRAM** → **volatile**. ⚠️ Correction : il n'existe **aucun backup flash** du
  storage dans la source (`FileSystem::sharedFileSystem` = `char m_buffer[42 KiB]` en .bss userland ;
  aucune section flash, aucune routine de sauvegarde). Ce qui préserve les scripts « éteint », c'est
  que la calc ne s'éteint pas vraiment : `Ion::Power` fait une **veille à rétention SRAM**
  (`suspend()`), pas une coupure. **Corollaire : batterie totalement vide ou retirée → scripts
  perdus.** Confirmé côté hôte par `numworks.js`, qui doit **ajouter à la main** le segment RAM
  `0x20000000–0x20040000` pour lire/écrire le store (cf.
  [../reference/official-webusb-analysis.md](../reference/official-webusb-analysis.md)). Écrire
  pendant qu'Epsilon tourne demande de la prudence (cohérence avec l'état RAM de l'app Code).
- **Écriture = mutation de l'appareil** → soumise aux mêmes garde-fous que le flash (Lot 3) :
  confirmation explicite, jamais silencieux. Non retenu comme objectif tant que le harnais
  matériel réel (branche `develop`) n'est pas validé.

### 3.6 Réimplémentation headless
- **Lecture** : ajout naturel et sûr. Un module `storage.py` : parse le format §3.2/§3.3,
  s'appuie sur `dfu/identity.py` (pour `m_storageAddressRAM`) + `dfu/protocol.py` (UPLOAD).
  Testable contre le **device virtuel** en injectant un buffer storage synthétique.
- **Écriture** : **implémentée** (`scripts.write_storage` + routage d'alt-setting du `DfuClient`,
  §3.5), derrière confirmation. Validée sur N0120 réelle (write→verify→rollback).

---

## 4. Rattachement au périmètre projet
- **Lecture identité + n° de série + scripts** = extensions **lecture seule**, alignées sur
  la contrainte « on lit, on ne modifie pas » → candidates au rapport `diagnose`.
- **Appairage compte** et **écriture de scripts** = **mutations** (compte ou appareil) →
  hors objectif par défaut ; documentées ici pour complétude.

## 5. Incertitudes
- **Endpoints HTTP `my.numworks.com`** (devices, scripts) : **inférés**, non vérifiés en
  source (code serveur non public).
- **UID address n0100 / n02xx** : registre absent de ce fork → à confirmer sur matériel.
- **Cohérence d'écriture du storage en RAM** pendant qu'Epsilon tourne (fenêtre vis-à-vis de l'app
  Code) : **partiellement levé** — l'écriture atterrit et se relit correctement sur N0120 réelle
  **à condition de sélectionner l'alt `@SRAM`** (§3.5) ; le comportement au réveil de l'app Code
  reste à observer. La persistance « à l'extinction » = **rétention SRAM en veille**, pas un
  backup flash (cf. §3.5) — le mode `standby()` (perte SRAM) et le point exact de rétention restent à
  confirmer sur matériel (driver power côté kernel, absent de ce fork).
