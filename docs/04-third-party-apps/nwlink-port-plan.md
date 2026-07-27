# Lot 4 — Portage de `nwlink` : analyse & plan (se passer de Node)

Objectif backlog ([roadmap.md](../00-overview/roadmap.md)) : installer un `.nwa` **distribué**
(ELF relocalisable) **sans** dépendance Node/npm — ni côté projet, ni côté utilisateur.

**Décision (2026-07-27) : cible = C′ — linker pur-Python + runtime EADK *clean-room*.** On écrit
nous-mêmes le mini-runtime (crt0 + stubs), en s'appuyant sur l'**ABI `svc`** (des *faits*, pas du
code protégé). Zéro Node, et **aucun octet NumWorks redistribué**. Le chemin **A** (délégation
`npx nwlink`, déjà livré) **reste le repli** jusqu'à ce que C′ soit prêt et validé sur matériel.

> **Posture de bonne foi (voir aussi [GOOD-FAITH-DECLARATION.md](../../GOOD-FAITH-DECLARATION.md)) :**
> on procède au clean-room de bonne foi, et **on retirera la fonctionnalité immédiatement si NumWorks
> le demande**. L'équipe technique de NumWorks (dont la CTO) a accepté l'invitation GitHub sur ce
> dépôt → elle a une **visibilité directe** et un canal direct pour objecter. Ce n'est pas un accord
> de licence formel ; c'est une posture ouverte et réversible.

---

## 0. Vérification de licence — go/no-go (2026-07-27)

Faits établis (sources en fin de doc) :
- **`nwlink` (paquet npm) = « All rights reserved »** — propriétaire NumWorks. Seuls les WASM
  embarqués `ld.wasm`/`objcopy.wasm` sont GPLv2 ; **le runtime EADK embarqué ne l'est pas**.
- **Epsilon OS = CC BY-NC-SA** historiquement (Attribution + **NonCommercial** + **ShareAlike**) ;
  l'issue upstream #1875 note que la mention CC a « disparu » → au mieux NC/SA, au pire propriétaire.
- **`epsilon-sample-app-c` = BSD 3-Clause** — mais c'est le **gabarit d'app** que le publisher
  écrit, **pas** le runtime.

Ce que la licence interdit vs autorise :
- ⛔ **Redistribuer *leur* runtime** — le blob EADK de nwlink (propriétaire) ou des octets dérivés
  d'Epsilon (CC BY-NC-SA, incompatible MIT). → tue **B** et le **C « vendorisé »** (voir §4).
- ✅ **Écrire *notre* runtime** — les **numéros de `svc`** et le contrat mémoire EADK sont une
  **interface / des faits**, non protégeables par le droit d'auteur (posture clean-room classique).
  Un crt0 + des stubs réécrits par nous sont **notre code (MIT)**. → débloque **C′** (voir §5).

Le point de bascule : la licence ne bloque que la case « redistribuer **leur** code ». Elle ne dit
rien si le runtime est **le nôtre**.

### Le trilemme (on ne peut avoir que 2 des 3 — C′ prend les 2 bonnes)
| | Sans Node | Sans redistribuer le runtime NumWorks | Sans dépendre de NumWorks au runtime |
|---|:---:|:---:|:---:|
| **A** délégation `npx` | ❌ | ✅ | ✅ |
| **B / C vendorisé** | ✅ | ⛔ | ✅ |
| **C′** clean-room | ✅ | ✅ | ✅¹ |

¹ C′ ne dépend de NumWorks ni au build ni au runtime : le runtime est le nôtre. Reste seulement à
**récupérer l'ABI `svc`** une fois (des faits), empiriquement.

---

## 1. État actuel

### Chemin livré (repli, validé N0120) — délégation `nwlink nwa-bin` offline
- [apps/link.py](../../src/nwupdater/apps/link.py) : `_resolve_nwlink()` (`NWUPDATER_NWLINK` →
  `npx --yes nwlink@0.0.19` → `nwlink` sur PATH), `link_nwa()` construit `nwa-bin --flash-start …
  --ram-start … --trampoline-start … in.nwa out.bin`. Câblé dans `AppManager._link_if_needed()`
  ([apps/manage.py](../../src/nwupdater/apps/manage.py)) avec garde `trampoline_word_looks_valid`.
