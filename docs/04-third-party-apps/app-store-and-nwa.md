# Lot 4 — Apps tierces : store, format `.nwa`, et ce que la calc « présente »

But du Lot 4 : **simuler une calculatrice connectée** pour récupérer des applications tierces
depuis le site officiel, et comprendre le format pour les installer (Lot 3).

## Le store d'apps NumWorks

- Store + uploader : `https://my.numworks.com/apps` — **auth** (302 → sign_in) [CONFIRMÉ].
- `GET https://my.numworks.com/apps.json` → **401** (JSON auth-gated) [CONFIRMÉ].
- D'après `epsilon/external_apps/README.md` [CONFIRMÉ, fichier local] : *« Anyone can install
  an `app.nwa` on their calculator from the NumWorks online uploader (my.numworks.com/apps).
  »* Le flux officiel = **l'utilisateur fournit un `.nwa`**, flashé en WebUSB dans la région
  « external apps ». **Il n'y a pas de "catalogue d'apps" JSON public** : le modèle officiel
  est *upload d'un fichier*, pas un store curé côté serveur.
- Les **catalogues communautaires** (Nwagyu, dépôts GitHub) hébergent des `.nwa`
  indépendamment. → notre updater pourra agréger ces sources en plus du compte NumWorks.

> Implication : « récupérer des apps tierces » = (a) via le compte NumWorks authentifié
> (`/apps`), et/ou (b) via des dépôts communautaires de `.nwa`. La compatibilité se décide
> **côté client** (comme le fait le site), donc notre calc virtuelle doit exposer les bons
> champs (ci-dessous).

## Ce qu'une calculatrice connectée « présente » pour la compat

La compatibilité est décidée **côté client** en comparant le header de l'app au header
userland de la calc (tous deux lus en WebUSB/DFU). La calc expose :

- **Modèle** — dérivé des tailles de segments flash annoncés par le DFU (voir
  [../01-specs/usb-dfu-protocol.md §6.4](../01-specs/usb-dfu-protocol.md) et §4.2 de
  numworks.js) : `"0100"`, `"0110"`, etc.
- **Version OS** — chaîne 8 octets du KernelHeader.
- **Région flash "external apps"** — `m_externalAppsFlashStart` / `…End` du UserlandHeader →
  donne l'**espace disponible**.
- **API level** — chaque `.nwa` embarque son `EXTERNAL_APPS_API_LEVEL` requis ; l'OS ne
  lance l'app que si `app.APILevel() == device API level`.

### Modèle vu par `numworks.js` (getModel) — inféré des segments DFU [CONFIRMÉ]

Aucun champ « modèle » ; il est **calculé** depuis les segments mémoire du descripteur DFU :

| interne | externe | modèle |
|---|---|---|
| `0x10000` (64K) | `0x800000` (8M) | **`0110`** |
| `0x10000` | `0x1000000` (16M) | `0110-16M` |
| `0x100000` (1M) | 0 | **`0100`** |
| autre | autre | `????` |

→ Notre device virtuel doit **annoncer des segments DFU cohérents** avec le modèle prétendu
(ex. n0110 = 64K interne @`0x08000000` + 8M externe @`0x90000000`).

## Format binaire `.nwa` (EADK / AppInfo) [CONFIRMÉ via source]

`shared/ion/include/ion/external_apps.h` + `.../drivers/external_apps.cpp` :

