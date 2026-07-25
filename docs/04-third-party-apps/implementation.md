# Lot 4 — Implémentation apps tierces

Voir [app-store-and-nwa.md](app-store-and-nwa.md) pour le format et le store officiel. Ici,
le code. Réutilise le moteur DFU du Lot 3.

## Modules

- `src/nwupdater/formats/nwa.py` — header `AppInfo` d'un `.nwa` :
  - `AppInfo.parse(blob)` — magic `0xDEC0BEBA`, api_level, nom, taille ; `valid`.
  - `build_nwa(name, api_level, code, icon)` — construit un `.nwa` minimal valide (tests/démo).
- `src/nwupdater/apps/store.py` — `AppEntry`, `AppStore` :
  - `bundled()` — catalogue **communautaire illustratif** embarqué
    (`apps/data/community-apps.json`). ⚠️ Il n'existe **pas d'API JSON publique officielle**
    (le flux officiel = upload manuel d'un `.nwa` sur `my.numworks.com/apps`) ; ce store
    modélise l'agrégation de catalogues communautaires.
  - `compatible(family, device_api_level, has_external_apps)` — filtrage **côté client**
    (comme le site) : famille + API level + présence d'une zone apps externes.
- `src/nwupdater/apps/sources.py` — **source utilisateur générique** (rien de codé en dur) :
  - `user_apps_dir()` — `NWUPDATER_APPS_DIR`, sinon `<config>/nwupdater/apps`.
  - `app_entries(dir)` — agrège les `.nwa` **locaux** (nom + API level lus dans le header ;
    installés **tels quels** via `local_path`) et les URLs d'un `_urls.txt` (une par ligne ;
    téléchargées via le proxy SSRF-gardé, qui les autorise car désormais dans le store). Le
    serveur fusionne ces entrées dans `AppStore.bundled()` au démarrage → visibles dans
    « Disponibles ». C'est le moyen d'ajouter de **vraies** apps sans modifier le dépôt.
- `src/nwupdater/apps/installer.py` — `AppInstaller` :
  - `check(blob)` — magic valide, zone apps présente, API level == device, taille ≤ espace.
  - `install(blob, at_offset)` — écrit le `.nwa` dans la zone external-apps via le client DFU,
    puis vérifie (read-back).

## Compatibilité (résolue côté client, comme le site)

L'hôte lit par DFU (Lot 1) la zone `external_apps_flash` (UserlandHeader) → espace dispo. Le
`.nwa` embarque son `api_level` (`AppInfo`). L'installation exige `api_level == device` et
`taille ≤ espace`. Les modèles **sans QSPI** (N0100, N02xx scientifique) n'ont **pas de zone
apps externes** → aucune app tierce installable (cohérent avec le hardware).

> Le `EXTERNAL_APPS_API_LEVEL` du device n'est pas exposé dans les headers lus par DFU (il
> est compilé dans l'OS et vérifié au runtime). `DEFAULT_DEVICE_API_LEVEL = 0`, configurable
> (`--api-level`). Un mapping version→API level plus fin peut être ajouté.

## CLI

```bash
nwupdater apps --virtual n0110                 # liste les apps compatibles
nwupdater apps --virtual n0110 --install Tetris  # télécharge le vrai .nwa, relink + flashe + vérifie
nwupdater apps --virtual n0200                 # scientifique: aucune zone apps externes
```

## Sources du catalogue

Le catalogue livré (`apps/data/community-apps.json`) ne contient que de **vraies** apps
téléchargeables, publiées par le dépôt de leur auteur (jamais hébergées ni modifiées par cet
outil) ; chaque `.nwa` est un ELF relocatable relinké pour l'appareil connecté au moment de
l'installation. Pour ajouter d'autres apps sans éditer ce fichier : déposer des `.nwa` dans le
dossier apps utilisateur (`NWUPDATER_APPS_DIR`) et/ou lister leurs URLs (une par ligne) dans
`<dossier>/_urls.txt` — agrégées automatiquement dans « Available ». Une entrée sans vraie URL
(placeholder `example.invalid`) retombe sur une image de démo synthétisée hors-ligne : elle
s'installe mais **plante au lancement** (code à zéro) — à ne jamais livrer.