- Coût : **Node/npm sur le PC** de l'utilisateur (paresseux). C'est précisément ce que C′ supprime.

### Fondation pur-Python déjà committée — réutilisable telle quelle par C′
[formats/nwa_link.py](../../src/nwupdater/formats/nwa_link.py) (`f1e632a`) :
- ✅ Lecteur ELF32 (`Elf32.parse`) — sections, symtab, `.rel.*`.
- ✅ Moteur de relocations ARM (`apply_relocations`) : `ABS32`, `REL32`, `PREL31`, `THM_CALL`,
  `THM_JUMP24` + encode/decode Thumb-2 BL — bit-math validée ([tests/test_nwa_link.py](../../tests/test_nwa_link.py)).
- ❌ Manque (à construire pour C′) : placement de sections, en-tête AppInfo, et **le runtime**.

---

## 2. Contrainte technique

`nwlink` fait un **link statique complet** (pas une simple relocation). Le `.nwa` distribué
(ELF `ET_REL`, `-ffunction-sections`) contient `main` + l'app + newlib/compiler-rt, mais **`_start`
(crt0) et 10 externes sont UND** et fournis par le runtime :

    eadk_event_get, eadk_display_draw_string, eadk_display_push_rect_uniform,   ← dispatch EADK
    _read, _write, _sbrk, _close, _fstat, _isatty, _lseek                       ← stubs newlib

Ce runtime est **minuscule et trivial** — donc réécrivable clean-room :
- **`_start` (crt0)**, ~60-70 B : copie `.data` (flash→RAM), zéro `.bss`, place le heap, appelle
  `main`. Symboles définis par le script de link dont il a besoin : `_data_section_start_flash/_ram`,
  `_bss_section_start/end_ram`, `_heap_start/_heap_end`, `main`.
- **3 stubs `eadk_*`** : dispatch `svc #N` (`push_rect_uniform` = `svc 0x14`, `event_get` = `svc 0x17`)
  + une **indirection par pointeur de table API** pour `draw_string` (charge un mot en `.rodata`).
- **7 stubs newlib** : shims triviaux (retour -1 / `errno` ; `_sbrk` bumpe le heap).

Seul os dur : **l'ABI `svc` n'est pas dans `eadk.h`** → il faut récupérer les rares numéros
manquants + le mécanisme de la table API **empiriquement** (des faits). C'est borné.

---

## 3. Atout : modèle de reproduction (utile pour valider C′)

Mesuré byte-exact : deux links à base flash/ram décalée ne diffèrent que de ~700 octets / ~406 mots,
chacun décalé du delta de base → **`image(params) = IMAGE_FIXE + appliquer(~406 relocs absolues)`**.
Les relocs PC-relatives (1662 `THM_CALL`, 47 `THM_JUMP24`) sont invariantes.

