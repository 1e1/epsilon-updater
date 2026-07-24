# Changelog

Toutes les modifications notables de ce projet sont documentées ici. Le format s'inspire de
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; le projet suit un versionnage
[PEP 440](https://peps.python.org/pep-0440/).

## [Non publié]

### Ajouté

- **Branchement à chaud** : une calculatrice branchée *après* le lancement est détectée
  automatiquement (la page scanne toutes les 4 s) ; pendant qu'une vraie calculatrice est
  connectée, un test de vivacité (`GET /api/device/health`, DFU GETSTATE bénin, sérialisé avec
  les opérations via un verrou d'E/S) **détecte le débranchement** et repasse en mode scan.
  L'app packagée **ne bascule plus jamais en démo silencieusement** : la démo est explicite
  (`NWUPDATER_DEMO`/`--demo` ou le bouton « Explorer une démo »).
- **Mode classe — flash à la volée sans connexion élève** : une calculatrice dont le modèle est
  en cache se flashe **en un clic depuis le cache**, sans compte NumWorks ni re-téléchargement
  (l'enseignant se connecte une fois pour pré-télécharger). La version en cache est
  pré-sélectionnée ; `install_firmware(from_cache=True)` sans version résout l'entrée du modèle.
- **Canal du firmware en cache** : chaque entrée de cache mémorise son canal (`stable`/`beta`) ;
  l'interface et la CLI affichent un badge pour distinguer une image beta d'une stable en un
  coup d'œil.
- **Source d'apps utilisateur générique** : dépôt de `.nwa` locaux + liste d'URLs (`_urls.txt`)
  sous `NWUPDATER_APPS_DIR` (sinon `<config>/nwupdater/apps`), agrégés dans « Disponibles ». Les
  apps locales sont installées **telles quelles** (vrais octets, pas une image de démo).
- **Routage d'alt-setting DFU par découverte** : le `DfuClient` lit les régions annoncées par
  **chaque** alt-setting du device (`usbio`) et route chaque écriture vers l'alt propriétaire de
  l'adresse (Flash / SRAM / …). Aucune adresse ni alt codée en dur → N0100 … futur N0130 pris en
  charge automatiquement.

### Corrigé

- **Réactivité des boutons d'installation** (apps + scripts) : « Écrire » se verrouille et
  affiche « Écriture… » immédiatement (état occupé partagé), fermant aussi la fenêtre de
  double-soumission — plus d'impression d'absence de réaction pendant l'écriture DFU bloquante.
- **Écriture des scripts Python sur matériel réel** : l'écriture du storage (SRAM) était un
  *no-op silencieux* car émise sur l'alt-setting `@Flash`. Elle est désormais routée vers l'alt
  `@SRAM` (découverte du device) et **vérifiée par relecture** (`write_storage` lève si l'écriture
  n'atterrit pas). Confirmé write→verify→rollback sur une N0120 réelle.

## [1.0.0-rc.3] - 2026-07-24

### Ajouté

- **Capacités par device** (`nwupdater.capabilities`) : un resolver unique
  (`structural ∧ observed ∧ policy`) décide ce qu'un appareil peut faire (mise à jour firmware,
  apps `.nwa`, scripts Python). Le serveur l'expose dans le payload d'identité et l'utilise pour
  masquer automatiquement les ateliers non pertinents ; overlay `Policy` (ex. mode classe).

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
- **Serveur local — CSRF** : les requêtes mutantes (POST) exigent désormais un `Origin`
  same-origin ; un POST sans `Origin` ou d'origine étrangère est refusé (403). Les lectures
  (GET) restent tolérantes.
- **Serveur local — streaming** : plafond de taille aussi au téléchargement d'app en flux
  (pas seulement bufferisé), contre un CDN devenu hostile derrière une URL du catalogue.
- **Interface web** : les noms d'app/script passés aux handlers inline sont échappés en
  contexte JS (`jsStr`), fermant une injection DOM via une apostrophe dans un nom.
- **Cache « mode classe »** : `cached_version()` renvoie `None` pour un parc multi-versions ;
  écritures **atomiques** (temp + `os.replace`), pas de réécriture d'index sur lecture, index
  corrompu toléré (se reconstruit).
- **Parsing robuste** : plus de plantage sur entrée tronquée — `IndexError` sur un blob ELF
  court (icône d'app), `struct.error` sur en-têtes, image DfuSe ou commandes DFU malformés.
- Divers : suppression du flag `--real` mort, message clair quand aucune calculatrice n'est
  connectée, fermeture de fichier explicite, faux 403 sur loopback IPv6 avec port.

### Modifié

- **Cohérence du parsing d'en-têtes** : `dfu.identity` réutilise les parseurs de
  `formats.headers` (fin d'une seconde implémentation manuelle à offsets en dur). Tailles et
  magies centralisées dans `dfu.constants` (`SLOT_INFO_SIZE`, `KERNEL_HEADER_SIZE`,
  `EXTERNAL_APP_SECTOR`, magies `platform_info`) ; helpers `cstr`/`fixed` uniques.
- **Sortie Python en anglais** sur toute la couche (CLI + serveur + catalogue/install/modèles +
  outils de capture), conformément à la règle « sortie CLI/Python en anglais » ; la localisation
  FR/EN reste gérée côté interface web. Les docstrings internes restent en français.
- **Architecture** : point d'ouverture USB unique (`usbio.open_calculator`) éliminant
  l'inversion de couche `session → cli` ; bloc d'ouverture device factorisé dans le CLI
  (`_open_device`) ; primitives d'install d'app partagées (`validate_nwa`, `write_verified`) ;
  proxy de téléchargement d'apps extrait (`apps.proxy`, garde SSRF unique).
- **Découpe des gros fichiers** : `cli.py` scindé en `cli` (argparse + dispatch) / `cli_commands`
  (handlers) / `cli_device` (acquisition device) ; `session.py` scindé en une base `SessionBase`
  (état + cycle de vie device) et des mixins par préoccupation (catalogue, apps, auth, firmware,
  scripts). API publique et points d'entrée inchangés.

### Outillage

- Version en **source unique** (`nwupdater.__version__`, relue par `pyproject` via
  `dynamic`) ; fichier `VERSION` orphelin supprimé ; version alignée sur `1.0.0rc3`.
- Vérification de types **mypy** (gating) + marqueur `py.typed` : **100 % de `src`** typé et
  vérifié, plus aucun module différé.
- **Couverture** : `pytest-cov` avec un seuil (`fail_under = 80 %`, branche) sur le job Linux ;
  tests ajoutés pour les routes serveur, les wrappers auth de session, `apps.proxy`, `dfudiff`
  et le registre de modèles (couverture ~81 %).
- **Test UI headless** (Playwright + Chromium, job CI dédié, extra `test-ui`) : charge la page
  servie, vérifie qu'elle tourne sans erreur JS et que les fetch same-origin du navigateur
  atteignent l'API durcie CSRF — la couverture automatisée qui manquait à la couche JS/UI.
- **bandit** rendu bloquant en CI ; matrice CI étendue à **macOS** et **Windows** (fumée) en
  plus de Linux (Python 3.10–3.12).
- **Analyse de sécurité CodeQL** (Python + JavaScript de l'UI) et **Dependabot** (pip +
  github-actions) ajoutés.
- **Fichiers communautaires** : `CODE_OF_CONDUCT.md`, templates d'issue/PR, `CODEOWNERS`.
- **Format de code** : `ruff format` appliqué à tout le dépôt + `ruff format --check` en CI
  (style canonique, plus de débats de formatage).
