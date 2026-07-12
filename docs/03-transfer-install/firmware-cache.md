# Lot 3 — Cache firmware (mode classe)

Pré-télécharger un OS **une seule fois** puis flasher **toute une classe** hors-ligne.

## Politique

- **Une seule version à la fois.** Mettre en cache un firmware d'une *autre* version vide
  d'abord tout le cache → le cache ne contient jamais qu'une version d'OS (ses binaires
  peuvent couvrir plusieurs modèles présents dans la classe, ex. n0110 + n0120).
- **Auto-suppression après 30 jours.** Chaque entrée porte un `downloaded_at` ; les entrées
  plus vieilles que le TTL sont purgées à chaque accès (et via `cache --prune`).
- Le module ne fait **aucun réseau** : il stocke des octets déjà téléchargés. Le temps est
  injectable (`now`) → l'expiration est testable sans attendre.

## Module

`src/nwupdater/cache/store.py` — `FirmwareCache` :
- `put(model, version, data)` — stocke (évince l'ancienne version), renvoie l'entrée
  (taille + sha256 + horodatage).
- `get/has(model, version)`, `entries()`, `status()`, `prune()`, `clear()`.
- `default_cache_dir()` → `~/.cache/nwupdater/firmware` (respecte `XDG_CACHE_HOME`).
- Index `index.json` + binaires `<model>-<version>.bin`.

## CLI

```bash
# Poste "maître" : pré-télécharger une fois
nwupdater preload n0110 25.2.0

# Vérifier le cache (version conservée, échéance)
nwupdater cache            # → version 25.2.0 · modèles n0110 · expire dans 30 j
nwupdater cache --prune    # purge les entrées expirées
nwupdater cache --clear    # vide

# Pour chaque calculatrice de la classe : flash SANS re-télécharger
nwupdater install --virtual n0110 --to-version 25.2.0 --from-cache
```

## Intégration UI (Lot 5)

L'interface expose un « mode classe » : bouton **Pré-télécharger**, indicateur
« en cache : 25.2.0 · expire dans 30 j », puis les flashs suivants lisent le cache. Idéal
pour un poste enseignant qui met à jour une série de calculatrices.

## À raccorder (prod)

`preload` prend aujourd'hui une image synthétique (démo offline). En production, il
récupère le vrai `.bin`/`.dfu` (URL derrière `/devices/upgrade/`, via le compte) puis
`put()` dans le cache — le reste (install `--from-cache`) est déjà opérationnel.
