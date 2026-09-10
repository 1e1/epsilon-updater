# IHM native (V3) — implémentation

> Fenêtre native Qt Quick, pilotant le cœur **en direct**. Suite décisionnelle :
> [`native-ui-feasibility.md`](native-ui-feasibility.md) (choix du toolkit, tailles mesurées,
> matrice de compatibilité) et [`native-ui-zoning.md`](native-ui-zoning.md) (zone par zone,
> comparatif du mode classe).

## 1. Architecture

Le cœur n'a **pas** été modifié : l'IHM appelle `Session` dans le processus, sans serveur HTTP.
Disparaissent donc de ce chemin : `httpd.py`, le garde anti-CSRF/DNS-rebinding, le fichier
d'instance unique, le heartbeat et l'idle-timeout — c'est-à-dire **toute la surface réseau**.

```
qml/                Présentation. Liaisons et gestes uniquement — aucune règle ici.
backend.py          L'unique QObject. Propriétés, slots, signaux ; délègue tout.
jobs.py             Exécute un appel bloquant du cœur hors du thread graphique.
models.py           Modèles de liste mis à jour EN PLACE (défilement et focus survivent).
workshop.py         Le staging projeté en lignes            ┐  Python pur :
roster.py           Parc, classes, distribution             │  ni Qt, ni E/S,
plan.py             Le plan d'écriture mémoire              │  testés dans
format.py           Tailles et dates relatives              ┘  tests/test_gui_pure.py
i18n.py             Chaînes FR/EN, partagées avec l'IHM web.
```

**Le principe** : tout ce qui peut se décider sans fenêtre se décide **sous** `backend.py`. La
règle qui compte le plus — quels octets sont réellement réécrits — est donc testable sans Qt,
alors qu'en V2 il fallait 561 lignes de Playwright et un navigateur pour l'atteindre.

Deux règles transverses tiennent ce découpage. Toutes deux ont été enfreintes dans la première
coupe, toutes deux sont désormais tenues par un test :

- **Aucune E/S appareil sur le thread graphique — les lectures comprises.** `Backend.refresh()`
  lit tout l'inventaire dans un worker et renvoie **un** instantané ; le thread graphique se
  contente de l'affecter. La première version le faisait en ligne : la fenêtre n'apparaissait
  qu'une fois la calculatrice lue (178 ms mesurés sur appareil *virtuel*, donc sans USB) et se
  figeait à chaque sondage de branchement à chaud (71 ms). C'est 0 ms des deux côtés aujourd'hui.
- **Rien ne franchit la frontière QML déjà traduit.** Le backend émet des **clés** i18n — champs
  de ligne, messages d'état, dates relatives — et QML les rend. Une phrase formatée côté Python
  fige l'IHM dans une langue : c'est ainsi que la colonne « dernier passage » du parc restait en
  français quand l'interface était en anglais, et que la barre d'état affichait `install_ok::20.4.0`.

```
QML  ──lecture de propriétés / appels de slots──▶  Backend (QObject)
                                                     │
                                    ┌────────────────┼────────────────┐
                                    ▼                ▼                ▼
                            modules purs        JobRunner         Session
                       (plan · workshop ·   (thread worker)   (identique à la V2)
                        roster · format)                            │
                                                                    ▼ USB (virtuel en dev)
                                                              Appareil DFU
```

## 2. Ce que le natif apporte, que le web ne pouvait pas

- **Barre de progression réelle.** `Installer(progress=…)` existait déjà et n'était exploité par
  personne : la couche HTTP n'a pas de canal de streaming. Le backend y branche une barre
  déterminée écriture/vérification (`_session_firmware.install_firmware(progress=…)`).
- **État préservé.** Les modèles de liste diffèrent les lignes : même jeu de clés → `dataChanged`
  sur les seules lignes modifiées. Un branchement, un changement de mode ou une fin d'écriture ne
  font plus perdre le défilement ni le focus.
