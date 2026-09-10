# Zoning V2 → composants V3 : ce qui rapproche du desktop, et ce que ça coûte

> Suite de [`native-ui-feasibility.md`](native-ui-feasibility.md), qui tranchait le *toolkit*
> (QML / Quick Controls, PySide6-Essentials). Ce document descend d'un cran : **zone par zone**,
> qu'est-ce qui devient un vrai composant desktop, et l'addition sur trois axes — **taille**
> (binaire *et* RAM), **gain d'intuitivité**, **perte de convivialité**.

## 0. Le constat qui commande tout le reste

La V2 **dessine une fenêtre à l'intérieur d'une fenêtre**. En relisant le zoning :

```
.window   max-width:1140px; margin:0 auto      → un cadre d'application centré, factice
.toolbar  height:54px                          → une barre de titre dessinée en HTML
.statusbar height:30px                         → une barre d'état dessinée en HTML
#quit-btn                                      → un bouton « Quitter » parce qu'il n'y a pas de croix
#batch-overlay  position:absolute; z-index:30  → une modale parce qu'il n'y a pas de 2e fenêtre
#src-pop        position:absolute              → un popover parce qu'il n'y a pas de menu natif
#toast          position:fixed; bottom:26px    → une notification parce qu'il n'y a pas de Centre de notifications
```

Sept zones sur dix sont des **substituts** de choses que l'OS fournit gratuitement. La première
optimisation V3 n'est donc pas d'ajouter des composants : c'est d'en **supprimer**. C'est aussi
pour ça que le portage rapproche du desktop « en creux » — on retire un décor, on ne le refait pas.

