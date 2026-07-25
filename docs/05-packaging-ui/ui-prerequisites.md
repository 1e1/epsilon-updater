# Prérequis d'exécution des composants UI

> Pour **chaque composant** de l'interface web, le **niveau de prérequis minimal** pour qu'il soit
> *fonctionnel* (pas seulement visible). Sert de source de vérité pour taguer la
> [bibliothèque UX](../../src/nwupdater/server/web/ux.html) et pour décider **ce qui peut
> s'afficher au plus tôt** (voir la lecture transversale en fin de document).

Le serveur local est **toujours** présent (il sert la page). Les prérequis ci-dessous décrivent
donc les **capacités d'exécution** dont un composant a besoin *en plus* du serveur : réseau, compte,
disque, USB, calculatrice reconnue, ou une **fonction** matérielle précise.

## Échelle des prérequis

| Code | Prérequis | Signification |
|------|-----------|---------------|
| **P0** | **Standalone** | Purement côté client (ou contrôle local trivial) — aucun réseau, disque ni USB. Utilisable dès le chargement de la page. |
| **P1** | **Internet** | Le serveur va sur le réseau — sans compte, sans appareil (catalogue *live*, téléchargement d'une app communautaire). |
| **P2** | **Internet + compte NumWorks** | my.numworks.com authentifié (firmware officiel, dernière version *live* par modèle). |
| **P3** | **Accès disque PC** | Le serveur lit/écrit des fichiers locaux (cache firmware, bibliothèques app/script, magasin de noms, roster). |
| **P4** | **Accès USB** | Le serveur peut ouvrir un périphérique DFU sur l'USB — **pas encore** identifié comme une calculatrice précise. |
| **P5** | **USB + calculatrice reconnue** | L'identité est lue (modèle / série / OS / famille / régions). |
| **P6** | **USB + reconnue + fonction X** | Une **capacité** matérielle précise est présente : région *apps externes*, stockage Python, slot flashable… (X noté au cas par cas). |

> Ces niveaux ne sont pas strictement linéaires : un composant peut **combiner** des besoins
> (ex. « P5 + P3 » = identité *et* disque). La colonne « Détail » le précise.

> **Note simulateur.** Une **calculatrice démo (virtuelle)** — bouton « Explorer une démo »,
> `attach_demo`, `--virtual` — fournit identité + régions + un DFU virtuel modélisant flash/RAM.
> Elle **substitue P4–P6 sans matériel ni réseau**. Autrement dit, presque toute l'UI est
> exerçable hors-ligne via la démo + le catalogue embarqué. C'est la base du « simulateur »
> (voir §Lecture transversale).

---

## Tableau des composants

### Chrome global (barre d'outils, barre d'état, overlays)

| Composant | Prérequis | Détail |
|-----------|:---------:|--------|
| Bascule de langue (FR/EN) | **P0** | `localStorage`, re-rendu client. |
| Thème (clair/sombre/auto) | **P0** | `data-theme` client. |
| Bascule de mode (Individuel/Classe) | **P0** | État client + `localStorage`. |
| Bouton Quitter | **P0** | Contrôle du serveur local (arrêt) ; aucune ressource externe. |
| Barre d'état (local / hors-ligne / déconnecté) | **P0** | Statique / dérivé de l'état client. |
| Modale mentions légales / avertissement | **P0** | Texte statique. |
| Notifications (`toast`) | **P0** | Live-region client. |

### Connexion & appareil (rail)

| Composant | Prérequis | Détail |
|-----------|:---------:|--------|
| Écran « aucun appareil » — **Explorer une démo** | **P0** | Appareil virtuel, aucun USB. |
| Écran « aucun appareil » — **Rescanner** (détecter le matériel) | **P4** | Énumère un périphérique DFU. |
| Rail appareil — rendu calc + fiche (modèle/famille/MCU/OS/région) | **P5** | Identité lue. *Démo → P0.* |
| Révéler le numéro de série | **P5** | Fait partie du rail (série floutée par défaut). |
| Édition du nom de la calculatrice | **P5 + P3** | Clé `modèle:série` (identité) + magasin de noms (disque). |
| Sélecteur de modèle démo | **P0** | Appareil virtuel. |
| Bouton Déconnecter | **P5** | Affiché seulement si connecté. |
| Barre d'onglets (Parc/Système/Apps/Scripts) | **P0** | Navigation client — mais **masquée tant qu'aucun appareil n'est connecté** (`data-conn`, voir §Lecture transversale). |

### Pane Système (individuel)

| Composant | Prérequis | Détail |
|-----------|:---------:|--------|
| Catalogue / mises à jour firmware | **P5** + source | Compare l'OS de l'appareil au catalogue : embarqué = **P0/offline**, dernière *live* = **P2**. |
| Bascule de canal (stable/bêta) | **P1** | Re-fetch du catalogue ; snapshot embarqué = P0. |
| Bouton **Flasher** le firmware | **P6** (slot flashable) | + image : depuis le cache = **P3**, téléchargée = **P2**. |
| Bouton **Démarrer** (« boot now ») | **P5** | Saut vers l'adresse de boot. |
| Panneau de résultat de flash | **P0** | Affichage client du dernier résultat. |
| Compte / connexion (auth) | **P2** | Internet + compte NumWorks. |
| Cache firmware — **voir** le contenu | **P3** | Lecture des images en cache (disque). |
| Cache firmware — **précharger / mettre à jour** | **P2 + P3** | Téléchargement officiel + écriture disque. |
| Cache firmware — **vider** | **P3** | Suppression sur disque. |

### Atelier Apps (`pane-apps`)

| Composant | Prérequis | Détail |
|-----------|:---------:|--------|
| Atelier apps (liste on-calc + barre mémoire) | **P6** (région apps externes) | *Démo → P0.* |
| Liste « Disponibles » | **P3** (sources locales) + **P1** (URLs distantes) | Catalogue embarqué = P0. |
| Stager une app distante (télécharger le `.nwa`) | **P1** | Téléchargement via le proxy local. |
| Stager un `.nwa` local (glisser/parcourir) | **P3** | Fichier disque. |
| Écrire les apps sur l'appareil | **P6** (région apps) | Le relink d'un ELF peut requérir Node (hors UI). |
| Popover Sources | **P3** (dossiers locaux) + **P1** (URLs) | |

### Atelier Scripts (`pane-scripts`)

| Composant | Prérequis | Détail |
|-----------|:---------:|--------|
| Atelier scripts (liste on-calc + barre mémoire) | **P6** (stockage Python) | *Démo → P0.* |
| Liste « Disponibles » | **P3 + P1** | |
| Envoyer / récupérer des scripts | **P6** | |
| Exporter un script sur le PC | **P3** | Écriture disque. |

### Parc (Classe — `pane-parc`)

| Composant | Prérequis | Détail |
|-----------|:---------:|--------|
| Onglet Parc — rail des classes + table du roster | **P3** | Lit le roster + le magasin de noms (disque). **Aucun appareil requis pour l'affichage** — actuellement bridé « connecté-only » (écart avec plan §1). |
| Enrôlement (upsert au scan) | **P5** | Effet de bord d'un scan réussi. |
| Édition — renommer | **P3** | Magasin de noms. |
| Édition — déplacer / supprimer / CRUD classes | **P3** | Roster. |
| Multi-sélection / barre groupée / glisser-déposer | **P0** (interaction) → **P3** (effet) | |
| Pastille « à jour au dernier scan » | **P3** + catalogue | Compare `known_firmware` au catalogue (embarqué = P0 / live = P2). |

---

## Lecture transversale

### 1. Ce qui peut s'afficher « au plus tôt » (sans calculatrice)

Une **grande partie de l'UI est P0–P3** et ne dépend **pas** d'une calculatrice branchée :

- **P0** : langue, thème, mode, barre d'état, mentions, toasts, sélecteur de démo, panneau de résultat.
- **P2** : connexion au compte NumWorks (indépendante de tout appareil).
- **P3** : **le Parc entier** (rail + roster + édition), le **cache firmware** (voir/vider), les **sources**.

Pourtant l'app-shell **masque tout** (barre d'onglets + panes) tant qu'aucun appareil n'est connecté
(`.window[data-conn="0"]` dans `index.html`). Conséquences directes :

- **Parc** : c'est du **P3 pur** — il devrait s'afficher **sans appareil** (c'est l'écart plan §1).
- **Cache / compte / sources** : consultables et actionnables avant tout branchement.

> **Piste** : découpler la visibilité des composants P0–P3 de l'état de connexion, pour un
> « premier écran utile » immédiat (gérer son parc, précharger le cache, se connecter) au lieu de
> l'écran « branchez une calculatrice ».

### 2. Ce qui incite à un simulateur

Les composants **P4–P6** (rail, catalogue, flash, ateliers apps/scripts) exigent du matériel. Mais
le **device démo (virtuel)** les rend déjà **entièrement exerçables hors-ligne** : identité,
régions, DFU virtuel modélisant flash/RAM. C'est un **simulateur intégré**.

> **Pistes** : promouvoir la démo en parcours « essayer maintenant » de premier plan ; auto-attacher
> une démo pour rendre les composants P5/P6 explorables immédiatement ; étendre la fidélité du
> simulateur (contenu on-calc, tailles, familles) pour couvrir la démo apps/scripts sans matériel.

*(Ces deux points alimentent la discussion « affichage au plus tôt / simulateur ».)*
