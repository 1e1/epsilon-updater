# Changelog

Toutes les modifications notables de ce projet sont documentées ici. Le format s'inspire de
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; le projet suit un versionnage
[PEP 440](https://peps.python.org/pep-0440/).

## [Non publié]

### Outillage

- **Dependabot n'épingle plus `github/codeql-action` à une version exacte.** Les workflows suivent
  le tag majeur flottant (`@v4`), donc les versions mineures et correctives arrivent sans PR. Une
  PR d'épinglage laissée ouverte quelques semaines finit au contraire par **faire reculer**
  l'action : celle qui proposait `v4.37.3` pointait, à sa fermeture, sur un commit antérieur à
  celui de `@v4`. Les montées de majeure restent signalées — seules elles exigent d'éditer le
  workflow.

## [3.0.0-rc.4] - 2026-09-10

**Passe de qualité avant la 3.0 finale.** Un audit du portage Qt, avant de figer. Il a sorti neuf
défauts visibles à l'écran, une règle d'architecture que le code n'honorait pas, et trois lignes
fausses dans la grille de qualité du projet lui-même. Le neuvième — changer de langue ne
redessinait rien — a été trouvé par un test écrit pour vérifier autre chose : la présentation
n'était couverte par rien.

### Corrigé

- **Le sélecteur de modèle de démo ne fonctionnait pas** sur l'écran « aucune calculatrice » — le
  premier que voit quiconque n'a pas de câble branché. Un `textRole` posé sur une liste de chaînes
  : toutes les entrées s'affichaient **vides**, et « Explorer une démo » transmettait `undefined`.
  Qt ne signale rien dans ce cas, pas même un avertissement.
- **La barre d'état affichait les clés de traduction brutes.** L'utilisateur lisait
  `real_connected`, `install_ok::20.4.0`, `bad_ext::.nwa`. Le backend émet désormais une **clé et
  ses paramètres** (`toast(key, params, isError)`), la barre appelle `i18n.t()` — et quatre de ces
  clés n'existaient dans aucun des deux dictionnaires. Toutes réutilisent celles de l'IHM web
  (`fail`, `fw_done`, `written_ok`, `exported`, `wrong_ext`, `already_staged`) : aucune clé
  inventée, parité exacte.
- **La colonne « Distribution » du tableau du parc était un tiret en dur.** `last_dist` était
  pourtant dans le payload depuis l'arrivée du mode batch, et l'IHM web dessine ces pastilles.
  Elle les dessine maintenant aussi, par le même composant que le journal de batch.
- **Les dates « dernier passage » restaient en français** avec l'interface en anglais : la chaîne
  était formatée en Python. `format.relative_key()` renvoie désormais une **clé + un compte**, que
  QML rend — la colonne suit donc un changement de langue sans recalcul.
- **Le niveau d'API des applications n'était jamais affiché**, bien que calculé et exposé. Il l'est
  — accompagné de la **pastille d'incompatibilité** de l'IHM web, qui signale une app exigeant une
  API plus récente que celle de la calculatrice.
- **La barre de menus native était absente sous Windows et Linux** (hors bureaux à menu global).
  `Qt.labs.platform` n'a d'implémentation native que sur macOS et se replie sur des widgets, repli
  qui exige un `QApplication` — l'app construisait un `QGuiApplication`. Coût mesuré du correctif :
  **+9,2 Mo de RAM**, les 6 Mo de disque étant déjà payés.
- **Le compteur de sélection du parc mentionnait un nombre que le tableau ne montrait pas** après
  un Maj-clic sous filtre : cette branche seule le recalculait d'une autre façon, en comptant les
  lignes masquées.
- **Le journal de batch affichait des clés non traduites** (`recensement`, `firmware`) et peignait
  l'issue « erreur » avec un fond bleu, faute d'un token `errSoft` dans le thème.
- **Changer de langue ne redessinait rien.** Le menu Français/English ne décidait en réalité que
  de l'apparence du **prochain** lancement : sur 22 libellés à l'écran, **zéro** suivait. Une
  liaison QML ne se réévalue que si une *propriété* qu'elle a lue change, et `i18n.t("clé")` est
  un appel de slot — il ne crée aucune dépendance. Le docstring de `i18n.py` affirmait pourtant
  l'inverse depuis l'origine. La propriété de contexte est désormais réinstallée sur
  `langChanged`, ce qui invalide toutes les liaisons qui la référencent : 15 libellés sur 22
  basculent (les 7 autres sont des versions et des noms de modèle, identiques dans les deux
  langues). Trouvé par le test qui vérifiait la barre d'état.
- **La fermeture générait une volée de `TypeError` QML** : les objets exposés à la scène étaient
  libérés avant elle. Ils sont parentés à l'application, et le moteur est détruit en premier.

### Modifié

- **Plus aucune E/S appareil sur le thread graphique — les lectures comprises.** L'en-tête de
  `backend.py` affirmait cette règle ; elle ne valait que pour les écritures. `refresh()` lit tout
  l'inventaire dans un worker et renvoie un instantané que le thread graphique se contente
  d'affecter. Sur appareil **virtuel** (donc sans USB) : constructeur **178 → 0 ms**, coût d'un
  rafraîchissement sur le thread graphique **71 → 0 ms**, six frappes dans le filtre du parc
  **172 → 1 ms** — le filtre relisait tout le registre à chaque caractère.
- **`Session.roster()` ne relit plus le registre une fois par classe** (`all_distributions()` en
  un seul chargement) : **34,4 → 6,1 ms** sur un parc de 240 calculatrices et 8 classes. Les deux
  IHM en profitent.
- **`Session.io()`** — un gestionnaire de contexte public remplace l'accès direct à `_io_lock`
  depuis l'extérieur ; la sérialisation des E/S a désormais un point d'entrée documenté.
- **`Main.qml` : 502 → 230 lignes.** Barre de menus, bandeau d'onglets, barre de confirmation,
  barre d'état et les deux états « pas de calculatrice » deviennent des composants ; les deux
  `StackLayout` concurrents fusionnent en un seul. Les deux colonnes de l'atelier, jusque-là
  dupliquées à l'identique, partagent un `WorkshopColumn`.
- **Les tables d'actions de distribution fusionnent** dans un singleton `DistActions`, qui
  documente au passage le piège du chemin : l'étape est **configurée** sous le nom `census` et
  **journalisée** sous `recensement`.
- Constantes de classe (`__all__`, `__unfiled__`) exposées par le backend au lieu d'être écrites
  en dur huit fois dans le QML.
- Code mort retiré : `stageMinimize`, `quit`/`quitRequested`, `Stage.kept_names`,
  `RowsModel.rows`, `switchDemo`, quatre rôles de modèle jamais liés, onze clés de traduction, et
  deux imports QML inutilisés.

### Ajouté

- **`tests/test_gui_qml.py` — la scène QML est enfin testée.** Rien ne chargeait ces 3 200 lignes :
  `QQmlApplicationEngine` signale une liaison cassée par un avertissement puis continue avec un
  contrôle vide. Le test charge `Main.qml`, visite chaque onglet des deux modes, ouvre la fenêtre
  batch, démarre l'application entière, et **échoue au premier avertissement**. Comme le bug du
  sélecteur de démo n'en produisait aucun, il affirme séparément qu'un sélecteur peuplé affiche
  quelque chose — vérifié en réintroduisant le bug.
- **`pyside6-qmllint` en CI**, seule la catégorie `unqualified` désactivée (les *context
  properties* sont par construction impossibles à qualifier, et pèsent ~400 des ~420
  signalements). Les vingt autres sont corrigés : chaînes `parent.parent`, tailles posées sur des
  enfants de layout, appel de méthode sur un `currentItem` non typé.
- **Le test i18n couvre les messages d'état émis**, pas seulement les libellés du QML : toute clé
  émissible doit exister dans les deux langues **et** recevoir les placeholders que sa chaîne
  attend.
- Couverture des chemins destructeurs, jusque-là à 0 % : écriture du plan, export, dépôt de
  fichier, et toutes les mutations du registre. Couverture du paquet `gui` : **72 → 82 %**.

### Outillage

- **`configure_identity()`** — les quatre appels qui nomment l'application à Qt sont extraits et
  partagés entre `run()` et les tests. `QSettings`, donc le bloc `Settings` qui persiste
  géométrie, langue et thème, refuse de s'initialiser sans eux : le harnais de test les omettait
  et la scène partait avec deux avertissements **sous Linux uniquement** — macOS retombe sur un
  plist sans prévenir. Comportement de l'app livrée inchangé, elle les posait déjà.
- Les étapes CI qui dépendent d'un glob shell s'exécutent sous **bash** sur les trois OS : la
  console Windows par défaut est PowerShell, qui n'étend pas `*.qml` et transmettait le littéral.

## [3.0.0-rc.3] - 2026-09-10

**Intégration visuelle de l'IHM native.** Le portage Qt Quick avait gardé les contrôles bruts du
style `Basic` : ils peignent avec la palette **système**, quand tout le reste de la fenêtre peint
avec les tokens du thème. Cette version les remplace, et remet d'aplomb la table du parc.

### Corrigé

- **Le filtre du parc recouvrait le libellé « Nom ».** La cellule d'en-tête n'avait aucune largeur
  implicite — 0 px, son texte débordant sous le champ placé 8 px plus loin. Elle se dimensionne
  désormais sur son libellé, ce qui vaut aussi pour les traductions plus longues.
- **Champs, cases à cocher, listes déroulantes et barres de défilement ignoraient le thème.**
  Aucune palette Qt n'étant posée, ils restaient **clairs en thème sombre** — cases blanches sur
  carte sombre, listes déroulantes étrangères au reste — avec des angles droits, un anneau de
  focus bleu système et des hauteurs qui ne s'alignaient pas sur les boutons. Quatre composants
  reprennent les tokens (`AppTextField`, `AppCheckBox`, `AppComboBox`, `AppScrollBar`) : dix-sept
  usages basculés, plus aucun contrôle brut ne subsiste.
- **Filtrer effaçait la sélection du parc.** Chaque frappe vidait la sélection et faisait
  disparaître la barre d'actions groupées. La sélection est désormais **élaguée** : seules les
  calculatrices sorties du registre la quittent, le compteur ne totalise que les lignes visibles
  et « tout sélectionner » n'agit que sur elles — la sémantique de la table web.
- **Le champ de filtre ignorait une remise à zéro venue de l'application** : sa liaison mourait à
  la première frappe. Elle est réaffirmée tant que le champ n'a pas le focus.

### Ajouté

- **Noms accessibles** sur le filtre du parc, la case « tout sélectionner » et le menu « Déplacer
  vers » — les clés existaient déjà dans le dictionnaire partagé, seule l'IHM web les utilisait.

### Modifié

- Rail des classes élargi à **280 px** (marges 16) et calculatrice du panneau latéral ramenée à
  150 px, pour que les noms de classe longs cessent d'être tronqués.

## [3.0.0-rc.2] - 2026-09-07

**Canal figé pour anciens systèmes** (troisième canal de distribution). Le canal actif reste sur
les dernières versions d'outillage ; celui-ci gèle le sien pour garder les vieux postes.

### Ajouté

- **Troisième canal de distribution** (`NumWorks-Updater-legacy-…`, x86_64) : l'IHM web compilée
  avec un **outillage volontairement épinglé**, pour les postes que le canal actif laisse derrière
  — **macOS 10.12** (Sierra), **glibc 2.17** (CentOS 7, Ubuntu 14.04+), **Windows 8.1**. C'est le
  **même code** que le canal actif : pas une vieille version de l'app, mais la version courante
  bâtie pour de vieux systèmes — le parc ancien continue donc de recevoir le catalogue à jour.
  Épingles, politique de gel et recette :
  [`docs/05-packaging-ui/legacy-channel.md`](docs/05-packaging-ui/legacy-channel.md).
- **`nwupdater.tools.binary_floor`** — lit le plancher système **dans les octets livrés** :
  Mach-O (`LC_VERSION_MIN_MACOSX` / `LC_BUILD_VERSION`, chaque tranche d'un binaire universel),
  symboles `GLIBC_x.y` importés par un ELF, en-tête optionnel PE. La CI s'en sert comme barrière :
  une montée d'outillage qui remonte un plancher **fait échouer** le canal figé au lieu de livrer
  une promesse que le binaire ne tient pas. Utilisable sur un zip téléchargé.
- `NWUPDATER_MAC_MIN` pilote le `LSMinimumSystemVersion` du bundle macOS (défaut `10.13`), pour
  que le plist suive le bootloader au lieu d'enfermer l'utilisateur dehors.

### Corrigé

- **Le plancher macOS annoncé était faux.** La doc affirmait que le binaire web n'avait « aucun
  plancher système » ; mesure faite, le **bootloader PyInstaller publié est bâti à 10.13**, et
  c'est lui — pas le CPython embarqué, qui accepte 10.9 — qui interdisait les Mac en 10.12. Le
  canal figé le recompile à 10.12 ; l'étude de faisabilité est corrigée avec les chiffres mesurés
  (Linux : `GLIBC_2.34` aujourd'hui, pas « aucun plancher »).

## [3.0.0-rc.1] - 2026-09-02

**IHM native embarquée** (Lot 7). Le cœur est inchangé : la fenêtre pilote `Session` **dans le
processus**, sans serveur HTTP. L'IHM web reste livrée — c'est désormais le **canal de
compatibilité** pour les postes que les roues Qt excluent.

### Ajouté

- **`nwupdater gui`** — fenêtre **Qt Quick** (extra `pip install 'nwupdater[gui]'`,
  PySide6-Essentials ; QtWebEngine n'est pas utilisé). Le design system de la V2 est conservé
  (23 tokens, thème clair/sombre) ; c'est la *chrome* et les *comportements* qui deviennent natifs.
- **Progression réelle du flash** : `Session.install_firmware(progress=…)` expose le callback de
  `Installer` qui existait déjà et que la couche HTTP ne pouvait pas exploiter (pas de canal de
  streaming). La barre affiche les octets écrits puis vérifiés.
- **Gestes du bureau** : glisser-déposer entrant *et sortant* (traîner une app vers le Finder /
  l'Explorateur pour l'exporter), Maj-clic et ⌘/Ctrl-clic pour la sélection de plage, ⌘A,
  `Suppr`, `F2`, ⌘Z, menus natifs (⌘1 / ⌘2 pour le mode), dialogues de fichiers natifs,
  géométrie de fenêtre, langue et thème mémorisés.
- **Mode classe complet** : rail des classes avec renommage en place et dépôt de calculatrices,
  suppression de classe à **3 issues**, barre de lot, filtre par nom, chaîne d'actions cliquable,
  panneaux conditionnels, cache firmware, et le **kiosque batch en fenêtre séparée** (projetable
  sur un 2ᵉ écran pendant qu'on travaille dans la fenêtre principale).
- **Tests** : `tests/test_gui_pure.py` (plan d'écriture, staging, projections — **sans Qt**),
  `test_gui_i18n.py` (parité FR/EN, clés QML, placeholders), `test_gui_qt.py` (modèles, jobs,
  backend, en `offscreen`). 85 tests ajoutés, couverture 93–100 % sur les modules purs.
- **App native publiée par architecture**, comme l'app navigateur : macOS arm64 et x86_64,
  Linux x86_64, Windows x86_64. Le nom **sans** `native` reste le canal de compatibilité — c'est
  le téléchargement par défaut du site, celui qui n'a aucun plancher système. Deux absences
  assumées et nommées : Windows-sur-ARM (pas de runner hébergé) et **Linux arm64 en natif**, où
  la suite passe puis l'interpréteur abandonne à la finalisation (bug de démontage
  PySide6/shiboken sur aarch64) — cette cible reste couverte par l'app navigateur.
- **`packaging/nwupdater-gui.spec`** — app native empaquetée. Qt élagué (126 → 116 Mo sur disque,
  40 → 38 Mo zippés, macOS arm64) ; bibliothèques Qt laissées **séparées et remplaçables** sur les
  trois OS, comme la LGPL le demande.

### Modifié

- **Architecture** : toute la logique décidable sans fenêtre vit hors de Qt et est testée là —
  `gui/plan.py` (plan d'écriture), `workshop.py`, `roster.py`, `format.py`. `gui/backend.py` n'est
  qu'un adaptateur Qt. Le plan mémoire ne dépend plus d'un navigateur pour être vérifié.
- **Réordonnancement des apps** : les flèches parcourent la région **réinscriptible** en sautant
  les slots figés, au lieu de refuser le déplacement quand le voisin immédiat est figé. Aligné sur
  la règle de l'atelier web, donc un plan construit dans l'une ou l'autre IHM écrit les mêmes
  octets.
- **RAM** : 206 → 194 Mo (individuel), 203 → 188 Mo (classe) — panneaux et fenêtre batch
  construits à la demande, icônes d'apps décodées non retenues. Le plancher reste Qt
  (~149 Mo pour une fenêtre vide).

### Corrigé

- Un `QRunnable` en `autoDelete` détruisait son objet de signaux **avant** que Qt ne livre la
  complétion : l'appel réussissait en silence, l'IHM restait « occupée » indéfiniment et le
  changement de calculatrice virtuelle paraissait sans effet.
- Le commutateur Individuel/Classe semblait inerte : `Policy` porte `classroom`, pas `mode`, et un
  `getattr(..., "individual")` par defaut masquait l'erreur.
- Un rôle de modèle nommé `model` (et un autre nommé `id`) : ces noms sont réservés dans un
  *delegate* QML, et la collision vidait **tous** les autres rôles de la ligne.
- Zone morte en mode classe : un `StackLayout` sans enfant conservait son `fillHeight` et
  réclamait la moitié de la fenêtre.
- Récursion du moteur de layout (deux colonnes en `Layout.preferredWidth: 1`) et boucle de
  liaison dans la barre mémoire — les deux se manifestaient en **segfault sans message**.
- **`GET /api/device/name` renvoyait 500 quand aucune calculatrice n'est connectée**, alors que
  `/api/identity` traite le même état comme normal. Toute lecture encore en vol au moment d'un
  débranchement remontait donc une erreur serveur dans la console de la page — d'où un test d'IHM
  web intermittent (antérieur à cette version). Les deux lectures se comportent désormais pareil.
- **Le site proposait le binaire natif aux visiteurs Windows** : le sélecteur prenait la
  première correspondance, et `…-native-windows…` trie avant `…-windows…`. Il exclut désormais
  explicitement le natif — le bouton de téléchargement doit toujours pointer vers le canal sans
  plancher système. Au passage, Linux recevait l'arm64 pour tout le monde (défaut antérieur) :
  l'architecture préférée est maintenant explicite par OS.
- `RowsModel.data()` levait une exception à travers un appel virtuel C++, que Qt ne peut pas
  dérouler ; la scène mourait plus tard, ailleurs.

## [2.0.0] - 2026-07-27

Version **stable** de la lignée 2.0.0 (promotion de la rc.7). Faits marquants depuis la 1.x :

- **Installer une app `.nwa` distribuée sans Node** — linker pur-Python + runtime EADK *clean-room*
  (aucun octet NumWorks redistribué), **validé sur N0120 réelle** ; délégation `nwlink` en repli.
- **Binaires plus légers et publiés par architecture** : macOS **arm64 / x86_64** (build natif par
  arch), Linux **x86_64 / arm64**, Windows.
- **Atelier apps/scripts fiabilisé** : synchro UI systématique, **zéro doublon**, occupation mémoire
  en secteurs, vrai feedback de suppression — en mode **Individuel et Classe**.

## [2.0.0-rc.7] - 2026-07-27

### Modifié (packaging — cibles Linux différenciées)

- **Linux publié par architecture** : `NumWorks-Updater-linux-x86_64.zip` (x64) **et**
  `NumWorks-Updater-linux-arm64.zip` (aarch64, ex. Raspberry Pi), au lieu d'un seul `-linux.zip`.
  L'arm64 est buildé nativement sur le runner hébergé `ubuntu-24.04-arm` (gratuit pour ce dépôt
  public). Pas de cible 32 bits : GitHub n'offre aucun runner 32 bits et l'audience i686/armhf est
  négligeable. (Contenu applicatif identique à rc.6.)

## [2.0.0-rc.6] - 2026-07-27

### Corrigé (synchro UI + doublons apps/scripts, Individuel **et** Classe)

- **Plus de doublon à l'installation** (ex. « Tetris » installé deux fois). Un nom d'app/script est
  désormais **unique** : `AppManager.push` refuse un nom déjà présent (invariant device), l'atelier
  bloque l'ajout d'un nom déjà présent (sauf si l'ancien est planifié pour effacement → autorisé pour
  *remplacer* dans la même écriture), et `set_scripts` déduplique. Le drop de fichier stage désormais
  sous le **vrai** nom de l'app (lu dans le `.nwa`), pas le nom de fichier — c'est ce décalage de nom
  qui laissait passer le doublon.
- **UI toujours resynchronisée** après Écrire, même en cas d'échec partiel : `refreshLists()` passe
  dans un `finally`. Corrige l'occupation mémoire figée et l'étiquette **NEW** qui restait collée
  (elles restaient bloquées quand une étape d'écriture levait et sautait la resync).
- **Occupation mémoire des apps** comptée en **secteurs 64 Kio** (comme l'alloue le device), au lieu
  des octets bruts — la barre ne sous-estime plus l'espace et un plan affiché « ça rentre » rentre
  vraiment.
- **Suppression : vrai feedback** — les cartes supprimées s'animent pendant l'écriture et le toast de
  fin distingue « n installé(s) » / « n supprimé(s) » / mixte. **Suppression multiple** en une seule
  réécriture de région (`/api/apps/uninstall {names:[...]}` → `AppManager.uninstall_many`).
- Correctifs appliqués aux **deux modes** (état device partagé) ; le batch Classe reste idempotent
  (« déjà installé » = saut, pas d'erreur).

## [2.0.0-rc.5] - 2026-07-27

### Corrigé (app macOS ne se lançait pas)

- **macOS : « Could not load PyInstaller's embedded PKG archive » au lancement** (rc.4, testé sur
  Mac Intel). Cause : rc.4 buildait un binaire universel2 puis le **découpait par arch a posteriori**
  (`ditto --arch`), ce qui reconstruit le Mach-O et **perd l'archive PKG** que PyInstaller ajoute en
  overlay à la fin de l'exécutable. Correctif : **un build PyInstaller natif par architecture**
  (`NWUPDATER_MAC_ARCH=arm64|x86_64`) — l'overlay reste intact et PyInstaller signe chaque app.
  Vérifié en local : arm64 (natif) et x86_64 (sous Rosetta) démarrent et servent l'UI. Linux/Windows
  (mono-fichier, jamais découpés) n'étaient pas affectés.

## [2.0.0-rc.4] - 2026-07-27

### Ajouté (linker `.nwa` pur-Python — sans Node)

- **Installer une app distribuée (`.nwa` = ELF relocalisable) sans Node/npm** via un linker
  **pur-Python** (`formats/nwa_linker.py`) + un **runtime EADK clean-room** que nous écrivons
  (`formats/eadk_runtime.s`, embarqué en pur-Python dans `formats/_eadk_runtime.py` — aucun
  toolchain requis à l'exécution). Garbage-collection des sections (`--gc-sections`), relocations
  ARM `REL` (ABS32/REL32/THM_CALL/THM_JUMP24/PREL31/MOVW/MOVT/TARGET1), garde de dépassement
  flash/RAM. `AppManager.push` l'essaie d'abord ; **repli automatique** sur la délégation `nwlink`
  (`NWUPDATER_LINKER=nwlink|pure` pour forcer). Aucun octet NumWorks redistribué (l'ABI `svc` sont
  des faits ; le runtime est notre code MIT). **Validé sur N0120 réelle : Tetris s'installe et se
  lance** (en-tête AppInfo par ailleurs identique à `nwlink`). Retirable d'un bloc si NumWorks le
  demande. Voir `docs/04-third-party-apps/nwlink-port-plan.md` + `docs/07-contributing/05-linker-nwa-pur-python.md`.

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
