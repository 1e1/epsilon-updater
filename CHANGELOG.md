# Changelog

Toutes les modifications notables de ce projet sont documentées ici. Le format s'inspire de
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; le projet suit un versionnage
[PEP 440](https://peps.python.org/pep-0440/).

## [Non publié]

### Modifié (taille des binaires)

- **Binaires plus légers** : la spec PyInstaller élague les extensions C de la stdlib jamais
  utilisées par cet outil (codecs CJK, `_decimal`, `pyexpat`, `readline`, `_sqlite3`, `_curses`),
  active `strip` et `optimize=2`. ≈ **−17 %** mesuré (arm64 : 7,2 → 6,0 Mo zip). `unicodedata`
  est conservé (le codec IDNA du bind `http.server` en dépend), ainsi qu'OpenSSL (HTTPS + hash).
- **macOS — deux téléchargements par architecture** au lieu d'un binaire universel : le build
  universel2 est découpé (`ditto --arch` + re-signature ad-hoc) en `…-macos-arm64.zip`
  (Apple Silicon) et `…-macos-x86_64.zip` (Intel), chacun ≈ moitié plus petit.

## [2.0.0-rc.3] - 2026-07-25

### Corrigé (retours test N0120 réelle)

- **Connexion plus réactive** : le rail appareil + l'onglet Système (flash / compte / cache)
  s'affichent **immédiatement** ; les lectures USB lentes (apps / scripts / parc) chargent en
  arrière-plan puis repeignent. Elles restent en cache — basculer Classe↔Individuel **ne rescanne
  plus** (seule une nouvelle connexion relit l'appareil).
- **Zone apps parfois « — » / onglet Applications en retard sur Scripts** : lecture DFU durcie —
  `SlotInfo` et `UserlandHeader` sont relus (jusqu'à 3 tentatives) pour qu'une trame glitchée ne
  fasse plus disparaître la région d'apps (chemin sain inchangé, 1 lecture).
- **Mode batch** : la mention « Simuler » disparaît quand une **vraie calculatrice est branchée**
  (rien à simuler) ; elle reste en attente / sur device virtuel.
- **Classe · Calculatrices** : suppression de la colonne « Actions » (et du menu déroulant par
  ligne) — déplacer se fait par glisser-déposer sur une classe ou via la barre de sélection
  multiple, conformément à la maquette.
- **Classe · suppression de classe** : la confirmation s'affiche désormais dans une barre **sur une
  seule ligne, sous la barre d'onglets**, visible depuis Calculatrices **et** Distribution (elle
  était auparavant rendue dans l'onglet Calculatrices → clic sans effet visible depuis Distribution).
- **Ateliers Apps/Scripts** : retrait du bouton « Ouvrir le dossier » redondant (le popover
  « Sources » ouvre déjà les dossiers locaux en cliquant leurs lignes).

## [2.0.0-rc.2] - 2026-07-25

### Ajouté

- **Mode Classe — refonte « console de parc » (maquette approuvée)** : en mode Classe le rail gauche
  devient la **liste des classes** (Toutes en haut · classes triées · Sans classe en bas) et la barre
  d'onglets pleine largeur passe à **Calculatrices | Distribution** + [supprimer la classe] +
  [Mode batch]. Les onglets Système/Apps/Scripts (centrés appareil) sont retirés en mode Classe.
- **Onglet Distribution (config par classe)** : **Recensement** (déplacer/ignorer une calculatrice
  déjà rangée ailleurs, toujours visible), **Chaîne d'actions** ordonnée (recensement → firmware →
  apps → scripts, **Firmware désactivé par défaut**), et les panneaux **Firmware / Applications /
  Scripts** qui n'apparaissent que si leur action est activée. Persistée dans le parc
  (`classroom_roster.set_distribution`, `POST /api/roster/dist`).
- **Panneau Firmware = gestion des caches** (déplacé depuis Système) : « Mettre à jour les caches »
  **prolonge le TTL de 30 j sans re-télécharger** quand la version cachée est déjà à jour
  (`FirmwareCache.touch`, `preload_all` renvoie `refreshed`/`downloaded`).
- **Mode batch (kiosque de provisionnement)** : armer une fois, chaque calculatrice branchée exécute
  automatiquement la chaîne d'actions de la classe (recensement · flash firmware depuis le cache ·
  apps · scripts, uniquement le **manquant**), avec **journal par appareil** (passages précédents
  grisés au re-branchement), **arrêt** toujours visible, et un bouton **Simuler** (device virtuel)
  pour tester sans matériel. `Session.batch_run` compose les opérations atomiques existantes ;
  `POST /api/batch/run`. Le numéro de série n'atteint jamais le DOM du journal.
- **Individuel — ouvrir le dossier local** : un lien discret « Ouvrir le dossier » dans l'en-tête
  des ateliers Apps/Scripts (et les chemins du popover Sources) révèle la bibliothèque locale dans
  le gestionnaire de fichiers de l'OS pour purger à la main (`POST /api/reveal`, verrouillé aux deux
  dossiers gérés — jamais de chemin arbitraire).
