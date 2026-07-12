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
nwupdater apps --virtual n0110 --install Tetris  # démo: synthétise + flashe + vérifie
nwupdater apps --virtual n0200                 # scientifique: aucune zone apps externes
```

## À raccorder (prod)

Remplacer les URLs d'exemple du store par de vraies sources `.nwa` (compte NumWorks
authentifié `/apps` et/ou dépôts communautaires), puis télécharger le `.nwa` et appeler
`AppInstaller.install(blob)` — la logique flash/vérif est déjà là.