- **Gestes du bureau** : glisser-déposer entrant *et sortant*, Maj-clic / ⌘-clic / ⌘A / `Suppr` /
  `F2`, ⌘Z, menus natifs, dialogues de fichiers natifs, géométrie de fenêtre mémorisée.
- **Le batch en fenêtre séparée**, projetable sur un 2ᵉ écran pendant qu'on travaille dans la
  fenêtre principale.

## 3. Règle d'ergonomie tenue

> **Le natif double l'écran, il ne le remplace jamais.**

Chaque menu, clic droit, raccourci ou notification a son équivalent visible. Le mode
Individuel/Classe vit dans le menu **Mode** (⌘1 / ⌘2) *et* reste affiché dans la barre d'état.
Le glisser-déposer sortant double le bouton d'export, il ne le supprime pas.

## 4. Lancer

```bash
pip install 'nwupdater[gui]'      # PySide6-Essentials ; QtWebEngine n'est PAS utilisé
nwupdater gui                     # réel d'abord, sinon écran « branchez une calculatrice »
nwupdater gui --virtual n0120     # démo explicite
nwupdater gui --real --lang en
```

`nwupdater ui` (navigateur) reste disponible : c'est le **canal de compatibilité** (macOS 10.13 /
glibc 2.34, et macOS 10.12 / glibc 2.17 dans le [canal figé](legacy-channel.md)), pour les postes
que Qt exclut (cf. la matrice de l'étude de faisabilité).

## 5. Empaquetage

`packaging/nwupdater-gui.spec` construit l'app native ; `packaging/nwupdater.spec` continue de
construire l'app navigateur. Les deux sont livrées, **par architecture** :

| | Compatibilité (navigateur) | Native (Qt Quick) | Figée (anciens systèmes) |
|---|---|---|---|
| macOS | `…-macos-arm64.zip` · `…-macos-x86_64.zip` | `…-native-macos-arm64.zip` · `…-native-macos-x86_64.zip` | `…-legacy-macos-x86_64.zip` |
| Windows | `…-windows.zip` | `…-native-windows-x86_64.zip` | `…-legacy-windows-x86_64.zip` |
| Linux | `…-linux-x86_64.zip` · `…-linux-arm64.zip` | `…-native-linux-x86_64.zip` — **pas d'arm64** | `…-legacy-linux-x86_64.zip` |

Le nom **sans qualificatif est le canal de compatibilité** : c'est le téléchargement par défaut du
site, et celui dont le plancher est le plus bas des deux canaux actifs (macOS 10.13 / glibc 2.34).
`legacy` descend plus bas encore, avec un outillage épinglé
([`legacy-channel.md`](legacy-channel.md)). `native` est un choix explicite. Windows-sur-ARM
n'est pas couvert (aucun runner hébergé gratuit) ; le suffixe `-x86_64` le dit plutôt que de le
laisser deviner.

**Linux arm64 n'a pas de build natif.** La suite y passe (« 85 passed »), puis l'interpréteur
abandonne à la finalisation : `bool_dealloc: deallocating True or False — bug likely caused by a
refcount error in a C extension`, c'est-à-dire un bug de démontage de PySide6/shiboken sur
aarch64, pas dans ce code. Livrer un binaire dont la propre vérification se termine par un
abandon n'est pas signable ; et le public est mince, la roue aarch64 de PySide6 exigeant
glibc 2.39 (Ubuntu 24.04+). Linux arm64 reste couvert par l'app navigateur, qui n'a aucun
plancher. À revoir quand la roue amont cessera d'abandonner.

> Un binaire par architecture plutôt qu'un universel : c'est ce que fait déjà l'app navigateur, et
> côté natif l'écart est plus marqué encore — un bundle Qt universel2 embarque deux fois chaque
> bibliothèque.

Deux points structurants du spec :

- **Élagage Qt.** Le hook PySide6 embarque tout ce qu'il trouve. Le spec exclut les modules
  inutilisés *et* supprime leurs arbres QML et leurs bibliothèques par chemin — c'est là que
  sont les mégaoctets. QtWebEngine à lui seul en pèserait ~200.
- **Qt est LGPL.** Les bibliothèques restent des fichiers séparés et remplaçables (`COLLECT`,
  pas de *one-file*), sur les trois OS. C'est la raison pour laquelle l'app native ne se livre
  pas en fichier unique sous Windows et Linux, contrairement à l'app navigateur.
- **QtWidgets reste embarqué, pour une raison plus étroite qu'annoncé.** Le spec le gardait au
  nom du repli non natif des dialogues de fichiers ; c'est faux, ceux-ci viennent de
  `QtQuick.Dialogs` et ne demandent rien à Widgets. Ce qui l'exige, c'est la **barre de menus**
  de `Qt.labs.platform` : native sur macOS seulement, et ailleurs un repli à base de widgets qui
  réclame en plus que l'objet application soit un `QApplication`. Avec un simple
  `QGuiApplication`, Qt écrit `Qt Labs Platform requires Qt Widgets` sur la sortie d'erreur et la
  fenêtre part **sans aucune barre de menus** sous Windows et sous les bureaux Linux sans menu
  global. `gui/app.py::_application` construit donc un `QApplication` quand QtWidgets est là, et
  se dégrade proprement sinon.

  Coût mesuré du choix, même méthode et même plateforme des deux côtés (`maxRSS` à 3 s,
  offscreen) : **145,5 Mo** avec `QGuiApplication` contre **154,7 Mo** avec `QApplication`, soit
  **+9,2 Mo**. C'est le prix d'une barre de menus sur deux OS sur trois ; les 6 Mo de disque
  étaient déjà payés.

## 6. Tests

| Fichier | Portée | Dépend de Qt |
|---|---|---|
| `tests/test_gui_pure.py` | plan d'écriture, staging, projections parc/distribution, formats, compat API | non |
| `tests/test_gui_i18n.py` | parité FR/EN, toute clé utilisée en QML **et tout message d'état** existe, placeholders alignés | non |
| `tests/test_gui_qt.py` | modèles de liste, exécuteur de jobs, façade backend, chemins destructeurs | oui (`importorskip`) |
| `tests/test_gui_qml.py` | **la scène elle-même** : elle charge, sans un seul avertissement, dans les deux modes | oui (`importorskip`) |

Les tests Qt tournent en `QT_QPA_PLATFORM=offscreen` : ni écran, ni USB réel — le device virtuel,
comme partout ailleurs dans le projet. Ceux qui ne dépendent pas de Qt tournent même sans l'extra
`gui` installé, donc la règle d'écriture reste vérifiée dans une CI minimale.

`test_gui_qml.py` comble le trou le plus large du portage : **rien ne chargeait les 3 200 lignes
de QML**. `QQmlApplicationEngine` signale une liaison cassée par un *avertissement* puis continue
avec un contrôle vide, si bien qu'une faute ne se voyait qu'une fois la fenêtre ouverte. Le test
charge `Main.qml`, visite chaque onglet des deux modes, ouvre la fenêtre batch, et **échoue au
premier avertissement**. `pyside6-qmllint` complète le tableau côté statique, en CI.

Un cas mérite d'être connu : le pire bug du portage — un `textRole` posé sur un modèle de chaînes,
qui vidait le sélecteur de démo du premier écran et transmettait `undefined` au backend — ne
produisait **aucun** avertissement. Charger proprement ne suffisait donc pas ; le test affirme
séparément qu'un sélecteur non vide affiche quelque chose. (Vérifié en réintroduisant le bug :
le test tombe.)