- **Individuel — préflight nwlink** : l'onglet Applications avertit **avant** l'installation qu'une
  app distribuée (ELF, ex. Tetris) nécessite nwlink (Node) s'il est absent, et l'erreur d'install est
  remplacée par un message clair et traduit (`/api/apps` expose la disponibilité de nwlink).

### Modifié

- **Individuel — rafraîchissement plus fréquent** : les bibliothèques Apps/Scripts se rechargent au
  retour de focus sur la fenêtre + à intervalle léger (sans écraser un plan d'écriture en cours), de
  sorte qu'une purge manuelle du dossier local se reflète sans reconnecter.
- **Compte — libellé honnête** : la carte Compte n'affirme plus « nomme vos calculatrices (synchro
  cloud) » ; le **nom reste local** à l'outil. La synchro cloud du nom est **différée** (décision
  produit) mais son flux `my.numworks` est désormais rétro-conçu et **documenté**
  (`docs/01-specs/scripts-and-device-pairing.md`) pour une implémentation propre ultérieure.

## [1.0.0-rc.6] - 2026-07-25

### Ajouté

- **Installation d'apps `.nwa` distribuées (relink à l'installation)** : un `.nwa` publié est un
  **ELF relogeable**, pas un blob AppInfo plat — il faut le **lier aux adresses flash/RAM de
  l'appareil** avant de le flasher. Le link est délégué à `nwlink nwa-bin` (**hors ligne**),
  alimenté par les paramètres cible résolus en DFU, puis flashé par notre moteur DFU
  (`apps/link.py` : `is_relocatable_nwa`, `LinkTarget.from_identity`, `link_nwa`, `ensure_linked` ;
  trampoline EADK dérivé de l'`UserlandHeader`, avec garde `trampoline_word_looks_valid`). Validé
  sur **N0120 réelle** (RPN s'installe et se lance).

### Corrigé

- **Statut « officiel » / examen — correction majeure (l'affirmation rc5 était fausse)** :
  l'analyse du firmware Epsilon + du flux WebUSB officiel, **confirmée sur N0120 réelle**, établit
  que « officiel » est une **signature Ed25519 vérifiée par le bootloader au démarrage à froid**,
  **entièrement hors ligne** (aucune attestation réseau). Le bandeau « UNOFFICIAL SOFTWARE » vu en
  rc5 venait du **saut DFU** (`leave`, le « boot » in-app) utilisé pour booter — **pas** des octets
  du slot. Flasher l'**image officielle signée** puis **redémarrer à froid** (RESET) rend l'appareil
  **officiel** : la mise à jour hors ligne vers un firmware conforme examen **est donc faisable**
  (image officielle signée + boot à froid, pas le saut DFU). Un firmware non signé reste « non
  officiel » (signature non forgeable). Nouvelle spec :
  [`docs/01-specs/firmware-authenticity.md`](docs/01-specs/firmware-authenticity.md).
- **`boot()` garde la calculatrice *officielle* (plus de RESET manuel)** : le « boot » après flash
  faisait un saut DFU *dans* le slot (secteur reflashable) → le noyau le marquait « UNOFFICIAL
  SOFTWARE ». Désormais `boot()` fait le `leave` vers la **base flash interne `0x08000000` (le
  bootloader)** → `Reset::core()` = **boot à froid** → le bootloader re-vérifie la signature →
  **officiel sans manip**. Reproduit le flux WebUSB officiel (capturé sur N0120 **et** N0200
  réelles : `leave` final vers `0x08000000`). Constante `dfu.constants.BOOTLOADER_RESET_ADDRESS`.
  Documenté dans [`docs/reference/official-webusb-analysis.md`](docs/reference/official-webusb-analysis.md).
- **N0200 — flash hors-ligne VIABLE (correction)** : la capture du flux WebUSB officiel sur N0200
  réelle montre que le mode `0xA51A` **accepte directement** les écritures DfuSe vers `0x98000000`
  (`SET_ADDRESS`/bloc + `DNLOAD`, **sans erase**, **sans bascule de mode ni changement de PID**,
  sans attestation en ligne). L'outil le fait **déjà** (mono-slot, `flash_erase=False`).
  [`docs/01-specs/n02xx-firmware-format.md`](docs/01-specs/n02xx-firmware-format.md) corrigé
  (l'ancienne conclusion « ni viable ni sûr » était fausse) + layout du **FirmwareHeader**
  `0xFACECAFE` (version on-device lisible).

### Modifié

- **Interface — orientation post-flash** : les messages `confirm_flash`, `exam_warn`, `fw_reboot`
  (FR/EN) orientent désormais vers un **démarrage à froid (RESET)** après un flash pour conserver le
  statut officiel, au lieu d'affirmer (à tort) que tout flash rend l'appareil non conforme examen.
  `DISCLAIMER.md`, `README.md` et `docs/03-transfer-install/implementation.md` corrigés en
  conséquence.

## [1.0.0-rc.5] - 2026-07-25

### Ajouté

- **Avertissement examens dans l'interface** : bandeau persistant dans la carte de mise à jour et
  **dialogue de confirmation renforcé** (FR/EN) avant tout flash — flasher un firmware via cet
  outil, **même l'image officielle**, marque l'appareil « UNOFFICIAL SOFTWARE » et rompt la
  conformité au mode examen ; renvoi vers my.numworks.com pour un firmware certifié. S'applique
  aussi au flash « mode classe » en un clic depuis le cache.

### Corrigé

- **Flash firmware A/B — slot inactif uniquement** : sur un appareil en marche le slot **actif**
  est protégé matériellement (un `erase` renvoie `errTARGET` et **fige la session DFU** jusqu'à un
  reset physique — constaté sur N0120 réelle). `install_firmware` détecte désormais le slot actif
  (`_active_slot` via `SlotInfo`) et n'écrit **que le slot inactif** ; un `.dfu` complet A+B n'est
  plus écrit verbatim.

### Documentation

- **Certification examen non reproductible hors ligne** : le statut « officiel » (donc la
  conformité au mode examen) est posé par le **flux d'installation signé**, **pas** par les octets
  du slot userland. Constaté sur N0120 réelle : un slot flashé par cet outil contient les octets
  officiels **rebasés octet-exact** (seule différence = la relocation d'adresse par slot,
  `0x90000000` vs `0x90400000`) et boote pourtant « UNOFFICIAL SOFTWARE ». On peut copier les
  octets mais **pas forger l'attestation d'install signée** → installer un firmware certifié examen
  **hors ligne est infaisable par conception**. Firmware certifié via my.numworks.com. Détaillé
  dans `docs/03-transfer-install/implementation.md`.
- **N0200 — flash hors ligne non viable** : en runtime (PID `0xA51A`), la N0200 n'expose qu'une
  région DFU `@FirmwareHeader/0x080040C0/01*64Ba` de **64 octets en lecture seule** (type `a`),
  aucune région inscriptible ; le firmware réel (~232 Kio @ `0x98000000`) n'y est ni adressable ni
  inscriptible. Le flux officiel doit basculer l'appareil en mode flasher (déclenché
  logiciellement — pas de bouton reset). Combiné au mono-slot et au firmware chiffré/signé, le
  flashage **hors ligne du firmware N0200 n'est ni viable ni sûr** avec cet outil → my.numworks.com.
  Détaillé dans `docs/01-specs/n02xx-firmware-format.md`.

## [1.0.0-rc.4] - 2026-07-24

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
- **Export apps/scripts vers l'ordinateur** : les apps `.nwa` et scripts `.py` installés sur la
  calculatrice peuvent être **exportés vers l'ordinateur** (bibliothèque locale sous le dossier
  apps/scripts utilisateur), avec un indicateur « déjà sur l'ordinateur » quand un fichier de même
  nom et taille y est déjà présent.

### Corrigé

- **Réactivité des boutons d'installation** (apps + scripts) : « Écrire » se verrouille et
  affiche « Écriture… » immédiatement (état occupé partagé), fermant aussi la fenêtre de
  double-soumission — plus d'impression d'absence de réaction pendant l'écriture DFU bloquante.
- **Écriture des scripts Python sur matériel réel** : l'écriture du storage (SRAM) était un
  *no-op silencieux* car émise sur l'alt-setting `@Flash`. Elle est désormais routée vers l'alt
  `@SRAM` (découverte du device) et **vérifiée par relecture** (`write_storage` lève si l'écriture
  n'atterrit pas). Confirmé write→verify→rollback sur une N0120 réelle.

### Outillage

- **Harnais de test JS (Playwright)** : `tests/test_ui_logic.py` teste la logique de `app.js` en
  navigateur réel — logique pure (planificateur d'écriture, résolveur de cache par modèle,
  échappement `jsStr`) via `page.evaluate`, et interaction (staging → « Écrire » → mise à jour de
  la liste device). Un filet de sécurité pour refactorer l'interface.
- **Couverture durcie** à l'aide de calculatrices réelles : tests précis du routage d'alt-setting,
  de la découverte multi-alt (`usbio`), de la reprise de la machine à états DFU (`make_idle`), de
  la vérification d'écriture du storage et de la branche de téléchargement firmware.

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
