# Lot 4 — Portage de `nwlink` : analyse & plan (se passer de Node)

Objectif backlog ([roadmap.md](../00-overview/roadmap.md)) : installer un `.nwa` **distribué**
(ELF relocalisable) **sans** dépendance Node/npm côté utilisateur. Ce document fige l'analyse,
compare les stratégies, et détaille le plan retenu.

**Décision (mise à jour 2026-07-27, après vérification de licence — §0) : portage BLOQUÉ en Phase 0.**
La stratégie B était retenue, mais la vérification de licence montre que **B *et* C exigent de
redistribuer le runtime EADK propriétaire** de NumWorks — ce qui n'est pas permis dans ce projet.
**Le chemin A (délégation `nwlink` via `npx`, déjà livré) reste la seule option propre.** B/C ne
seront rouverts qu'avec une **autorisation écrite de NumWorks**. Détails et sources en §0 et §5.

---

## 0. Vérification de licence — go/no-go (2026-07-27, bloquant)

Faits établis (sources en fin de doc) :
- **`nwlink` (paquet npm) = « All rights reserved »** — propriétaire NumWorks. Seuls les WASM
  embarqués `ld.wasm`/`objcopy.wasm` sont GPLv2 ; **le runtime EADK embarqué (`Uint8Array`) ne
  l'est pas** — il est couvert par le « all rights reserved ».
- **Epsilon OS = CC BY-NC-SA** historiquement (Attribution + **NonCommercial** + **ShareAlike**) ;
  l'issue upstream #1875 note que la mention CC a « disparu » → statut actuel au mieux NC/SA,
  au pire propriétaire par défaut (pas de fichier `LICENSE`).
- **`epsilon-sample-app-c` = BSD 3-Clause** — mais c'est le **gabarit d'app** que le publisher
  écrit, **pas** le runtime. Le runtime EADK (`_start` crt0 + les 10 stubs) est **fourni par
  nwlink** au moment du link → **aucune source permissive (BSD/MIT) à recompiler nous-mêmes**.

Pourquoi ça bloque B et C (et pas A) :
- Le modèle **A** (actuel) exécute `nwlink` **sur la machine de l'utilisateur** (`npx`) au moment
  de l'installation → le runtime EADK n'est **jamais** redistribué par nous ; chaque utilisateur
  l'obtient directement de NumWorks sous les termes de NumWorks. **Rien à redistribuer → GO.**
- **B** (lier 1× puis publier une image/`.nwb`) **introduit une redistribution du runtime** qui
  n'existe pas aujourd'hui (l'écosystème diffuse l'ELF `ET_REL` *pré-link* ; c'est nwlink qui
  ajoute le runtime en local). Publier une image liée = redistribuer les octets propriétaires
  NumWorks → **NO-GO** tel que le projet (ou son catalogue) l'héberge.
- **C** (linker pur-Python) doit **vendoriser** le runtime comme table réutilisable → redistribuer
  du code propriétaire NumWorks dans un dépôt MIT → **NO-GO** (et la piste Epsilon = CC BY-NC-SA
  est incompatible MIT + NC + ShareAlike de toute façon).

| Stratégie | Verdict licence | Motif |
|---|---|---|
| **A** délégation `npx nwlink` | ✅ **GO** | rien redistribué ; runtime obtenu par l'utilisateur chez NumWorks |
| **B** link CI + reloc pur-Python | ⛔ **NO-GO** | redistribue le runtime EADK propriétaire (image/`.nwb`) |
| **C** linker pur-Python complet | ⛔ **NO-GO** | vendorise le runtime EADK propriétaire dans le dépôt |

**Seul déblocage :** autorisation écrite de NumWorks de redistribuer le runtime EADK (rendrait B,
puis C, envisageables) — ou l'apparition d'un runtime EADK sous licence permissive (inexistant à ce
jour). À défaut, **on reste sur A**.

---

## 1. État actuel

### Chemin livré (fonctionne, validé N0120)
Délégation à `nwlink nwa-bin` en **offline** :
- [apps/link.py](../../src/nwupdater/apps/link.py) : `_resolve_nwlink()` (`NWUPDATER_NWLINK` →
  `npx --yes nwlink@0.0.19` → `nwlink` sur PATH), `link_nwa()` construit
  `nwa-bin --flash-start … --ram-start … --trampoline-start … in.nwa out.bin`.
- Câblé dans `AppManager._link_if_needed()` ([apps/manage.py](../../src/nwupdater/apps/manage.py)),
  avec garde `trampoline_word_looks_valid` (lit le mot trampoline sur l'appareil avant de lier).
- **Coût** : dépendance **Node/npm sur le PC** de l'utilisateur, paresseuse (uniquement pour un
  ELF distribué non-lié ; un blob pré-lié `0xDEC0BEBA` ne demande rien).