Six régressions y sont épinglées nommément, parce qu'elles étaient toutes **silencieuses** :

1. un `QRunnable` en `autoDelete` détruit son objet de signaux avant que Qt ne livre la
   complétion — l'appel réussit sans que personne ne l'apprenne, et l'IHM reste « occupée » ;
2. `Policy` porte `classroom`, pas `mode` : lu derrière un `getattr(..., "individual")` par
   défaut, le commutateur paraissait inerte ;
3. un rôle nommé `model` (ou `id`) dans un modèle de liste : dans un *delegate* QML ces noms sont
   réservés, et la collision vide **tous** les autres rôles de la ligne ;
4. un `textRole` sur un modèle de chaînes : sélecteur muet, `undefined` transmis au slot ;
5. un message d'état passé à `Text` sans `i18n.t()` : l'utilisateur lit la clé brute ;
6. un compte de sélection recalculé d'une **seconde** façon dans la branche Maj-clic : la barre
   de lot annonçait un nombre que le tableau ne montrait pas, dès qu'un filtre était actif ;
7. `i18n.t()` est un **slot** : une liaison QML ne dépend que des *propriétés* qu'elle lit, donc
   changer de langue ne réévaluait aucune étiquette. Le commutateur ne décidait que du prochain
   lancement — 0 libellé sur 22 suivait.

