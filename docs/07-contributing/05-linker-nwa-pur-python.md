# 5 — Le linker `.nwa` pur-Python (sans Node)

Installer une app **distribuée** (`.nwa` = ELF relocalisable `ET_REL`) exige de la *lier* aux
adresses flash/RAM de l'appareil. Historiquement on déléguait ce lien à `nwlink` (paquet Node).
Le linker **pur-Python** (`formats/nwa_linker.py`) fait ce lien **sans Node**, en liant l'app
contre notre **runtime EADK clean-room** — voir l'analyse complète dans
[`../04-third-party-apps/nwlink-port-plan.md`](../04-third-party-apps/nwlink-port-plan.md).

> **Licence / bonne foi.** L'ABI EADK (numéros `svc`, dispatch) sont des *faits* ; le runtime est
> **notre code** (MIT). On ne redistribue **aucun octet NumWorks**. Feature retirable d'un bloc si
> NumWorks le demande. Ne **jamais** committer d'octet extrait de `nwlink` ni de `.nwa` réel.

## Le flux en un schéma

```
app.nwa (ET_REL)  ─┐
                   ├─► PureLinker.link() ──► .bin AppInfo 0xDEC0BEBA ──► flash (DFU)
runtime clean-room ┘        │
(_eadk_runtime.py)          ├─ GC des sections (racines: _start + name/icon/api)
                            ├─ placement: header│name│icon│.text│.rodata│.data(LMA)│.bss(RAM)
                            ├─ résolution des symboles cross-objets (app ⇄ runtime)
                            └─ relocations ARM REL (moteur de nwa_link.py)
```

- `AppManager.push` essaie C′ d'abord, **repli** sur `nwlink` si le lien échoue.
  `NWUPDATER_LINKER=pure|nwlink` force l'un ou l'autre.
- **Acceptation = l'app tourne sur l'appareil** (pas de byte-exact avec nwlink). Cross-check offline
  possible sur l'en-tête AppInfo.

## Les fichiers

| Fichier | Rôle |
|---------|------|
| `formats/nwa_link.py` | lecteur ELF32 + moteur de relocations ARM `REL` (ABS32, REL32, THM_CALL/JUMP24, PREL31, **MOVW/MOVT**, TARGET1). |
| `formats/eadk_runtime.s` | **notre** runtime Thumb-2 (crt0 + stubs `eadk_*` + stubs newlib). MIT. |
| `formats/_eadk_runtime.py` | le runtime compilé, embarqué en base64 (**généré**, ne pas éditer). |
| `formats/nwa_linker.py` | le linker (`PureLinker`, `link_nwa_pure`). |
| `scripts/build_eadk_runtime.py` | **tooling** : recompile `.s` → régénère `_eadk_runtime.py`. |

## Tooling — régénérer le runtime

Après toute modif de `eadk_runtime.s` :

```bash
python scripts/build_eadk_runtime.py     # nécessite un clang cross (arm-none-eabi) — DEV seulement
python -m pytest tests/test_nwa_linker.py -q
```

Le shipping n'a besoin **ni de clang ni de Node** : `_eadk_runtime.py` contient déjà les octets.

## Ajouter une fonction `eadk_*` (nouveau `svc`)

1. **Récupérer le numéro de `svc` (un fait)** via un *probe* clean-room — jamais en copiant nwlink :
   ```bash
   # une app à nous qui appelle la fonction, liée par nwlink OFFLINE, puis désassemblée
   clang --target=arm-none-eabi -mthumb -mcpu=cortex-m7 -mfloat-abi=hard -mfpu=fpv5-sp-d16 \
         -DPLATFORM_DEVICE=1 -fshort-enums -c probe.c -o probe.nwa -I<dist/eadk>
   npx nwlink@0.0.19 nwa-elf probe.nwa probe.elf     # offline, aucun appareil requis
   # désassembler le stub (capstone, mode Thumb) → lire `svc #N`
   ```
2. Ajouter le stub dans `eadk_runtime.s` avec la macro adaptée (`SVC_VOID` / `SVC_RET` / `SVC_U64`
   / `RECT_SVC`). `draw_string` est le cas spécial (dispatch par la table du trampoline OS).
3. `python scripts/build_eadk_runtime.py` puis tests.

## Valider (dev-PC, avec `nwlink`) et sur matériel

```bash
# cross-check offline de l'en-tête AppInfo vs l'oracle nwlink (skip si npx/nwlink absent) :
NWUPDATER_TEST_NWA=/chemin/app.nwa python -m pytest \
    tests/test_nwa_linker.py::test_appinfo_matches_nwlink_oracle -q

# sur appareil (le seul vrai juge) : forcer C′ et flasher, puis lancer l'app :
NWUPDATER_LINKER=pure python -m nwupdater apps ...    # ou via AppManager.push
```

## Limite connue

- **Constructeurs C++ globaux (`.init_array`)** ne sont **pas** exécutés par notre crt0 (les jeux C
  n'en ont pas ; RPN et Tetris tournent). Une app qui en dépend doit passer par le repli
  (`NWUPDATER_LINKER=nwlink`). À implémenter dans le crt0 si le besoin apparaît.
- Fonctions EADK non fournies par le runtime (ex. `eadk_battery_*`, `eadk_usb_is_plugged`) : si
  l'app les appelle sur un chemin **vivant**, le lien échoue → repli `nwlink`. Le GC élimine les
  références en code mort (cas courant).

## Tests

- `tests/test_nwa_link.py` — bit-math des relocations (branches, MOVW/MOVT), lecteur ELF.
- `tests/test_nwa_linker.py` — link d'une app **synthétique** (aucun binaire committé), GC des
  stubs inutilisés, garde de dépassement, + cross-check `nwlink` **gate dev-PC**.