### Fondation pur-Python déjà committée
[formats/nwa_link.py](../../src/nwupdater/formats/nwa_link.py) (« foundation », pas le chemin livré) :
- ✅ Lecteur ELF32 (`Elf32.parse`) — sections, symtab, `.rel.*`.
- ✅ Moteur de relocations ARM (`apply_relocations`) : `R_ARM_ABS32`, `R_ARM_REL32`,
  `R_ARM_PREL31`, `R_ARM_THM_CALL`, `R_ARM_THM_JUMP24` + encode/decode Thumb-2 BL — bit-math
  validée en tests ([tests/test_nwa_link.py](../../tests/test_nwa_link.py)).
- ❌ Pas de placement de sections (linker script `lld`), pas de résolution finale des symboles,
  pas de runtime EADK.

---

## 2. La contrainte fondamentale

`nwlink` ne **relocalise** pas — il fait un **link statique complet**. Le `.nwa` distribué
(ELF `ET_REL`, compilé `-ffunction-sections`) contient `main` + l'app + newlib/compiler-rt, mais
**`_start` (crt0) et 10 externes sont UND** :

    eadk_event_get, eadk_display_draw_string, eadk_display_push_rect_uniform,
    _read, _write, _sbrk, _close, _fstat, _isatty, _lseek

