# Lot 2 — API web du catalogue de mises à jour

But du Lot 2 : à partir de l'identité d'une calculatrice (modèle + version, lue par DFU au
Lot 1), **lister les mises à jour disponibles**. Cartographie du backend NumWorks.

Légende : **[CONFIRMÉ]** = requête effectuée + réponse observée · **[INFÉRÉ]** = déduit.

## Topologie

- **Le « Workshop » = `my.numworks.com`.** `workshop.numworks.com` **301/302 →
  `https://my.numworks.com/`** [CONFIRMÉ].
- `apps.numworks.com`, `platform.numworks.com`, `api.numworks.com` **ne résolvent pas**
  (pas de DNS) [CONFIRMÉ] — pas de host API séparé. Tout est sous `my.numworks.com`.
- `my.numworks.com` = app **Rails** (Devise pour l'auth + Hotwire/Turbo). Le bundle JS
  `https://cdn.numworks.com/*.js` est **marketing uniquement** (0 occurrence de
  firmware/dfu/webusb) [CONFIRMÉ]. La logique WebUSB vit dans les pages authentifiées
  `/devices/upgrade/` et `/apps`.

## Catalogue firmware — **endpoint PUBLIC** ⭐ [CONFIRMÉ]

```
GET https://my.numworks.com/firmwares.json     → 200 application/json
GET https://my.numworks.com/firmwares          → 200 application/json (même corps, négocié)
```
- **Aucune auth, aucun cookie.** `cache-control: max-age=0, private, must-revalidate`.
- Réponse : tableau JSON plat, **du plus récent au plus ancien**, de `{version, patch_level}`
  (`patch_level` = hash court du commit git). **⚠️ Ne contient PAS d'URL `.bin`/`.dfu`** —
  seulement les métadonnées de version.

Extrait capturé (2026-07) :
```json
[{"version":"25.2.0","patch_level":"43f67db"},
 {"version":"24.11.0","patch_level":"a58aaa0"},
 {"version":"24.10.0","patch_level":"cc796b7"},
 {"version":"24.8.0","patch_level":"bea4886"},
 ...
 {"version":"1.1.0","patch_level":"679cea7"}]
```
60 entrées de 1.1.0 → **25.2.0** (dernière au moment de la capture).

Changelog HTML public : `GET https://my.numworks.com/firmwares/` → 200 text/html.

### Deux schémas de versionnage selon la famille [CONFIRMÉ]

⚠️ `firmwares.json` est le catalogue de la famille **Graphique (N01xx)** : versions **datées
par année** (`17.2.0`, `19.x`=2022, … jusqu'à **`25.2.0`**, la dernière). Le `3.0.0` présent
dans ce fichier est un **firmware graphique legacy (~2018)** de l'ancienne séquence
`1.x → 2.1.0 → 3.0.0 → … → 16.4.4` — **à ne pas confondre** avec la scientifique.

La famille **Scientifique (N02xx)** a sa **propre numérotation entière** (Version 1, 2, 3…) :
- Dernière : **Version 3**, publiée le **10 juin 2026** (résultats supplémentaires dans
  Calculs, menu unités d'angle dans la boîte à outils, réglage du contraste).
- Page officielle : `https://www.numworks.com/fr/scientifique/mise-a-jour/`.
- Mise à jour via le **même portail** `my.numworks.com/devices/upgrade/` (WebUSB/DFU).
- **Pas de catalogue JSON scientifique public trouvé** (les variantes de chemin testées →
  404 ; `?product=scientific` est ignoré et renvoie le catalogue graphique). La liste des
  versions scientifiques n'est donc pas exposée en JSON anonyme → à récupérer via la page
  authentifiée (compte de test) ou la page publique de MàJ.

## Pages upgrade / rescue — **AUTH** [CONFIRMÉ]

```
GET https://my.numworks.com/devices/upgrade/  → 302 → /users/sign_in   (page de flash WebUSB)
GET https://my.numworks.com/devices/rescue/   → (recovery / DFU bootloader)
```
L'**URL de téléchargement du `.bin` firmware est servie DANS la page upgrade
authentifiée** et n'a pas pu être énumérée anonymement. Chemins devinés → 404 :
`my.numworks.com/firmwares/25.2.0/epsilon.onboarding.internal.bin`,
`cdn.numworks.com/firmwares/…`, `/firmwares/latest.json` [CONFIRMÉ négatif].

## Binaires firmware — nommage & modèle de flash [CONFIRMÉ via source]

Le firmware NumWorks = **deux binaires bruts** flashés à deux régions :
- `epsilon.onboarding.internal.bin` → **flash interne `0x08000000`**
- `epsilon.onboarding.external.bin` → **flash externe `0x90000000`** (n0110/n0120 ; absent
  sur n0100/n0200 qui n'ont pas de QSPI)

Le flash se fait **côté client en WebUSB DFU**, sans round-trip serveur : le navigateur
télécharge le `.bin` (depuis la page authentifiée) puis le streame au device via
`navigator.usb`. → notre updater fait pareil mais avec `libusb`/pyusb (Lot 3).

## Auth (Devise) [CONFIRMÉ]

- `GET /users/sign_in` → 200 (formulaire email+password). `POST /users/sign_in` avec
  `user[email]`, `user[password]` + `authenticity_token` (CSRF du formulaire), réutiliser le
  **cookie de session** [INFÉRÉ, Devise standard].
- `GET /users/sign_in.json` → 406 (pas d'API JSON d'auth).
- `GET /oauth/authorize|token` → 404 (**pas d'OAuth public**).
- **Public** : `/firmwares.json`, `/firmwares`, `/firmwares/`, `www.numworks.com/*`,
  `cdn.numworks.com/*`. **Auth** : `/devices/upgrade/`, `/devices/rescue/`, `/apps`,
  `/apps.json`, et les binaires firmware.

## Conséquences pour le Lot 2

1. **Le catalogue est trivialement reproductible offline** : servir/parser `firmwares.json`.
   C'est le seul endpoint firmware public ; il n'a pas d'URL binaire.
2. **Le filtrage par modèle est côté client** : `firmwares.json` liste les versions Epsilon
   sans distinction de modèle. La compatibilité modèle↔version est vérifiée à l'install (les
   headers kernel/userland, Lot 1). Notre catalogue croise donc `firmwares.json` avec le
   modèle lu par DFU.
3. **Récupérer le `.bin`** nécessite soit la session authentifiée (compte de test → POST
   sign_in → suivre la page upgrade pour extraire l'URL réelle), soit une source alternative
   (voir [firmware-hosting.md](firmware-hosting.md) — à compléter au Lot 2/3).
4. **Endpoint local à exposer** (Lot 5) : `GET /api/catalog?model=n0110&version=23.2.4` →
   liste des versions ≥ courante compatibles, agrégée depuis `firmwares.json`.

## Table de référence rapide

| URL | Méthode | Auth | Réponse | Statut |
|---|---|---|---|---|
| `my.numworks.com/firmwares.json` | GET | Public | `[{version,patch_level}]` | 200 [CONFIRMÉ] |
| `my.numworks.com/firmwares` | GET | Public | idem (négocié) | 200 [CONFIRMÉ] |
| `my.numworks.com/firmwares/` | GET | Public | changelog HTML (graphique) | 200 [CONFIRMÉ] |
| `www.numworks.com/fr/scientifique/mise-a-jour/` | GET | Public | page MàJ scientifique (Version 3, 10/06/2026) | 200 [CONFIRMÉ] |
| `my.numworks.com/devices/upgrade/` | GET | Login | page flash WebUSB | 302 [CONFIRMÉ] |
| `my.numworks.com/devices/rescue/` | GET | Login | recovery/DFU | [INFÉRÉ] |
| `my.numworks.com/users/sign_in` | GET | Public | form Devise | 200 [CONFIRMÉ] |
| `my.numworks.com/oauth/*` | GET | — | 404 | [CONFIRMÉ] |
| firmware `.bin` | GET | Login | `epsilon.onboarding.{internal,external}.bin` | [INFÉRÉ] |