Deuxième constat structurel : `renderAll()` reconstruit le rail, le panneau système, l'atelier et
le parc par **`innerHTML`** (27 affectations dans `app.js`), et remet à jour ~20 `textContent`
d'i18n à la main. Conséquence concrète : **toute** notification d'état (branchement, débranchement,
changement de mode, changement de langue, fin d'écriture) **fait perdre le défilement et le focus**
dans les panneaux. En QML, un `ListView` sur un modèle ne réécrit que les lignes qui changent et
les libellés se re-traduisent par liaison. Ce n'est pas une amélioration cosmétique : c'est la
disparition d'une classe entière de friction.

## 1. Correspondance zone par zone

| # | Zone V2 | Rôle actuel | Composant V3 | Nature du changement |
|---|---|---|---|---|
| **Z0** | `.window` 1140px centré | cadre factice | **la fenêtre OS** (`ApplicationWindow`) redimensionnable, géométrie mémorisée (`Qt.labs.settings`) | **suppression** |
| **Z1** | `.toolbar` 54px | marque, Individuel/Classe, FR/EN, Quitter | barre d'outils applicative **allégée** (mode seul) + **`Qt.labs.platform.MenuBar`** natif pour Quitter / Langue / Préférences ; titre unifié macOS | **suppression partielle + natif** |
| **Z2** | `.rail` 250px fixe | 3 variantes : appareil / classes / « aucun appareil » | **`SplitView`** : redimensionnable, repliable, largeur mémorisée | enrichissement |
| **Z3** | `.tabbar` | onglets **+** actions (`#btn-batch`, `#btn-delclass`) mélangées | `TabBar` pour la navigation seule ; les deux actions descendent dans une **barre d'action contextuelle** du panneau | **correction d'anti-pattern** |
| **Z4** | `.panes` (5 × `position:absolute`) | un seul `.on`, réécrits par `innerHTML` | **`StackLayout`** de vues persistantes sur modèles | **gain structurel** (état conservé) |
| Z4a | `pane-system` (3 `.card2`) | flash / compte / classe | 3 `Frame` empilés, inchangé | quasi 1:1 |
| Z4b | `pane-apps` / `pane-scripts` `.wk` | membar + `.cols2` + dropzone + `.wplan` | 2 `ListView` + `Rectangle` segmenté + `DropArea` **+ glisser-déposer sortant vers le Finder/Explorateur** | enrichissement fort |
| Z4c | `pane-parc` | table roster, cases à cocher, corbeille au survol | **`TableView`** : tri par colonne, Maj/Ctrl-clic, `Suppr`, `F2`, colonnes redimensionnables | enrichissement fort |
| Z4d | `pane-dist` | config de distribution | formulaire, inchangé | 1:1 |
| **Z5** | `#batch-overlay` z-30 | kiosque plein cadre | **2ᵉ fenêtre** (plein écran possible sur un 2ᵉ écran) + progression Dock/barre des tâches | changement de nature |
| **Z6** | `.statusbar` 30px | état + disclaimer | `Qt.labs.platform` / bandeau bas — **conservée** (cf. §4) | 1:1 |
| **Z7** | `#src-pop` | popover « Sources » | `Menu` natif ancré | natif |
| **Z8** | `#toast` | retour transitoire | statusbar **+** notification OS pour le seul cas « terminé alors que la fenêtre est en arrière-plan » | à encadrer (cf. §4) |
| **Z9** | `.nodev` / `.rail-nodev` | états vides « branchez une calculatrice » | même écran, mais la détection à chaud devient un `QTimer` | 1:1 |

## 2. Les optimisations, chiffrées sur les trois axes

Notation : **Taille** = effet sur le zip et la RAM · **Intuitivité** = ce que l'utilisateur gagne ·
**Convivialité** = ce qu'il perd. Classées par rapport gain/perte décroissant.

### À prendre sans réserve

| # | Optimisation | Taille | Gain d'intuitivité | Perte |
|---|---|---|---|---|
| 1 | **Vues persistantes sur modèles** (Z4) au lieu de `innerHTML` | **−** (supprime 620 l de rendu string) | le défilement, le focus et la sélection **survivent** à un branchement, un changement de mode ou une fin d'écriture. Aujourd'hui tout saute | aucune |
| 2 | **Progression déterminée** pendant le flash + **dans le Dock / la barre des tâches** (Z4a, Z5) | **0** (`Installer(progress=…)` existe déjà et n'est pas exploité) | on voit où en est l'écriture, et on peut passer à autre chose sans perdre le suivi. Aujourd'hui : indéterminé, fenêtre au premier plan obligatoire | aucune |
| 3 | **Glisser-déposer sortant** : traîner une app hors de la fenêtre vers le Finder pour l'exporter (Z4b) | **0** | remplace le petit bouton d'export de chaque ligne par le geste attendu ; l'entrant (déposer un `.nwa`) marche déjà | affordance invisible → **garder le bouton en doublon** |
| 4 | **Fenêtre OS redimensionnable + géométrie mémorisée** (Z0) | **−1 Mo** de CSS/chrome factice ; `Qt.labs.settings` **< 1 Mo** | on retrouve sa fenêtre où on l'a laissée ; deux fenêtres côte à côte deviennent possibles | le 1140px centré était un **choix de lisibilité** — il faut le réintroduire comme `Layout.maximumWidth` interne, sinon l'atelier s'étale sur un 34" |
| 5 | **Rail en `SplitView`** repliable (Z2) | **0** | on élargit pour lire un nom de classe long, on replie pour l'atelier | un rail replié = « où est passée ma calculatrice ? » → **mémoriser, et ne jamais replier par défaut** |
| 6 | **Sortir les actions de la barre d'onglets** (Z3) | **0** | « Mode batch » et la corbeille cessent d'être des faux onglets ; navigation et commandes se distinguent | aucune, à condition de ne pas les enterrer dans un menu |
| 7 | **Table roster native** (Z4c) : tri colonne, Maj/Ctrl-clic, `Suppr`, `F2`, `Ctrl+A` | **0** | sélectionner 12 postes prend un Maj-clic au lieu de 12 clics ; trier par firmware devient possible | les cases à cocher restent nécessaires pour qui ne connaît pas Maj-clic → **les deux, pas l'un ou l'autre** |
| 8 | **Vrai Undo clavier** (Z4b) | **0** (`pushHist`/`undoStage` existent) | `Ctrl/Cmd+Z` fait ce qu'il fait partout ailleurs | aucune (le bouton Annuler reste) |

### À prendre avec garde-fou

| # | Optimisation | Taille | Gain d'intuitivité | Perte |
|---|---|---|---|---|
| 9 | **Menu natif** (`Qt.labs.platform.MenuBar`) : Fichier / Édition / Appareil / Aide (Z1) | **< 1 Mo** | conforme à l'OS, notamment macOS où l'absence de barre de menus se remarque ; loge Quitter, Préférences, À propos, la langue | **la découvrabilité chute** pour un public occasionnel. Règle : **aucune action ne doit exister *uniquement* dans un menu** — le menu double l'écran, il ne le remplace pas |
| 10 | **Menus contextuels (clic droit)** partout (Z4b, Z4c) | **0** | accélère tout pour qui connaît le geste | invisible. Même règle qu'au 9 : **toujours en doublon** d'un bouton visible |
| 11 | **Batch en 2ᵉ fenêtre** (Z5) | **0** | plein écran sur le vidéoprojecteur ou un 2ᵉ écran pendant qu'on travaille dans la fenêtre principale — impossible aujourd'hui | sur un portable mono-écran, la gestion de fenêtres est une **charge** que l'overlay évitait → **garder le plein-cadre comme mode par défaut**, la fenêtre détachée en option |
| 12 | **Notification OS** en fin d'opération longue (Z8) | **< 1 Mo** (`Qt.labs.platform.SystemTrayIcon`) | on lance un flash et on part ; l'OS prévient | **les notifications se coupent** : mode Concentration, permission refusée, profil géré d'établissement — soit exactement le parc visé. **Le toast/statusbar reste la source de vérité**, la notification n'est qu'un bonus |
| 13 | **Style natif par OS** (`macOS`, `FluentWinUI3`) livré avec Quick Controls | **0** | intégration visuelle parfaite | **détruit le design system validé** (23 tokens, thème clair/sombre, iconographie). À **refuser** : garder le design pour le contenu, prendre le natif pour la *chrome* et les *comportements* |

## 3. Bilan mémoire — mesuré

> macOS 26 arm64, PySide6 6.11.1. RAM = `maxRSS` après 2,5 s sur des sondes minimales
> (fenêtre + rail + onglets + table/SVG). Le zip est la mesure PyInstaller du document précédent.

| | zip téléchargé | RAM à l'exécution |
|---|---:|---:|
| **V2** — serveur local **+** navigateur en mode application | **6,0 Mo** | **≈ 690 Mo** (serveur **27 Mo** + arbre Chromium **666 Mo** sur 6 process, profil neuf) |
| **V3** — QML / Quick Controls | **40 Mo** | **126 Mo** |
| *(pour comparaison)* Qt Widgets | 26 Mo | 173 Mo |

**Le portage inverse les deux courbes : ×6,7 sur le disque, ÷5,5 sur la RAM.** Nuance honnête :
si le navigateur de l'utilisateur est **déjà ouvert**, le coût *marginal* de la V2 n'est pas 690 Mo
mais l'onglet et son renderer, de l'ordre de 150–250 Mo — la V3 reste devant, mais de ×1,5 environ,
pas de ×5,5. Le cas « 690 Mo » est celui du **mode application** (§10 du document précédent), qui
lance une instance dédiée. Deuxième nuance : les sondes ne sont pas des charges identiques (la
sonde Widgets contient une `QTableWidget` de 30 lignes, gourmande) ; ne pas lire le 173 vs 126
comme un verdict Widgets/QML.

**Ce que coûte la « desktop-isation » elle-même : presque rien.** C'est le résultat le plus utile
de cette étude. Les briques natives dont dépendent les optimisations 9 à 12 sont déjà dans
Essentials et pèsent **moins de 1 Mo chacune** :

| Module QML | Ce qu'il apporte | Poids installé |
|---|---|---:|
| `Qt.labs.platform` | barre de menus **native**, icône de barre d'état, notifications, menus natifs | < 1 Mo |
| `QtQuick.Dialogs` | sélecteurs de fichiers/dossiers **natifs** | < 1 Mo |
| `Qt.labs.settings` | persistance de la géométrie et des préférences | < 1 Mo |

Autrement dit : **aucun besoin d'ajouter PySide6-Addons** pour obtenir menus natifs, dialogues
natifs, tray et persistance. Les 40 Mo de zip de la V3 QML couvrent **déjà** toutes les
optimisations 1 à 12.

> **Corrigé à l'implémentation.** Ce paragraphe disait « aucun besoin d'ajouter QtWidgets », et
> c'était faux pour un cas précis : la barre de menus de `Qt.labs.platform` n'est native que sur
> macOS ; ailleurs elle passe par un repli à base de widgets qui exige aussi que l'application
> soit un `QApplication`. Sans les deux, Windows et Linux (hors menu global) partaient sans
> barre de menus du tout. QtWidgets est dans les Essentials, donc déjà dans le bundle : le coût
> réel s'est révélé être **+9,2 Mo de RAM**, pas 31 Mo de disque. Voir
> [`native-ui-implementation.md`](native-ui-implementation.md) §5.

Pour mémoire, la répartition qui explique l'écart QML/Widgets : `Qt/qml` **42 Mo** +
QtQml 12 + QtQuick 15 + Controls2 2 ≈ **71 Mo installés** — c'est le prix du moteur déclaratif,
et c'est ce qui rend le design system reproductible.

## 4. La vraie perte : ce que le navigateur donnait gratuitement

Les pertes listées en §2 sont locales et se compensent. Celle-ci est transversale, et elle ne se
voit qu'après la mise en service :

| Perdu | Aujourd'hui | En V3 |
|---|---|---|
| **Zoom** `Ctrl/Cmd + +/−` | gratuit, sur toute l'interface | **à réimplémenter** (facteur d'échelle en préférence). Sans ça, c'est une régression d'accessibilité nette pour un public enseignant |
| **Impression / export PDF** `Ctrl/Cmd+P` | gratuit — imprimer la liste d'une classe marche | **à implémenter** (QtPrintSupport est dans Essentials, mais c'est du code) |
| **Sélection et copie de n'importe quel texte** | gratuite partout | seulement là où on l'a prévu (numéro de série, versions, chemins…) |
| **Pile d'accessibilité** (lecteur d'écran, contraste, réglages OS) | celle du navigateur, mature | Qt Accessible est correct mais demande de renseigner les rôles ; les `aria-label`/`role` déjà posés dans le HTML **ne se transposent pas tout seuls** |
| **Inspection / débogage** | DevTools | à remplacer par des journaux |
| **Harnais de test** | les **561 l** de `tests/test_ui_logic.py` (Playwright) | à refaire en `pytest-qt` (déjà chiffré dans l'étude précédente) |

Le premier et le deuxième points sont les plus coûteux à ignorer : ils touchent précisément la
cible « enseignant en salle de classe ». **Les budgéter dès le spike**, pas après.

## 5. Recommandation

**Prendre 1 à 8 sans discuter** : gain réel, coût nul en taille, perte nulle ou compensable. Les
optimisations 1 et 2 à elles seules justifient le portage mieux que l'argument « fenêtre native » —
elles corrigent deux frictions structurelles que la V2 ne peut pas corriger.

**Prendre 9 à 12 sous une règle unique** : *le natif double l'écran, il ne le remplace jamais.*
Menu, clic droit, raccourci, notification — chacun doit avoir son équivalent visible à l'écran.
C'est ce qui distingue « rapprocher du desktop » de « rendre l'outil expert-only », et c'est le
principal risque de convivialité d'un portage réussi par ailleurs.

**Refuser 13** (styles natifs par OS) : le design system est un actif du projet.

**Budgéter explicitement zoom + impression** (§4) dans le périmètre du spike : ce sont les deux
seules régressions que l'utilisateur remarquera immédiatement et qu'aucune optimisation de cette
liste ne compense.

## 6. Mode classe — comparatif web (V2) → natif (V3)

Audit fonction par fonction du mode classe de `server/web/app.js` (`renderParc`,
`renderClassesRail`, `renderCalcPane`, `renderDistPane`, `openBatch`) face au portage QML.

| Fonction (V2 web) | V3 natif | Écart |
|---|---|---|
| **Rail des classes** — Toutes / classes / Sans classe, icône + effectif | ✅ | — |
| Sélection d'une classe | ✅ | — |
| **Renommage en place** (double-clic → champ, Entrée/Échap) | ✅ | — |
| **Cible de dépôt** (glisser des calculatrices) | ✅ | le drag emporte **toute la sélection**, pas une ligne |
| Ajout de classe (champ + ＋) | ✅ | — |
| **Suppression de classe** (icône, désactivée sur Toutes / Sans classe) | ✅ | — |
| **Confirmation à 3 issues** (Annuler · Déplacer vers Sans classe · Supprimer les N) | ✅ | — |
| **Barre de lot** (N sélectionnées · déplacer vers… · Supprimer) | ✅ | — |
| **Filtre par nom** dans l'en-tête de colonne | ✅ | — |
| Case « tout sélectionner » | ✅ | — |
| Table : type · nom · firmware + pastille · distribution · dernier passage | ✅ | la colonne Distribution a été un `—` en dur jusqu'à la finale : `last_dist` était dans le payload, personne ne le lisait |
| Renommage de calculatrice en place | ✅ | + `F2`, `Échap` |
| Corbeille au survol de la ligne | ✅ | — |
| Ligne draggable | ✅ | — |
| — | ✅ | **ajouts desktop** : Maj-clic (plage), ⌘/Ctrl-clic, ⌘A, `Suppr` |
| **Distribution — recensement toujours visible**, libellé adaptatif selon la chaîne | ✅ | — |
| **Chaîne d'actions** numérotée, cliquable, avec flèches | ✅ | — |
| **Panneaux conditionnels** (un panneau n'apparaît que si son action est active) | ✅ | — |
| Carte **cache firmware** (entrées, « Hors-ligne prêt », Mettre à jour, TTL) | ✅ | — |
| Jeux apps/scripts : pastilles supprimables + sélecteur d'ajout | ✅ | — |
| **Mode batch** : armement par classe, attente de branchement, chaîne, journal, Stop | ✅ | **fenêtre séparée** (plein écran sur un 2ᵉ écran possible) au lieu d'un overlay |
| Batch : « Simuler » avec choix du modèle | ✅ | — |
| Batch : journal avec pastilles d'issue colorées (ok / change / erreur) | ✅ | — |
| Batch : renommage depuis le journal | ⬜ | non porté — se fait dans la table |
| Barre de confirmation affichée par-dessus **les deux** onglets classe | ✅ | — |

**Reste ouvert** : le renommage depuis le journal de batch. Tout le reste du mode classe est
au niveau de la V2, avec les gestes desktop en plus.

> **Relu avant la finale.** Ce tableau annonçait la parité à un écart près ; l'audit du code en a
> trouvé trois de plus, tous du même genre — une donnée calculée, transmise, et jamais dessinée :
> la colonne Distribution, le niveau d'API des applications, et les dates relatives (rendues en
> français quel que soit la langue). Les trois sont corrigés. Un tableau de parité rempli de
> mémoire ne vaut rien : il se relit contre le code.