La septième mérite un mot, parce qu'elle illustre à quoi sert un test de présentation : elle a été
trouvée **par** le test écrit pour vérifier la barre d'état, pas par une relecture. Personne
n'avait ouvert la fenêtre et cliqué « English » ; le docstring affirmant que ça marchait a tenu
lieu de vérification pendant tout le portage.

## 7. Grille de qualité et auto-évaluation

Pour juger la V3 autrement qu'à l'œil, une grille en deux volets. Chaque critère est **mesurable**
et son résultat est reproductible avec les commandes indiquées.

### Technique

| # | Critère | Mesure | V2 (web) | V3 (native) |
|---|---|---|---|---|
| T1 | Poids du téléchargement | zip publié, macOS arm64 | **6 Mo** | 38 Mo |
| T2 | Empreinte mémoire | `maxRSS` après 3 s | ≈ 690 Mo (serveur + navigateur dédié) | **194 Mo** |
| T3 | Surface d'attaque | ports en écoute | 1 (loopback, gardé) | **0** |
| T4 | Couverture de la logique | `pytest --cov` | logique dans `app.js`, hors couverture Python | **93–100 %** sur les modules purs, **82 %** du paquet |
| T5 | Testable sans navigateur | oui/non | non (561 l de Playwright) | **oui** (`test_gui_pure.py`, sans Qt) |
| T6 | Lint + format | `ruff check`, `ruff format --check` | vert | **vert** |
| T7 | Plancher système | glibc / macOS minimum | **aucun** | glibc 2.34 / macOS 13 |
| T8 | Taille du plus gros fichier | `wc -l` | `app.js` 1 691 l | `backend.py` 941 l · `Main.qml` **230 l** |
| T9 | La présentation est-elle vérifiée ? | scène chargée en CI, `qmllint` | — (Playwright, navigateur requis) | **oui**, 0 avertissement |
| T10 | Coût du premier rendu | temps avant que la fenêtre puisse s'afficher | — (page servie, puis `fetch`) | **0 ms** (l'inventaire arrive après) |

### Ergonomie

| # | Critère | V2 | V3 |
|---|---|---|---|
| U1 | Parité fonctionnelle | référence | **1 écart** (renommage depuis le journal batch) |
| U1b | Parité de la table parc | colonne Distribution dessinée | **dessinée** (pastilles par action, comme le web) |
| U2 | Progression d'un flash | indéterminée | **déterminée**, octets écrits puis vérifiés |
| U3 | État conservé au rafraîchissement | non (`innerHTML` complet) | **oui** (mise à jour en place) |
| U4 | Sélection multiple | cases à cocher seules | cases **+** Maj-clic, ⌘-clic, ⌘A |
| U5 | Annulation | bouton | bouton **+** ⌘Z |
| U6 | Export d'une app | bouton | bouton **+** glisser vers le Finder |
| U7 | Rien d'accessible uniquement par un menu | — | **tenu** (voir §3) |
| U8 | Parité FR/EN | testée | **testée**, placeholders compris — libellés, **messages d'état et dates relatives** |
| U8b | Changement de langue à chaud | immédiat (re-render complet) | **immédiat** (liaisons invalidées) |
| U9 | Zoom, impression | gratuits (navigateur) | **absents** — assumé, hors périmètre 3.0 |
| U10 | Barre de menus | — (menus du navigateur) | **les trois OS** (voir §5, coût mesuré) |
| U11 | Avertissement d'incompatibilité API | pastille sur l'app trop récente | **pastille**, même règle |

