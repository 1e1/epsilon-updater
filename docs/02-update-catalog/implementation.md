# Lot 2 — Implémentation du catalogue

Voir [web-api.md](web-api.md) pour la cartographie de l'API. Ce document décrit le code.

## Modules

- `src/nwupdater/catalog/version.py` — parsing/comparaison des versions NumWorks
  (dotted-numeric, façon `KernelHeader::softwareVersionComparedTo`). `25.2.0` → `(25, 2)`,
  robuste aux `\x00`/espaces.
- `src/nwupdater/catalog/firmware.py` — `FirmwareRelease`, `FirmwareCatalog` :
  - `bundled()` — snapshot embarqué (offline par défaut) : `catalog/data/firmwares.json`.
  - `for_family(famille, public=…)` — les versions d'**une** famille (voir ci-dessous). C'est
    le seul point d'entrée des interfaces : CLI, web, bureau et mode classe.
  - `fetch(url=CATALOG_URL)` — rafraîchit en ligne (seul point réseau du Lot 2).
  - `load(path)` / `from_json(data)` — sources locales / tests.
  - `updates_for(current)` — versions strictement plus récentes, plus récente d'abord.
  - `is_up_to_date(current)`, `latest()`, `get(version)`.
- `catalog/data/firmwares.json` — **instantané réel** capturé le 2026-07-12 depuis
  `https://my.numworks.com/firmwares.json` (60 versions, dernière 25.2.0). Copie de
  référence dans [`../reference/captures/firmwares.json`](../reference/captures/firmwares.json).

## Point important : le catalogue n'a pas de dimension « modèle »

`firmwares.json` liste des versions Epsilon **sans champ modèle** ni URL binaire (confirmé,
cf. web-api.md). La compatibilité modèle↔version est résolue **côté client** à l'installation
(headers kernel/userland, Lot 1). Donc `updates_for()` est un simple filtrage par version ;
le modèle lu par DFU sert au contexte et au ciblage du binaire (Lot 3).

**La liste publique mélange les familles.** Les versions Scientifique (N02xx : `2.1.0`, `3.0.0`,
`4.1.0`) y côtoient celles du Graphique. La table `FAMILY_SNAPSHOTS` de `catalog/firmware.py`
associe à une famille sa propre piste (`catalog/data/firmwares-<famille>.json`). Une famille sans
piste propre lit la liste publique, moins les versions qu'une autre piste revendique. Le code ne
connaît aucun modèle : ajouter une famille, c'est une ligne dans la table et un fichier.

Connecté, le **manifeste officiel** par modèle (`/firmwares/<modèle>/<canal>.json`) prime sur
ces pistes, pour toutes les familles. `Session._latest_version(modèle, canal)` donne cette réponse
unique au panneau Système, au préchargement du cache et au lot du mode classe.

## CLI

```bash
nwupdater catalog --virtual n0110 --os-version 16.4.4   # liste 29 MàJ (snapshot offline)
nwupdater catalog --virtual n0200 --os-version 25.2.0   # → à jour
nwupdater catalog --virtual n0110 --fetch               # rafraîchit en ligne, repli snapshot
```

## À compléter (Lot 3)

Le catalogue ne fournit pas d'URL `.bin` (elle est derrière la page authentifiée
`/devices/upgrade/`). La résolution version → binaire est traitée au Lot 3 (transfert), avec
la session authentifiée du compte de test ou une source alternative.
