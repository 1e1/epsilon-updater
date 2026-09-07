# Canal figé — binaires pour anciens systèmes

> **Statut : livré** (job `build-legacy` de
> [`build-apps.yml`](../../.github/workflows/build-apps.yml)). Trois zips `…-legacy-…`, x86_64
> uniquement, publiés à côté des canaux actifs.

## 1. Pourquoi un canal figé

La règle du projet est de **rester sur les dernières versions d'outillage**. Chaque montée
déplace un plancher système vers le haut, et ces planchers ne sont pas dans les tags de roues :
ils sont **dans les binaires livrés**. Résultat, un poste ancien tombe du camion sans que rien,
dans le code, ne l'ait décidé.

Le canal figé fait l'inverse : **outillage épinglé, planchers bas, même code applicatif**. Deux
promesses tenues séparément au lieu d'une seule tenue à moitié :

| Canal | Promesse |
|---|---|
| **actif** (natif + web) | dernières versions d'outillage, plateformes récentes |
| **figé** (web seul) | mêmes fonctionnalités, vieux postes |

Point important : **le canal figé n'est pas une vieille version de l'app.** C'est le code
courant, compilé pour de vieux systèmes. Un Mac en 10.12.6 reçoit donc le catalogue firmware à
jour, les correctifs et les nouveautés — c'est l'**outillage de compilation** qui est gelé, pas
le produit.

## 2. Planchers mesurés

Chiffres lus dans les binaires par
[`nwupdater.tools.binary_floor`](../../src/nwupdater/tools/binary_floor.py), pas dans les tags de
roues (qui mentent : voir §6 de [`native-ui-feasibility.md`](native-ui-feasibility.md)).

| Cible | Canal actif (mesuré) | Canal figé | Ce qui fixait le plancher |
|---|---|---|---|
| **macOS** x86_64 | 10.13 | **10.12** (Sierra) | le bootloader PyInstaller publié (`LC_VERSION_MIN_MACOSX 10.13`) — le CPython embarqué, lui, est à **10.9** |
| **Linux** x86_64 | `GLIBC_2.34` (Ubuntu 22.04+) | **`GLIBC_2.17`** (CentOS 7, Ubuntu 14.04+) | le CPython de `setup-python`, compilé sur l'Ubuntu du runner |
| **Windows** x64 | 8.1 | **8.1, gelé** | la politique CPython (3.13 exige Windows 10) |

Trois précisions qui évitent de se tromper de cible :

- **Aucun Mac n'est bloqué en 10.12 par le matériel** : la liste de compatibilité de High Sierra
  (10.13) est identique à celle de Sierra. Les postes en 10.12.6 sont **gelés par politique de
  flotte** — exactement le parc scolaire visé, donc le canal figé les sert quand même.
- **Le gain Linux est immédiat et large** : `GLIBC_2.34` exclut aujourd'hui Ubuntu 20.04, encore
  courant en salle. `2.17` remonte jusqu'à CentOS 7.
- **Le gain Windows est différé** : il n'apparaît qu'au moment où le canal actif passera à
  Python ≥ 3.13, qui exige Windows 10. Le figé, lui, restera à 8.1.

L'**IHM native n'a pas de canal figé** : aucun Qt 6 ne descend sous macOS 11 (PySide6 6.5.2, la
dernière roue *taguée* `macosx_10_9`, a en réalité `minos 11.0` dans `QtCore`), et la route Qt 5
est un ensemble vide (PySide2 en `macosx_10_12_intel` plafonne à **Python 3.7**). Le canal figé
est donc, par construction, le canal **web**.

## 3. Les épingles, et pourquoi celles-là

| Épingle | Valeur | Raison |
|---|---|---|
| Python (macOS, Windows) | **3.11.9** | dernière lignée CPython qui supporte Windows 8.1 ; l'installeur macOS `universal2` est bâti à 10.9 (mesuré sur la tranche x86_64) ; `.9` est son dernier correctif avec installeurs officiels |
| Python (Linux) | **`python-build-standalone` cpython-3.11.15+20260805** | compilé pour glibc 2.17, **OpenSSL lié statiquement** → TLS sans dépendre d'un `libssl` système disparu |
| PyInstaller | **6.22.2** | bootloader Linux à `GLIBC_2.14`, Windows à PE 6.0 ; sur macOS il est recompilé (§4) |
| Extras | **`usb`, `auth`** | `auth` = `certifi` : un macOS de 2016 ou un CentOS 7 ne reçoit plus de racines de confiance à jour, l'app figée porte donc les siennes |

**Politique de gel.** Ces épingles **ne suivent pas** le canal actif — c'est tout l'intérêt du
job. On n'y touche que pour un correctif de sécurité **dans la même lignée**, et seulement si le
contrôle de plancher (§5) reste vert. Une montée qui remonte un plancher **fait échouer le job**
au lieu de livrer une promesse que le binaire ne tient pas.

## 4. macOS : la seule recompilation nécessaire