### Ce que la grille a fait corriger

Elle n'est pas décorative : appliquée, elle a produit des changements.

- **T4/T5 → l'architecture.** Écrire les tests a montré que la logique était piégée dans un
  `QObject` de 1 052 lignes. D'où l'extraction en modules purs, et `backend.py` retombé à 728 l.
- **T4 → un bug de portage.** Le test de réordonnancement a révélé que `▲`/`▼` refusait le
  déplacement quand le voisin immédiat était figé, là où l'atelier web **saute** les slots figés.
  Deux IHM auraient produit deux plans d'écriture différents pour le même geste.
- **T2 → la construction paresseuse.** Mesurer plutôt qu'estimer a montré que la fenêtre batch et
  les deux panneaux du mode classe étaient construits au démarrage, dans toutes les sessions.
- **U9 → un aveu.** Le zoom et l'impression étaient gratuits dans le navigateur ; ils ne le sont
  plus. C'est le prix explicite de la V3, et c'est pourquoi la V2 reste livrée.

Passée une seconde fois avant la finale, la grille a produit une deuxième série — et, ce qui
compte davantage, elle a montré que **trois de ses propres lignes étaient fausses** :

- **T9 → le trou qu'aucune ligne ne couvrait.** La grille mesurait la logique et ignorait la
  présentation. Or c'est là qu'était le pire défaut : un sélecteur muet sur le premier écran.
  D'où `test_gui_qml.py` et `qmllint` en CI.
- **T10 → une E/S là où le contrat disait l'inverse.** L'en-tête de `backend.py` affirmait
  qu'aucun appel appareil ne touchait le thread graphique. C'était vrai des écritures, faux des
  lectures : constructeur 178 ms, 71 ms par rafraîchissement, 29 ms par frappe dans le filtre du
  parc — sur appareil virtuel, donc sans USB. Tout est passé en worker.
- **U1/U8 étaient sur-déclarées.** « 1 écart de parité » en comptait trois de plus (colonne
  Distribution non dessinée, niveau d'API jamais affiché, dates relatives en français dur), et
  « parité FR/EN testée » ne testait que les libellés QML : les messages d'état s'affichaient
  crus, `install_ok::20.4.0`. Le test i18n couvre désormais aussi les messages **émis**.

La leçon se répète : une grille ne vaut que si on la relit contre le code, pas contre le
souvenir qu'on en a.

### Reproduire

```bash
pytest -q                                   # T4, T5, T6, T9, U1, U8
pytest --cov=nwupdater.gui --cov-report=term-missing tests/test_gui_*.py
ruff check src/ && ruff format --check src/ # T6
cd src/nwupdater/gui/qml && pyside6-qmllint -I . --unqualified disable *.qml   # T9
pyinstaller packaging/nwupdater-gui.spec --noconfirm && du -sm dist/*.app   # T1
```

`--unqualified disable` n'est pas un tapis sous lequel glisser la poussière : `backend` et `i18n`
arrivent en QML comme *context properties*, qui sont par construction impossibles à qualifier, et
pèsent à elles seules ~400 des ~420 signalements. Éteindre cette catégorie est ce qui rend les
vingt autres lisibles — et elles sont toutes corrigées. Les enregistrer en singletons QML les
qualifierait, mais ne paie qu'accompagné de `.qmltypes` générés : reporté après la 3.0.
