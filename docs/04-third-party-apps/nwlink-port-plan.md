# Lot 4 — Portage de `nwlink` : analyse & plan (se passer de Node)

Objectif backlog ([roadmap.md](../00-overview/roadmap.md)) : installer un `.nwa` **distribué**
(ELF relocalisable) **sans** dépendance Node/npm côté utilisateur. Ce document fige l'analyse,
compare les stratégies, et détaille le plan retenu.

**Décision : stratégie B** — lier une fois par app en CI avec `nwlink`, publier une image de base
+ une table de relocations, et relocaliser en **pur-Python** sur l'appareil. Voir §5.

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

| | Chemin | Node côté user | Réimpl. `lld` | Licence | Effort | Risque |
|---|---|---|---|---|---|---|
| **A** | Garder la délégation (statu quo) | **Oui** | Non | OK (npx) | 0 | 0 |
| **B** | **Link 1× en CI + reloc pur-Python** | **Non** | Non | légère¹ | Moyen | Faible |
| **C** | Linker pur-Python complet (byte-exact) | **Non** | **Oui** | lourde² | Élevé | Élevé |

¹ B ne vendorise pas un runtime *réutilisable* : il redistribue une **image liée par app** — ce
qu'un app-store fait déjà en flashant l'app sur l'appareil.
² C vendorise le runtime EADK comme **table réutilisable** pour lier des apps arbitraires → c'est
la vraie question de licence.

---

## 5. Stratégie retenue : B

Exploiter le modèle §3. **En CI/catalogue**, lier chaque app **une fois** avec `nwlink`, puis
publier un artefact `(image_de_base, table_de_relocs, base_params)`. **À l'installation**, en
pur-Python : `image = image_de_base` avec chaque offset absolu corrigé du delta de sa région, pour
les params DFU-résolus de l'appareil.

**Pourquoi B :** atteint l'objectif roadmap (plus de Node pour l'utilisateur), **sans réimplémenter
`lld`** ni vendoriser un runtime source, **en réutilisant le moteur de relocs déjà committé**.
Empreinte licence légère (redistribution d'une image liée par app = ce que fait déjà l'app-store).

Garder **A** comme repli automatique (un ELF brut sans artefact `.nwb` retombe sur la délégation).
Traiter **C** comme objectif « puriste » de long terme, **conditionné à la licence**.

### Format d'artefact proposé — `.nwb` (numworks binary, pré-relocalisable)
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

## 6. Plan par phases (B)

- **Phase 0 — Licence & décision** *(bloquant)* : vérifier licence `nwlink` (npm) + EADK/Epsilon ;
  confirmer que redistribuer une **image liée par app** est acceptable (elle l'est déjà pour le flash
  sur appareil). Sortie : go/no-go documenté.
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