Leur code est un **runtime précompilé embarqué dans nwlink** (`dist/index.js`, `Uint8Array` dérivé
d'EADK) — **non régénérable en Python**. Le dispatch EADK est un `svc #N` + indirection par
pointeur de table API (ex. `draw_string` lit un pointeur en `.rodata`), et **les numéros de `svc`
ne sont pas dans `eadk.h`**.

> **Conséquence :** « pur-Python + byte-exact + zéro binaire vendorisé » est **impossible**. Un
> linker pur-Python complet (stratégie C) doit *vendoriser* le runtime EADK (~220 B de `.text` +
> ses relocs + l'ABI `svc`) → **question de licence** ouverte (licence npm `nwlink` + licence
> EADK/Epsilon, à vérifier — non tranchée dans ce dépôt).

`lld` fait aussi : `.eh_frame` discardé (176→0 B), `.ARM.exidx` foldé (32→8 B), `.rodata` réduit
~130 B (`SHF_MERGE|STRINGS`), et un placement d'orphelins par son propre algo — autant à reproduire
byte-exact pour C.

---

## 3. L'atout décisif — modèle de reproduction (PROUVÉ)

Mesuré byte-exact : deux links du même app à base flash/ram décalée ne diffèrent que de
**~700 octets / ~406 mots de 32 bits**, chacun décalé exactement du delta de base. Donc :

> **`image(params) = IMAGE_FIXE + appliquer(~406 relocations absolues)`**

- Les relocs **PC-relatives** (1662 `THM_CALL`, 47 `THM_JUMP24`) sont **invariantes** au changement
  de base → absentes du diff.
- Seuls **~395 `ABS32`** (dans l'app) **+ ~11 refs runtime** dépendent de la cible.
- La taille du `.bin` est **indépendante des params**.

Ça borne le problème : la partie spécifique-appareil se réduit à **réappliquer ~406 mots absolus**,
chacun corrigé du delta de sa **région** (flash vs ram vs pointeur table API).

---

## 4. Stratégies comparées

| | Chemin | Node côté user | Réimpl. `lld` | Licence (vérifiée §0) | Effort | Risque |
|---|---|---|---|---|---|---|
| **A** | Garder la délégation (statu quo) | **Oui** | Non | ✅ **GO** | 0 | 0 |
| **B** | Link 1× en CI + reloc pur-Python | **Non** | Non | ⛔ **NO-GO**¹ | Moyen | Faible (tech) |
| **C** | Linker pur-Python complet (byte-exact) | **Non** | **Oui** | ⛔ **NO-GO**² | Élevé | Élevé |

¹ On croyait B « à empreinte légère » (redistribuer une image liée par app). La vérification §0
montre que **publier une image pré-liée = redistribuer le runtime EADK propriétaire** — une
redistribution qui n'a pas lieu aujourd'hui (l'écosystème diffuse l'ELF *pré-link*). NO-GO.
² C vendorise le runtime EADK propriétaire comme **table réutilisable** dans le dépôt MIT → NO-GO.

---

## 5. Stratégie retenue : A (B suspendu par la licence)

Après §0, **on reste sur A** (délégation `nwlink` via `npx`, déjà livrée et validée N0120) : c'est
la seule option qui ne redistribue aucun octet propriétaire NumWorks. Rien à implémenter.

**B était le meilleur choix *technique*** (objectif roadmap atteint, sans réimplémenter `lld`, en
réutilisant le moteur de relocs déjà committé), mais il est **suspendu** : publier une image
pré-liée redistribue le runtime EADK propriétaire (§0). B ne devient réalisable qu'avec une
**autorisation écrite de NumWorks**. La conception ci-dessous reste donc valable **le jour où B est
débloqué** ; elle n'est pas à construire tant que la licence n'est pas levée.

### Conception `.nwb` (à réaliser SEULEMENT si B est débloqué)

Exploiter le modèle §3. **En CI/catalogue**, lier chaque app **une fois** avec `nwlink`, puis
publier un artefact `(image_de_base, table_de_relocs, base_params)`. **À l'installation**, en
pur-Python : `image = image_de_base` avec chaque offset absolu corrigé du delta de sa région, pour
les params DFU-résolus de l'appareil.

#### Format d'artefact — `.nwb` (numworks binary, pré-relocalisable)
Conteneur pur-données (à figer en Phase 1) :
- `base_image` : le `.bin` lié par `nwlink` à `base_params` connus.
- `base_params` : `{flash_start, flash_length, ram_start, ram_length, trampoline_start}`.
- `reloc_table` : liste `(offset_dans_image, région)` où `région ∈ {flash, ram, api_table}` — les
  ~406 mots absolus, dérivés par **link différentiel** (2 links `nwlink` à bases décalées) ou en
  mappant les `ABS32` du `.rel.text` de l'ET_REL vers les offsets de sortie.
- `appinfo` : champs d'en-tête (magic, api_level, name, icon, app_size, entry).

À l'install : pour chaque `(offset, région)`, `mot += (cible_région − base_région)`. La validation
`validate_nwa` / `AppInfo.parse` existante consomme l'image relocalisée telle quelle.

---

## 6. Plan par phases (B) — GELÉ tant que la licence n'est pas levée

- **Phase 0 — Licence & décision** ✅ **FAIT (2026-07-27) → NO-GO** (voir §0). B et C exigent de
  redistribuer le runtime EADK propriétaire. **Les phases 1-4 ci-dessous sont GELÉES** ; elles ne
  démarrent qu'après une autorisation écrite de NumWorks. Prochaine action possible : solliciter
  NumWorks (grant explicite de redistribution du runtime EADK). À défaut, aucune action — A reste.
- **Phase 1 — Générateur CI (dev-PC)** : script qui, par app, lance `nwlink nwa-bin` à **2 bases**,
  dérive la `reloc_table` (offset + région), et émet le `.nwb`. Oracle de régression : **RPN v2.0.1**
  (`70 056 B` lié, **406 mots rebasés**, `395 ABS32 / 1662 THM_CALL / 47 THM_JUMP24 / 4 PREL31`).
- **Phase 2 — Relocateur pur-Python** : `formats/nwa_relocate.py` (réutilise `apply_relocations`).
  Test **byte-exact vs golden `nwlink`**, gate dev-PC — *skip* si `nwlink`/Node absent, comme les
  tests actuels ([test_apps_link.py](../../tests/test_apps_link.py), [test_nwa_link.py](../../tests/test_nwa_link.py)).
  **Aucun binaire committé** (règle du projet) : oracle en scratchpad seulement.
- **Phase 3 — Câblage** : `AppManager.push` consomme un `.nwb` **sans Node** ; `ensure_linked` garde
  la délégation `nwlink` en repli pour un ELF brut. Surface capacité `"nwlink"` conservée
  ([server/_session_apps.py](../../src/nwupdater/server/_session_apps.py)).
- **Phase 4 — Matériel** : smoke-test N0120 (installe + lance) ; read-back région == sortie `nwlink`.

### Repère si l'on bascule vers C plus tard
Fondation déjà faite : lecteur ELF32 + moteur de relocs. Reste (recette capturée) : placement
`.text`, `.rodata` `SHF_MERGE`, fold `.ARM.exidx` 32→8 B, LMA `.data`, en-tête AppInfo dynamique,
**récupération différentielle du runtime EADK** (les ~220 B + ~11 relocs), assemblage → diff 0,
câblage + tests. Phase 0 licence reste bloquante.

---

## Références
- Format & recette : [app-store-and-nwa.md](app-store-and-nwa.md) (§ ELF relocalisable, lignes ~73-104).
- Délégation livrée : [apps/link.py](../../src/nwupdater/apps/link.py), [apps/manage.py](../../src/nwupdater/apps/manage.py).
- Fondation pur-Python : [formats/nwa_link.py](../../src/nwupdater/formats/nwa_link.py).
- Trampoline / constantes : [dfu/constants.py](../../src/nwupdater/dfu/constants.py) (`USERLAND_HEADER_SIZE`, `USERLAND_ISR_SIZE`).
- Backlog : [roadmap.md](../00-overview/roadmap.md).

### Sources licence (§0, vérifiées 2026-07-27)
- `nwlink` npm — champ `license` = « All rights reserved » : `https://registry.npmjs.org/nwlink`
- Epsilon = CC BY-NC-SA + débat licence : `https://github.com/numworks/epsilon/issues/1875`
- Gabarit d'app BSD 3-Clause : `https://github.com/numworks/epsilon-sample-app-c` (fichier `LICENSE`)
