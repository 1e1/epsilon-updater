# Étude de faisabilité — IHM embarquée (piste V3)

> **Statut : étude, aucune décision prise.** Ce document chiffre le portage de l'IHM actuelle
> (page web locale ouverte dans le navigateur système) vers une **fenêtre native embarquée**,
> et compare les toolkits candidats — Qt en tête. Backlog d'origine :
> [`../00-overview/roadmap.md`](../00-overview/roadmap.md) → « Embarquer une IHM dans le binaire ».

## 1. La question, et le vrai arbitrage

L'objectif énoncé est double : **(a)** une vraie fenêtre native, plus de dépendance à un
navigateur externe ; **(b)** une compatibilité large Windows / Linux / macOS.

L'étude montre que **(a) et (b) se paient l'un contre l'autre**. Aujourd'hui l'IHM est gratuite
en taille (elle réutilise le navigateur déjà installé) et n'a **aucun plancher système côté
code** — le cœur est stdlib pur. Tout moteur de rendu embarqué apporte, au choix : beaucoup de
mégaoctets (Qt, Chromium) ou une dépendance système non empaquetable (webview de l'OS sous Linux).

> **Précision (mesurée depuis)** : « stdlib pur » vaut pour le *code*, pas pour le *binaire*. Le
> zip livré hérite des planchers de son outillage — bootloader PyInstaller en `10.13` sur macOS,
> CPython de la CI en `GLIBC_2.34` sur Linux. C'est l'objet du
> [canal figé](legacy-channel.md), qui les redescend à 10.12 et `GLIBC_2.17`.

L'arbitrage n'est donc pas « Qt ou rien » mais : **quelle promesse on garde ?**

## 2. Point de départ : l'architecture est déjà prête (bonne nouvelle)

Rien à porter côté Python. La façade `Session` ([`session.py`](../../src/nwupdater/server/session.py)
\+ 7 mixins, ≈ 1 250 lignes) est **déjà agnostique de l'IHM** : chaque méthode publique rend un
`dict` sérialisable, et [`httpd.py`](../../src/nwupdater/server/httpd.py) (483 l) n'est qu'une
couche de transport par-dessus. Une IHM native appelle `Session` **en direct**, sans HTTP.

Deux corollaires qui plaident *pour* le natif :

- **Barre de progression réelle.** `Installer(progress=…)`
  ([`install/installer.py:144`](../../src/nwupdater/install/installer.py#L144)) émet déjà
  `("write"|"verify", done, total)`. La couche HTTP **n'exploite pas** ce callback (pas de SSE ni
  de WebSocket) : la page web ne peut afficher qu'un indéterminé pendant un flash. Une IHM native
  branche le callback sur une barre de progression sans rien ajouter au cœur.
- **Surface réseau supprimée.** Le serveur loopback est aujourd'hui la seule surface d'attaque de
  l'outil (d'où le garde `_guard()` anti-CSRF / anti-DNS-rebinding, le plafond de taille des
  requêtes, le jeton d'instance). En natif, cette surface **disparaît** — avec elle
  `instance.py` (instance unique), le heartbeat `/api/ping`, l'idle-timeout et `/api/quit`.

## 3. Ce qu'il faudrait porter — inventaire mesuré

| Fichier | Lignes | Poids | Contenu |
|---|---:|---:|---|
| [`web/index.html`](../../src/nwupdater/server/web/index.html) | 617 | 51 Ko | structure + **43 Ko de CSS** (≈ 419 règles, 23 tokens de couleur utilisés 334 fois, thème clair/sombre, 15 `@media`) |
| [`web/app.js`](../../src/nwupdater/server/web/app.js) | 1 691 | 103 Ko | contrôleur + rendu |
| [`web/calc.js`](../../src/nwupdater/server/web/calc.js) | 272 | 20 Ko | générateur **SVG** des deux familles de calculatrices (3 modes : `device` / `icon` / `thumb`) |
| [`web/i18n.js`](../../src/nwupdater/server/web/i18n.js) | 494 | 25 Ko | **476 clés** FR + EN, `t(key, params)` |
| [`web/ux.html`](../../src/nwupdater/server/web/ux.html) | 493 | 40 Ko | galerie UX (outil de conception, hors produit — **à ne pas porter**) |

Découpage d'`app.js` par nature (classement par préfixe de fonction, 1 689 l sur 1 691
classées) :

| Nature | Lignes | Fonctions | Sort en cas de portage |
|---|---:|---:|---|
| contrôleur / I-O (`api`, `install*`, `commit*`, `roster*`…) | 637 | 58 | **remplacé** par des appels directs à `Session` |
| vue / rendu (`render*`, `*Row`, `*HTML`…) | 620 | 32 | **à réécrire** dans le toolkit cible |
| état / logique métier (plan mémoire, staging, drag, historique) | 287 | 43 | **à porter en Python** (récupérable, cf. §9 étape 1) |
| utilitaires (`esc`, `fmtBytes`, `toast`, `clone`…) | 145 | 45 | trivial |

**Widgets non triviaux à reproduire** : glisser-déposer sur deux axes (réordonner les apps/scripts
dans l'ordre mémoire, et déposer une calculatrice sur une classe du rail) ; barre mémoire
segmentée à 4 états (inchangé / à réécrire / nouveau / libre) ; pastilles tri-état ; table du parc
avec filtre live, sélection multiple, édition de nom en place ; zone de dépôt de fichier `.nwa` ;
toasts ; sélecteurs segmentés ; 3 animations `@keyframes` (pulse, sweep de téléchargement,
respiration du témoin USB) avec respect de `prefers-reduced-motion`.

Total **≈ 3 100 lignes de front produit** (hors `ux.html`) + 476 clés d'i18n.

## 4. Les options envisagées

**A — garder le web, embarquer un moteur de rendu** (réécriture d'IHM ≈ nulle)
- **A1** `QtWebEngine` (PySide6-**Addons**) — Chromium embarqué.
- **A2** webview du système via `pywebview` — WebView2 (Windows), WKWebView (macOS), WebKitGTK (Linux).
- **A3** CEF / Electron / Tauri — moteur ou runtime tiers, hors stack Python.

**B — réécrire l'IHM en natif** (réécriture complète du front)
- **B1** Qt **Widgets** (PySide6-**Essentials**).
- **B2** Qt **QML / Quick Controls** (PySide6-**Essentials**).
- **B3** **Tk** (stdlib, zéro dépendance).
- **B4** wxPython / Toga / Flet / Dear PyGui.

**C — ne rien porter** : lancer le navigateur déjà installé en *mode application* (fenêtre sans
barre d'adresse) — cf. §10.

## 5. Mesures de taille (faites sur ce poste)

> **Méthode.** macOS 26 arm64, PySide6 **6.11.1**, PyInstaller **6.21**, `--windowed --strip
> --target-arch arm64`, exclusions `tkinter/PIL/pytest` + modules Qt inutiles, venv propre par
> mesure. Applications-sondes minimales mais représentatives (fenêtre, rail latéral, onglets,
> table, rendu SVG, zone peinte, `QTranslator`). **Chaque sonde a été lancée : rc=0.** La
> colonne `.zip` est le `ditto -c -k` — c'est ce que l'utilisateur télécharge.

| Option | `.app` sur disque | `.zip` téléchargé | Rapport vs actuel |
|---|---:|---:|---:|
| **Actuel** (page web + navigateur) | — | **6,0 Mo** | ×1 |
| **B1** Qt Widgets (Essentials) | 73 Mo | **26 Mo** | **×4,3** |
| **B2** Qt QML / Quick (Essentials) | 125 Mo | **40 Mo** | **×6,7** |
| **A1** Qt + QtWebEngine (Addons) | 497 Mo | **177 Mo** | **×29,5** |
| **A2** pywebview (estimation) | ~35–45 Mo | ~12–18 Mo | ~×2,5 |

Notes :

- Le 6,0 Mo actuel est la mesure du dépôt lui-même (`CHANGELOG.md`, rc.5, arm64 zip).
- **A1** : `QtWebEngineCore` pèse à lui seul **217 Mo**, + `icudtl.dat` 10 Mo + les `.pak`.
  Embarquer Chromium pour afficher une page qu'un navigateur déjà installé affiche pour 6 Mo.
- **B2 coûte +52 Mo disque / +14 Mo zip vs B1** : c'est le prix du runtime QML. C'est aussi ce qui
  rend le design actuel reproductible (§7).
- **A2** est une **estimation, pas une mesure** : le build PyInstaller a échoué sur ce poste
  (`IndexError` dans `dis` — bug du **Python 3.10.0** installé ici, pas de `pywebview`). Le
  chiffre vient de la somme des paquets installés (`objc` 10 Mo + `AppKit`/`Foundation`/`Quartz`
  ≈ 6 Mo + `webview` 3 Mo + `bottle`/`proxy_tools`). **À mesurer** sur Python 3.11 (la CI) avant
  toute décision.
- Les roues PyPI compressées confirment l'ordre de grandeur sur les autres OS —
  Essentials : 77,5 Mo (win_amd64), 79,9 (linux x86_64), 79,0 (linux aarch64) ;
  Addons : 168,8 / 175,1 / 170,6.

## 6. Le point dur : la matrice de compatibilité

C'est **le** risque de l'option Qt, et il va à l'encontre exact de l'objectif (b). Les roues
PySide6 officielles portent un plancher système, et **ce plancher monte** :

| PySide6 | macOS | Linux x86_64 | Linux aarch64 | Windows |
|---|---|---|---|---|
| 6.6 – 6.7.3 | `macosx_11_0` (Big Sur) | `manylinux_2_28` (glibc 2.28) | `manylinux_2_31` | win_amd64 |
| 6.8.0 | `macosx_12_0` (Monterey) | `manylinux_2_28` | `manylinux_2_31` | win_amd64 |
| **6.8.1 – 6.9.3** | `macosx_12_0` | **`manylinux_2_28`** | **`manylinux_2_39`** | + win_arm64 (6.9) |
| **6.10 – 6.11.1** | **`macosx_13_0`** (Ventura) | **`manylinux_2_34`** | `manylinux_2_39` | win_amd64 + win_arm64 |

Traduction en parc réel :

- `manylinux_2_34` = **glibc ≥ 2.34** → Ubuntu 22.04+, Debian 12+, RHEL 9+. **Ubuntu 20.04 (glibc
  2.31) est exclu** — or c'est encore un socle courant en salle informatique.
- `macosx_13_0` = **macOS 13 Ventura minimum**. Les Mac bloqués en Monterey / Big Sur sont exclus.
- `manylinux_2_39` (aarch64) = **glibc ≥ 2.39** → Ubuntu 24.04+. **Raspberry Pi OS Bookworm (glibc
  2.36) est exclu** — régression nette : le binaire actuel y tourne.
- PySide6 6.11 exige aussi **Python 3.10 – 3.14** (la CI est en 3.11 ✔).

Le binaire actuel, stdlib pur, n'a **aucun de ces planchers Qt**. Il tourne partout où un Python
empaquetable tourne — et la cible affichée du projet, ce sont précisément les **postes anciens et
verrouillés**. Deux sorties possibles, aucune indolore :

1. **Épingler PySide6 6.9.3** (dernière version en glibc 2.28 / macOS 12) — regagne un large parc
   Linux et Mac, mais **contredit la règle projet « rester sur les versions récentes »** et laisse
   quand même l'aarch64 en glibc 2.39.
2. **Deux canaux de distribution** : binaire natif « moderne » + binaire web actuel « compatibilité ».
   Coûte une ligne de CI et une ligne de doc, garde les deux promesses. *(Piste privilégiée, §9.)*

**Suite (livrée)** : c'est la piste 2 qui a été retenue, avec un **troisième** canal derrière
elle. Deux mesures ont corrigé le tableau ci-dessus une fois les binaires ouverts :

- les **tags de roues mentent** — PySide6 6.5.2, taguée `macosx_10_9_universal2`, embarque un
  `QtCore` en `minos 11.0`. Aucun Qt 6 ne descend sous **macOS 11**, quelle que soit l'épingle,
  donc la piste 1 rapporte moins qu'annoncé ;
- le binaire *web* portait lui aussi un plancher, hérité de son outillage (macOS 10.13, glibc
  2.34). Le [**canal figé**](legacy-channel.md) le redescend à **10.12 / `GLIBC_2.17`** avec un
  outillage épinglé, et vérifie le résultat sur les octets livrés.

## 7. Fidélité visuelle atteignable

Le design actuel est un système maison, pas un thème d'OS — c'est ce qui rend le choix du toolkit
déterminant.

| Option | Fidélité estimée | Pourquoi |
|---|---|---|
| **A1 / A2** (web embarqué) | **100 %** | c'est la même page |
| **B2** QML / Quick | **80–90 %** | `Rectangle` (radius, gradient), `MultiEffect` (ombres, Qt 6.5+), `Behavior`/`NumberAnimation` (les 3 keyframes), `Shape`/`Path`, `DragHandler`/`DropArea`, `ListView`/`TableView`, tokens = propriétés liées, `@media` = liaisons sur `width`. Les 23 tokens et le clair/sombre se transposent directement. |
| **B1** Qt Widgets | **60–70 %** | QSS ne couvre ni les ombres douces, ni `color-mix`, ni les transitions ; il faudrait beaucoup de `paintEvent` custom, pour un résultat plus rigide et plus de code que B2 |
| **B3** Tk | **≪ 50 %** | pas de radius, pas d'ombre, pas d'animation, pas de HiDPI correct. **Régression visible** — à écarter |

**Bon point sur le rendu des calculatrices** : `calc.js` **génère des chaînes SVG**, il ne dessine
pas. `QtSvg` (dans Essentials) rend ce SVG tel quel. Il suffit donc de porter le **générateur**
(272 l JS → ≈ 300 l Python), et le JS existant sert d'**oracle de test** — on peut comparer les
sorties octet à octet via le harnais Playwright déjà en place.

## 8. Autres frottements techniques

| Sujet | Impact |
|---|---|
| **Threading** | Toutes les méthodes de `Session` sont **bloquantes** et sérialisées par `_io_lock`. En Qt, chaque appel qui touche l'USB doit passer en `QThread`/worker, sinon la fenêtre gèle pendant un flash. Environ 60 points d'appel à envelopper — mécanique, mais à ne pas sous-estimer. |
| **Hotplug** | Le poll `fetch` de 4 s devient un `QTimer` → plus simple. |
| **Tests** | Les **561 lignes** de [`tests/test_ui_logic.py`](../../tests/test_ui_logic.py) (Playwright, qui teste le planificateur mémoire et `jsStr` dans un vrai moteur JS) tombent. Remplacement : `pytest-qt` pour l'interaction, **et surtout** la logique de plan extraite en Python devient testable en pytest pur — un **gain** net de testabilité. |
| **Fichiers** | La zone de dépôt et l'aller-retour base64 de `POST /api/install/app-local` disparaissent au profit de `QFileDialog` / `QDropEvent` → moins de code, plafond de taille de requête inutile. |
| **i18n** | 476 clés, dict plat avec interpolation `{name}`. **Recommandé : extraire en JSON partagé** consommé par le web *et* le natif (`t()` Python de 10 lignes) — zéro perte, l'invariant « même ordre de clés FR/EN » testé par `tests/test_i18n.py` reste valable. Qt Linguist (`.ts`/`lupdate`) apporterait de l'outillage mais imposerait une conversion et un second format ; **non retenu**. |
| **Licence** | Qt et PySide6 sont **LGPL-3.0** (ou GPL, ou commercial). Un projet MIT peut s'y lier dynamiquement, mais l'esprit du §4 de la LGPL demande que l'utilisateur puisse **remplacer la bibliothèque** → livrer en **one-dir** (Qt en `.dll`/`.so`/`.dylib` séparés) + notice LGPL + offre de source. macOS est **déjà** en `COLLECT`/`BUNDLE` ✔ ; **Windows et Linux sont en one-file** ([`nwupdater.spec:87`](../../packaging/nwupdater.spec#L87)) et devraient passer en one-dir → on perd le « un seul fichier à double-cliquer » sur ces deux OS. À trancher, et à faire relire — ce paragraphe n'est pas un avis juridique. `pywebview` est **BSD-3** : aucun frottement. |
| **Dépendance système (A2)** | Windows : WebView2 est quasi généralisé (préinstallé Win 11, poussé par Edge sur Win 10) **mais pas garanti** sur images LTSC / postes figés — soit exactement la cible « poste scolaire verrouillé ». Linux : `pywebview` a besoin de **PyGObject + WebKitGTK 4.1** (`gir1.2-webkit2-4.1`), non empaquetables en pratique → **la promesse « rien à installer » tombe sous Linux**. C'est ce qui disqualifie A2 comme binaire principal. |
| **A3** | Electron/Tauri = second écosystème (Node ou Rust) dans un projet Python, et Tauri sous Linux retombe sur la webview système (même problème qu'A2). Le projet vient au contraire de **supprimer** sa dépendance Node en portant `nwlink` en Python — ajouter Node/Rust irait à l'envers. **Écarté.** |
| **B4** | wxPython : pas de roue Linux universelle (build source fréquent). Toga : trop jeune pour ce niveau de design. Flet : embarque Flutter (poids comparable à A1) et un modèle client/serveur. Dear PyGui : rendu jeu, incompatible avec ce design. **Écartés.** |

## 9. Recommandation

**Écarter A1 (QtWebEngine).** 177 Mo de téléchargement, ×29,5, pour **zéro gain fonctionnel** :
la même page, dans un Chromium qu'on transporte au lieu d'utiliser celui du poste — et le serveur
HTTP local reste nécessaire. Mauvais rapport qualité/prix, et le plancher système de Qt en prime.

**Retenir B2 (QML / Quick Controls, PySide6-Essentials) comme cible V3, en canal séparé** — la V2
web restant le **canal de compatibilité**. C'est le seul chemin natif qui reproduit ce design pour
un coût de taille acceptable (40 Mo zip), le seul qui bénéficie du rendu SVG déjà écrit, et il ne
demande **aucune modification du cœur**.

**Garder A2 (pywebview) comme extra opt-in**, pas comme binaire : `pip install nwupdater[gui]`
donne une fenêtre native à qui a déjà les dépendances système, pour ~3 jours de travail.

### Plan de sortie proposé (si go)

**Étape 0 — spike, 2–3 j, décisif.** Une fenêtre QML affichant l'onglet *Système* + la
calculatrice SVG, lisant `Session` en direct, **buildée par la CI sur les 5 cibles**. Critères
go/no-go chiffrés à fixer d'avance : zip ≤ 45 Mo par cible, démarrage à froid ≤ 2 s, les 5 builds
verts, rendu conforme à la capture de référence. **Ne rien engager avant ce verdict.**

Les étapes 1 à 3 ont de la valeur **même si le spike dit non** — elles améliorent la V2 web :

1. **Extraire la logique de plan/staging** d'`app.js` (les 287 l « état/logique ») vers
   `ui/plan.py`, testée en pytest pur. La page web consomme ensuite le même plan → une seule
   source de vérité pour le calcul mémoire. *3–5 j.*
2. **Porter `calc.js` → `ui/calc_svg.py`** (sortie SVG identique, comparable octet à octet contre
   le JS via le harnais Playwright existant). *2–3 j.*
3. **i18n en JSON partagé** web + natif. *1 j.*
4. **Écrans QML**, dans l'ordre de difficulté croissante : Système/Compte/Cache → ateliers
   Apps/Scripts (le plus dur : drag & drop, staging, barre mémoire) → Parc/Batch. *15–25 j.*
5. **Packaging** : one-dir + notices LGPL, matrice CI étendue, remplacement des tests d'IHM. *7–11 j.*

**Total ≈ 30–45 jours-personne** pour un portage fidèle. À l'échelle d'un projet de loisir, c'est
l'ordre de grandeur de tout un lot — d'où l'importance de l'étape 0.

## 10. Option C — la solution à ~0,5 jour

Avant d'engager 30 jours : les navigateurs Chromium (Chrome, Edge, Chromium, Brave) ouvrent une
**fenêtre sans barre d'adresse ni onglets** avec `--app=http://127.0.0.1:<port>`. Visuellement
c'est déjà « une application », pour **0 Mo** et une ligne dans `cli ui`.

Honnêtement : ce n'est **pas** de l'embarqué. Firefox et Safari n'ont pas d'équivalent (il faudrait
retomber sur l'onglet classique), l'icône de la fenêtre reste celle du navigateur, et ça ne règle
pas le cas « aucun navigateur exploitable » — qui est justement le cas d'usage fondateur du projet.
Mais c'est un **quick win de V2.x** qui capte l'essentiel du ressenti, et un bon moyen de mesurer
si la demande porte sur la fenêtre ou sur l'indépendance réelle au navigateur.

## 11. Risques

| Risque | Gravité | Atténuation |
|---|---|---|
| Plancher glibc/macOS exclut le parc scolaire ancien | **élevée** | double canal (§6-2), ou épingler 6.9.3 |
| aarch64 Linux : régression Raspberry Pi OS Bookworm | moyenne | garder le binaire web pour arm64 |
| ×4 à ×7 sur le téléchargement | moyenne | assumé et documenté ; le web reste disponible |
| Conformité LGPL en one-file Windows/Linux | moyenne | passer en one-dir + notices, faire relire |
| Perte des 561 l de tests d'IHM | moyenne | étape 1 d'abord (la logique devient testable en pur Python) |
| Fenêtre gelée pendant un flash | moyenne | workers `QThread` dès le spike, pas après |
| Dérive de fidélité entre les deux IHM | faible | le natif est la cible, le web est figé en mode compatibilité |
| Double IHM à maintenir | **élevée** | plan/i18n/SVG partagés (étapes 1–3) : seule la couche vue est dupliquée |

## 11 bis. Descente au niveau des zones

Le découpage **zone par zone** de l'IHM V2 vers les composants V3 — quelles optimisations
rapprochent réellement du desktop, ce qu'elles coûtent en taille et en RAM (mesuré), et ce qu'elles
font perdre en convivialité — est traité à part :
→ [`native-ui-zoning.md`](native-ui-zoning.md).

Résultat marquant : le portage **inverse les deux courbes** — ×6,7 sur le disque, mais **÷5,5 sur
la RAM** (V2 ≈ 690 Mo serveur + navigateur, V3 QML **126 Mo**) — et la « desktop-isation » propre
(menus natifs, dialogues natifs, notifications, persistance de la géométrie) coûte **moins de 3 Mo**,
sans ajouter QtWidgets.

## 12. Synthèse en une ligne

Techniquement **faisable et bien préparé** par l'architecture actuelle (façade `Session`,
callback de progression, SVG générés) ; le coût réel n'est pas le code mais **le plancher de
compatibilité système de Qt**, qui contredit l'objectif de large compatibilité. Chemin conseillé :
**option C tout de suite**, **spike QML (étape 0) pour décider**, et **double canal** si le spike
passe.