Pour C′ (qui n'a plus l'objectif byte-exact) ce modèle sert de **cross-check** : la **région app**
de notre sortie doit coïncider avec celle de `nwlink` (mêmes octets d'app, à la base près) ; toute
divergence se **localise dans le runtime que nous écrivons** — validation ciblée sans exiger l'égalité
byte-à-byte globale.

---

## 4. Stratégies comparées

| | Chemin | Node user | Réimpl. `lld` | Licence (§0) | Effort | Risque |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **A** | Délégation `npx nwlink` (repli) | **Oui** | Non | ✅ GO | 0 | 0 |
| **B** | Link 1× en CI + reloc pur-Python | Non | Non | ⛔ NO-GO¹ | Moyen | Faible |
| **C** | Linker pur-Python, runtime **vendorisé** | Non | Oui² | ⛔ NO-GO¹ | Élevé | Élevé |
| **C′** | Linker pur-Python, runtime **clean-room** | **Non** | **Non**³ | ✅ **GO** | Moyen-élevé | Moyen |

¹ Redistribue le runtime EADK propriétaire (image pré-liée ou table vendorisée). ² Le C byte-exact
imposait de reproduire le placement d'orphelins + `SHF_MERGE` de lld. ³ **C′ abandonne le byte-exact**
→ un placement *valide* suffit (l'oracle devient l'appareil), donc **pas de réimplémentation de lld**.

---

## 5. Stratégie retenue : C′ (clean-room), A en repli

**Notre linker pur-Python** (lecteur ELF + moteur de relocs déjà committés + placement à écrire)
lie deux entrées : (1) le `.nwa` `ET_REL` du publisher, (2) **notre runtime clean-room**. Sortie =
un `.bin` AppInfo `0xDEC0BEBA` valide pour les params DFU-résolus de l'appareil. **Aucun Node,
aucun octet NumWorks.**

- **Barre d'acceptation** : non plus « byte-exact vs nwlink » mais **« l'app tourne correctement
  sur N0120/N02xx »**, avec le cross-check §3 pour localiser les écarts.
- **Repli automatique A** : si C′ ne sait pas encore traiter une app (reloc/type non gérés), on
  retombe sur `ensure_linked` → `npx nwlink` (le code A reste, inchangé).
- **Réversibilité** : la fonctionnalité est isolée derrière `AppManager.push` et peut être retirée
  d'un bloc si NumWorks le demande (posture de bonne foi, bandeau en tête).

---

## 6. Plan par phases (C′)

- **Phase 1 — Récupérer l'ABI (faits)** : les numéros `svc` manquants + le mécanisme de la table API
  (`draw_string`), par observation empirique (Epsilon/appareil/oracle). *Livrable : une table de
  faits documentée, aucune copie de code.*
- **Phase 2 — Runtime clean-room** : écrire `_start` (crt0) + 3 stubs `eadk_*` + 7 stubs newlib en
  Thumb-2 (hand-assemblé, ~200 B), sous forme d'un objet/ELF que **nous** produisons, avec les
  symboles définis attendus (§2). MIT, dans le dépôt.
- **Phase 3 — Placement + assemblage pur-Python** : au-dessus du lecteur+reloc committés, placer les
  sections (valide, pas byte-exact), résoudre les symboles, écrire l'en-tête AppInfo (magic,
  api_level, name, icon, `app_size = _eadk_app_end`, `entry = _start`), appliquer les relocs pour les
  params cible. Trampoline = `userland_header_addr + 0x38` (déjà dans [apps/link.py](../../src/nwupdater/apps/link.py)).
- **Phase 4 — Câblage** : `AppManager.push` utilise C′ **sans Node** ; A en repli ; surface capacité
  `"nwlink"` conservée ([server/_session_apps.py](../../src/nwupdater/server/_session_apps.py)).
- **Phase 5 — Validation matériel** : N0120 (installe + lance), read-back ; cross-check région app vs
  `nwlink` (§3). Régression sur l'app RPN (v2.0.1, `70 056 B` lié, 406 mots rebasés).
- **Tests** : unit/structurel **pur-Python en CI** (ELF, relocs, placement, en-tête) ; smoke matériel
  et diff vs `nwlink` **gate dev-PC**, *skip* si nwlink/Node absents (comme
  [test_apps_link.py](../../tests/test_apps_link.py) / [test_nwa_link.py](../../tests/test_nwa_link.py)).
  **Aucun binaire committé** ; oracles en scratchpad uniquement.

---

## Références
- Format & recette : [app-store-and-nwa.md](app-store-and-nwa.md).
- Délégation (repli A) : [apps/link.py](../../src/nwupdater/apps/link.py), [apps/manage.py](../../src/nwupdater/apps/manage.py).
- Fondation pur-Python : [formats/nwa_link.py](../../src/nwupdater/formats/nwa_link.py).
- Trampoline / constantes : [dfu/constants.py](../../src/nwupdater/dfu/constants.py).
- Backlog : [roadmap.md](../00-overview/roadmap.md) · Bonne foi : [GOOD-FAITH-DECLARATION.md](../../GOOD-FAITH-DECLARATION.md).

### Sources licence (§0, vérifiées 2026-07-27)
- `nwlink` npm — `license` = « All rights reserved » : `https://registry.npmjs.org/nwlink`
- Epsilon = CC BY-NC-SA + débat licence : `https://github.com/numworks/epsilon/issues/1875`
- Gabarit d'app BSD 3-Clause : `https://github.com/numworks/epsilon-sample-app-c` (fichier `LICENSE`)
