# Lot 5 — Packaging UI (page web locale)

Le cœur headless expose une **API HTTP locale** et sert une **page web** ouverte dans le
navigateur système, mais **sans WebUSB** : tout l'USB est fait dans le processus natif, le
navigateur ne fait qu'afficher.

## Architecture

```
Navigateur système  ──HTTP 127.0.0.1──▶  Serveur local (stdlib http.server)
   (page web locale)                        │
                                            ├─ Session (device virtuel ou réel)
                                            ├─ Catalogue (Lot 2)
                                            ├─ Installateur firmware (Lot 3)
                                            └─ Store + installateur apps (Lot 4)
                                                     │
                                                     ▼ USB (virtuel en dev)
                                            Appareil DFU
```

## Modules

- `src/nwupdater/server/session.py` — `Session` : détient la calculatrice connectée
  (virtuelle par défaut, `real=True` → pyusb) et expose identité / catalogue / apps /
  installs en dicts JSON.
- `src/nwupdater/server/httpd.py` — serveur **stdlib uniquement** (aucune dépendance) sur
  **loopback 127.0.0.1**. Routes :
  - `GET /api/identity` — modèle, famille, MCU, OS, zone apps.
  - `GET /api/catalog` — MàJ disponibles.
  - `GET /api/apps` — apps compatibles.
  - `GET /api/cache` — état du cache (version, expiration).
  - `POST /api/install/firmware` `{version, from_cache?}` — flash + vérif (slot inactif).
  - `POST /api/install/app` `{name}` — flash `.nwa` du store + vérif.
  - `POST /api/install/app-local` `{filename, data_b64}` — flash un `.nwa` **fourni par
    l'utilisateur** (méthode officielle : le navigateur lit le fichier, poste les octets).
  - `POST /api/cache/preload` `{version}` · `POST /api/cache/clear` — mode classe.
  - sinon : fichiers statiques `web/`.
- `src/nwupdater/server/web/` — page **autonome** (aucun host externe, theme clair/sombre) :
  - `index.html` — structure + CSS (design validé) + sélecteur de langue FR/EN.
  - `calc.js` — **rendu SVG fidèle** des deux familles (matrice réelle `keys.inc` :
    graphique blanc/écran couleur/alpha ; scientifique charbon/écran monochrome large).
  - `i18n.js` — dictionnaires **FR/EN** + `t(key, params)` ; langue auto-détectée
    (`navigator.language`), mémorisée (`localStorage`), basculable à chaud.
  - `app.js` — fetch de l'API, rendu, install firmware / app / `.nwa` local, mode classe
    (cache), toasts. Aucune chaîne serveur affichée : le client localise tout.

## Lancer

```bash
nwupdater ui                       # device virtuel n0110, ouvre le navigateur
nwupdater ui --virtual n0200       # émule une scientifique
nwupdater ui --no-browser --port 8791
nwupdater ui --real                # piloter une vraie calculatrice (pyusb requis)
```

## Packaging

- **Zéro dépendance runtime** pour la démo virtuelle (stdlib) → un binaire PyInstaller
  (`nwupdater`) embarque tout, y compris `web/`, `catalog/data/`, `apps/data/`
  (déclarés en `package-data`).
- `pip install 'nwupdater[usb]'` ajoute pyusb pour le mode réel.
- Alternative conteneur : image Docker exposant le port ; l'utilisateur ouvre l'URL.

## Sécurité / périmètre

- Écoute **loopback** par défaut (pas d'exposition réseau).
- Mode démo = **device virtuel**, aucun USB réel (conforme à la contrainte projet).
- Les installs « réelles » (`--real`) réutilisent exactement le même moteur DFU validé sur
  le mock.
