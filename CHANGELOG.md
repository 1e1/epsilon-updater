# Changelog

Toutes les modifications notables de ce projet sont documentées ici. Le format s'inspire de
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; le projet suit un versionnage
[PEP 440](https://peps.python.org/pep-0440/).

## [Non publié]

### Corrigé

- **Sécurité — fuite de jeton d'authentification** : le cookie `remember_user_token` n'est
  plus transmis lors d'une redirection HTTP vers un hôte différent (le téléchargement du
  firmware officiel peut rediriger vers un CDN tiers). Les en-têtes `Cookie`/`Authorization`
  sont retirés dès que l'hôte cible change.
- **Effacement flash par secteur** : la gestion des applications réémettait un effacement par
  chunk de transfert (2048 o) au lieu du secteur de 64 KiB, effaçant chaque secteur 32 fois
  (usure et lenteur inutiles).
- **Serveur local** : confinement des fichiers statiques via `is_relative_to` (au lieu d'un
  test de préfixe contournable) et plafond de taille sur le corps des requêtes.
- **Parsing robuste** : plus de plantage sur entrée tronquée — `IndexError` sur un blob ELF
  court (icône d'app), `struct.error` sur en-têtes, image DfuSe ou commandes DFU malformés.
- **Cache « mode classe »** : `cached_version()` renvoie désormais `None` pour un parc
  multi-versions, au lieu d'une version arbitraire.
- Divers : suppression du flag `--real` mort, message clair quand aucune calculatrice n'est
  connectée, fermeture de fichier explicite, faux 403 sur loopback IPv6 avec port.

### Modifié

- **Cohérence du parsing d'en-têtes** : `dfu.identity` réutilise les parseurs de
  `formats.headers` (fin d'une seconde implémentation manuelle à offsets en dur). Tailles et
  magies centralisées dans `dfu.constants` (`SLOT_INFO_SIZE`, `KERNEL_HEADER_SIZE`,
  `EXTERNAL_APP_SECTOR`, magies `platform_info`) ; helpers `cstr`/`fixed` uniques.
- **Couche Python en anglais** (serveur, session, dfudiff, usbio), conformément à la règle
  « sortie CLI/Python en anglais » ; la localisation FR/EN reste gérée côté interface web.

### Outillage

- Version en **source unique** (`nwupdater.__version__`, relue par `pyproject` via
  `dynamic`) ; fichier `VERSION` orphelin supprimé ; version alignée sur `1.0.0rc2`.
- Vérification de types **mypy** + marqueur `py.typed` (cœur typé ; `server`/`tools`/`testing`
  différés le temps du découpage serveur).
- **bandit** rendu bloquant en CI ; matrice CI étendue à **macOS** et **Windows** (fumée) en
  plus de Linux (Python 3.10–3.12).