- Magic : **`0xDEC0BEBA`** (constante `k_magic` ; le commentaire l'appelle `0xBABECODE`).
- Chaque app commence par un header `AppInfo` de **huit mots de 32 bits** :

| Offset | Champ | Note |
|---|---|---|
| 0x00 | Magic start | `0xDEC0BEBA` |
| 0x04 | API level | doit == `EXTERNAL_APPS_API_LEVEL` du device |
| 0x08 | Name address | pointeur nom |
| 0x0C | Icon size | taille icône compressée |
| 0x10 | Icon address | pointeur icône compressée |
| 0x14 | Entry point | |
| 0x18 | App size | total header inclus |
| 0x1C | Magic end | `0xDEC0BEBA` |

Les apps sont buildées avec **`nwlink`** en `*.nwa`. Un reset efface les apps externes ;
depuis OS 24.3.0 elles sont seulement **cachées** en mode examen ; depuis 25.0.0 elles
survivent à la plupart des crashes.

> ⚠️ **Un `.nwa` *distribué* ne porte PAS ce header `AppInfo`.** Le fichier téléchargé (ex.
> l'asset GitHub d'une release) est un **ELF ARM relocatable** (`e_type = ET_REL`, magic
> `7f 45 4c 46`), pas un blob commençant par `0xDEC0BEBA`. Le header `AppInfo` et les adresses
> absolues (name/icon/entry point) **n'apparaissent qu'après le lien d'installation** : c'est
> `nwlink nwa-bin --flash-start <addr>` qui place les sections à `externalAppsFlashStart +
> offset` du slot actif, résout les symboles et applique les relocations (`R_ARM_THM_CALL`,
> `R_ARM_ABS32`, `R_ARM_THM_JUMP24`, …). Le lien est donc **spécifique à l'adresse de flash**
> et dépend aussi de la **fenêtre RAM externe** (`m_externalAppsRAMStart/End` du UserlandHeader),
> où vivent les `.bss`/`.data` de l'app. Conséquence : on ne peut PAS flasher l'asset tel quel
> — `AppInfo.parse()` le rejette (magic ELF ≠ `0xDEC0BEBA`). Un blob synthétique déjà lié
> (`nwa.build_nwa`, pour les tests) court-circuite cette étape et ne reflète donc pas une app
> réellement distribuée.
>
> **Ce que fait l'updater** ([`nwupdater.apps.link`](../../src/nwupdater/apps/link.py)) : à
> l'installation, si le `.nwa` est un ELF relocatable, on **délègue le lien à `nwlink nwa-bin`**
> exécuté **hors-ligne**, en lui passant les paramètres cible résolus en DFU (fenêtre flash
> external-apps + fenêtre RAM du UserlandHeader), puis on flashe le `.bin` obtenu avec notre
> propre moteur DFU. Raison : le lien exige le runtime EADK compilé de NumWorks (`_start` + les
> stubs `eadk_*`/newlib), qui n'existe qu'à l'intérieur de `nwlink` — on ne peut pas le
> régénérer en Python. Un `.nwa` déjà lié (magic `0xDEC0BEBA`) est flashé tel quel, sans nwlink.

## `nwlink` — CLI officielle app/link [CONFIRMÉ npm]

- Paquet npm **`nwlink`** (v0.0.19) : *« Command-line interface to your NumWorks calculator. »*
- Dépend de **`usb`** (libusb natif, **pas WebUSB**), `commander`, `cli-progress` → parle au
  device en **DFU natif depuis Node**, sans endpoint HTTP.
- Utilisé dans le build external-apps d'Epsilon (`make PLATFORM=device run`).

> **Pour notre updater (Python)** : `nwlink` prouve que le flux app tierce est faisable en
> USB natif headless. On réimplémente la partie flash `.nwa` → région external-apps via
> notre moteur DFU (Lot 3), et on lit `AppInfo`/API level pour valider la compat avant
> transfert.

## Conséquences pour le Lot 4

1. **Simuler la calc pour le site** : sans USB réel (contrainte), on ne pilote pas
   `navigator.usb` ; on cible directement le **modèle objet de `numworks.js`** (mock de
   `getModel`/`getPlatformInfo`/espace apps). Voir
   [../01-specs/emulators-and-usb-analysis.md](../01-specs/emulators-and-usb-analysis.md).
2. **Sources d'apps** : compte NumWorks (`/apps`, authentifié) + dépôts communautaires
   `.nwa`. À agréger dans un endpoint local `GET /api/apps?model=…&api_level=…`.
3. **Validation compat** avant transfert : `AppInfo.magic == 0xDEC0BEBA`,
   `AppInfo.APILevel == device API level`, et `AppInfo.appSize <= espace external-apps`.