Le bootloader publié par PyInstaller est bâti à **10.13**, et c'est lui — pas CPython (10.9) —
qui interdit 10.12 : c'est le **premier** exécutable que macOS charge. `waf` honore
`MACOSX_DEPLOYMENT_TARGET`, donc le correctif tient en une commande :

```bash
MACOSX_DEPLOYMENT_TARGET=10.12 CFLAGS="-arch x86_64" LINKFLAGS="-arch x86_64" \
PYINSTALLER_COMPILE_BOOTLOADER=1 PYINSTALLER_BOOTLOADER_WAF_ARGS=--no-universal2 \
pip install --no-binary=pyinstaller "pyinstaller==6.22.2"
```

- `--no-universal2` + `-arch x86_64` : une tranche **arm64 ne peut pas viser 10.12** (son
  minimum est 11.0), donc le bootloader reste mono-tranche.
- Vérifié avec **Xcode 21 sur macOS 26** : la cible 10.12 est acceptée, sans avertissement, et
  le binaire sort en `LC_VERSION_MIN_MACOSX 10.12`.
- Le plist suit, via `NWUPDATER_MAC_MIN=10.12`
  ([`nwupdater.spec`](../../packaging/nwupdater.spec)) : le Finder refuse une app d'après
  `LSMinimumSystemVersion`, donc laisser 10.13 là enfermerait l'utilisateur dehors alors que les
  binaires, eux, acceptent 10.12.

Le reste du parc macOS ne demande rien : CPython (10.9) et `libusb` (10.9) sont déjà assez bas.
Comme ce canal ne livre que x86_64, `libusb` est **remplacé** par sa build x86_64 plutôt que
fusionné en `universal2` — une tranche arm64 résiduelle ne ferait qu'échouer au contrôle.

## 5. Le contrôle de plancher

C'est ce qui rend la promesse vérifiable plutôt qu'affichée.
[`nwupdater.tools.binary_floor`](../../src/nwupdater/tools/binary_floor.py) lit les octets — pas
`vtool`, `objdump` ni `dumpbin`, pour que le même contrôle tourne sur les trois runners :

| Format | Ce qu'il lit | Plancher |
|---|---|---|
| Mach-O | `LC_VERSION_MIN_MACOSX`, `LC_BUILD_VERSION` (plateforme macOS), chaque tranche d'un binaire universel | version macOS minimale |
| ELF | les symboles `GLIBC_x.y` importés (`.dynstr`) | glibc minimale |
| PE | l'en-tête optionnel (`MajorOperatingSystemVersion`, `MajorSubsystemVersion`) | version Windows minimale |

```bash
python -m nwupdater.tools.binary_floor --macos 10.12 "dist/NumWorks Updater.app"
python -m nwupdater.tools.binary_floor --glibc 2.17 dist-legacy
python -m nwupdater.tools.binary_floor --windows 6.3 dist-legacy
```

Il sort en erreur si un binaire dépasse la cible **ou si aucun binaire n'a été inspecté** (un
`dist/` vide ou mal pointé passerait sinon en silence, ce qui viderait le contrôle de son sens).
Utilisable tel quel sur un zip téléchargé et décompressé.

**Nuance onefile** : sous Windows et Linux, l'interpréteur est compressé *dans* l'exécutable et
reste donc invisible au contrôle. Le job mesure alors aussi l'arbre de l'interpréteur — un
**surensemble** de ce qui a été empaqueté, ce qui rend la barrière plus stricte, jamais plus
laxiste. Sous macOS, l'app est un bundle *onedir* : mesuré tel quel.

`--exclude site-packages` écarte les dépendances **de compilation seulement** — `pillow`, qui
génère les icônes, exige `GLIBC_2.27` et ne part jamais dans l'app ; la mesurer ferait échouer la
barrière sur un fichier que personne n'installe. `libusb` est réintroduit en le nommant comme
racine à part : c'est la seule dépendance compilée qui, elle, est bien livrée (`pyusb` est du
Python pur). Le motif d'exclusion s'applique au chemin **relatif à chaque racine**, ce qui permet
exactement ça.

## 6. Ce que ce canal ne fait pas

- **Il ne fige pas les fonctionnalités** — même source que le canal actif (§1).
- **Il ne descend pas plus bas.** Windows 7 exigerait Python 3.8, or le cœur demande **3.9**
  (mesuré : `importlib.resources.files`, `argparse.BooleanOptionalAction`,
  `hashlib.sha1(usedforsecurity=)`) — et 3.9 exige déjà Windows 8.1. Ce serait donc une
  réécriture de ces trois usages **plus** un Python en fin de vie depuis 2024 : non retenu.
- **Il ne livre pas l'IHM native** (§2).
- **Il n'est pas signé**, comme les deux autres canaux — même contournement au premier
  lancement, voir [`desktop-app.md`](desktop-app.md).
- **Pas d'arm64, pas de 32 bits** : le parc ancien visé est x86_64.
