# Classroom 2.0 — Parc de calculatrices (roster local) · cible 2.0.0-rc

> **Plan de conception + implémentation** (pas encore codé). Décrit un **parc local** de
> calculatrices pour le **mode classe uniquement** : un registre hors-ligne qui regroupe les
> calculatrices scannées, les range par **classe (un seul niveau, un tag par calculatrice)** et
> laisse l'enseignant les renommer / déplacer / supprimer. Aucun compte, aucun cloud en mode
> classe : le nommage est **purement local**.

Légende : **[V1]** = dans cette livraison · **[HORS V1]** = explicitement reporté.

---

## 1. Vue d'ensemble & objectifs (2.0.0-rc)

Le mode classe actuel se limite au **cache firmware** (`app.js:206 renderMode` → bloc
`classroom_intro` + `cache-body`, cf. `docs/03-transfer-install/firmware-cache.md`). Classroom 2.0
ajoute la **gestion du parc** : une vue **« Parc »** qui liste toutes les calculatrices déjà vues
sur ce poste, triées par classe.

Objectifs :

- **Une source de vérité locale** pour « quelles calculatrices je gère, et dans quelle classe »,
  survivant aux débranchements et aux relances.
- **Zéro friction d'enrôlement** : brancher une calculatrice suffit à l'ajouter (auto-enrôlement).
- **Composer avec l'UI refondue** (barre d'onglets `index.html:332 .tabbar`, `setTab`) :
  - **Mode individuel** — inchangé : une calculatrice à la fois, onglets `System / Apps / Scripts`,
    et un **nom local unique « ad vitam »** (fondation `device_names.py`, non couvert ici).
  - **Mode classe** — un onglet **« Parc »** supplémentaire, **visible seulement en mode classe**
    (comme le bloc cache l'est déjà via `STATE.mode === "classroom"`, `app.js:210`). Le parc n'est
    pas centré appareil : il s'affiche même sans calculatrice branchée.
- **Le flash reste une calculatrice à la fois** (chacune branchée individuellement). Le
  « flasher toute la classe » est une **question ouverte** (§9), pas conçu ici.

Où vit le parc, en une esquisse :

```
                 device_names.py            classroom_roster.py            (NOUVEAU)
 config dir/  ├─ device-names.json  ◀─join─  classroom-roster.json
 nwupdater/   │  {model:serial→nom}          {schema, classes[], calculators{key→méta}}
             (nom "ad vitam", 2 modes)       (classe, known_fw, last_scan… mode classe)
                      ▲                                  ▲
                      │ get_name/set_name                │ upsert/move/delete/class-CRUD
             NamesMixin (_session_names.py)      RosterMixin (_session_roster.py, NOUVEAU)
                                                          ▲
   attach_real()/rescan ──(policy.classroom)──▶ upsert du parc (side-effect de scan)
                                                          ▲
   httpd.py  GET /api/roster · POST /api/roster/{rename,move,delete,class/*}
                                                          ▲
   web/app.js  onglet « Parc » : rail des classes + table du roster (DnD + multi-sélection)
```

---

## 2. Modèle de données & stockage

### 2.1 L'enregistrement (logique)

Clé d'identité : **`model + serial`**, exactement la clé du magasin de noms
(`device_names._key`, `device_names.py:30` → `"model:serial"`, `model` en minuscules/strippé,
`serial` strippé). Le `serial` provient de l'identité DFU (`CalculatorIdentity.serial_number`,
`dfu/identity.py:36` = Base64(UID MCU), 16 car.).

| Champ | Origine | Notes |
|---|---|---|
| `model` / `serial` | `_identity()` | forment la **clé** `model:serial`. Le serial n'est **jamais affiché** (§6). |
| `name` | **jointure** `device_names.get_name()` | **pas dupliqué** — voir 2.3. |
| `class` | utilisateur | `null`/absent ⇒ **« Sans classe »**. Un seul niveau, pas de dossier. |
| `known_firmware` | `identity.os_version` au dernier scan | **« vu au dernier scan »**, pas l'état live (§3). |
| `known_family` | `identity.family` | `"graphique"` / `"scientifique"` — pilote l'icône. |
| `known_model` | `identity.model_name` (`n01xx`) | redondant avec la clé, gardé pour l'affichage. |
| `last_scan` | horodatage ISO 8601 UTC du dernier scan | `datetime.now(timezone.utc).isoformat()`. |

### 2.2 Forme JSON sur disque

Fichier : **`<config>/nwupdater/classroom-roster.json`**, même base que le token et les noms —
`NWUPDATER_CONFIG_DIR` → `XDG_CONFIG_HOME` → `~/.config` (miroir de
`device_names.store_path()` `device_names.py:17` et `catalog.auth.config_path()` `auth.py:251`).
Un `roster_path(*, path=None)` reproduit exactement ce résolveur.

```json
{
  "schema": 1,
  "classes": ["Seconde A", "Terminale S"],
  "calculators": {
    "n0110:AbCd1234EfGh5678": {
      "class": "Terminale S",
      "known_firmware": "23.2.4",
      "known_family": "graphique",
      "known_model": "n0110",
      "last_scan": "2026-07-25T09:14:03+00:00"
    }
  }
}
```

- **`classes`** est explicite (source de vérité du rail) pour qu'une **classe vide** puisse
  exister ; elle est **triée alphanumériquement** à l'affichage. « Sans classe » et « Toutes »
  sont des buckets synthétiques, **jamais** stockés dans `classes`.
- **`name` absent du JSON** : le nom vient du magasin de noms (2.3).

### 2.3 Extension du magasin de noms (fondation)

Le parc **étend** la fondation `device_names.py` au lieu de la réimplémenter :

- Le **nom** reste dans `device-names.json`, autorité partagée par les deux modes. Le roster ne le
  duplique pas ; il le **joint** sur la clé `model:serial` commune via `device_names.get_name()`
  au moment de la lecture, et l'écrit via `device_names.set_name()` (`device_names.py:55`).
- Conséquence voulue : une calculatrice nommée en **mode individuel** apparaît déjà nommée dans le
  parc, et un renommage dans le parc suit la calculatrice partout. Une seule source de vérité pour
  le nom, zéro divergence.
- Le TODO cloud-sync existant (`_session_names.py:36`) reste **hors périmètre** (Individuel,
  différé).

### 2.4 Champ de version, tolérance à la corruption, migration

- **`schema: 1`** en tête (le magasin de noms est un dict plat sans version ; le roster introduit
  le champ pour évoluer). À la lecture, un `schema` inconnu/plus récent ⇒ lecture prudente de ce
  qui est reconnu, jamais de crash.
- **Tolérance à la corruption** : miroir de `device_names._load` (`device_names.py:34`) — un JSON
  illisible (`OSError`/`json.JSONDecodeError`) ⇒ **parc vide** plutôt qu'une exception. Écriture
  atomique (`write_text` d'un blob complet), `mkdir(parents=True, exist_ok=True)`.
- **Migration** : additive, non destructive. Un poste pré-2.0 a seulement `device-names.json` (dict
  plat). La 2.0 crée `classroom-roster.json` **à côté**. Le roster démarre **vide** (schéma présent,
  `calculators: {}`, `classes: []`) — conforme à la règle « une calculatrice n'entre que par un
  scan » (§3) : **on ne pré-remplit pas** le parc depuis les noms existants. Les calculatrices déjà
  nommées réapparaissent **déjà nommées** dès leur prochain scan (jointure 2.3). Rien n'est perdu,
  rien n'est inventé.

---

## 3. Flux de scan / auto-enrôlement

**Un seul déclencheur : un scan réussi.** Le point d'accroche est le chemin d'attache existant —
`attach_real()` (`_session_base.py:77`) et `attach_demo()` (`:92`), tous deux passant par
`_on_attached()` (`:113`) — appelé par `POST /api/device/rescan` (`httpd.py:236`).

Ajout : après une attache réussie qui expose un `serial`, la session appelle
`roster_upsert_current()` (nouvelle méthode `RosterMixin`) **quand `policy.classroom`** est actif
(`_session_base.py:70`, `capabilities.Policy(classroom=…)`). L'upsert :

- **Nouvelle calculatrice** : crée l'enregistrement avec `class = null` (⇒ **« Sans classe »**),
  `known_*` depuis l'identité, `last_scan = now`.
- **Calculatrice connue** : **rafraîchit** `known_firmware`, `known_family/model` et `last_scan`.
  **Ne touche jamais** `class` ni le nom (une re-lecture ne défait pas un rangement).
- **Idempotent** : ne réécrit le fichier que si un champ change (évite le thrash de `last_scan` sous
  le poll de santé `device_health`, `_session_base.py:138`).

**« Known firmware » vs firmware réel.** Le parc affiche `known_firmware` étiqueté **« vu au dernier
scan »** avec `last_scan`, jamais « actuel ». Seule la calculatrice branchée expose l'état **live**
via `GET /api/identity` (`httpd.py:177`). La pastille « à jour » compare `known_firmware` au dernier
de la famille (snapshot `_catalog_for`, `_session_base.py:169`, ou live) et est libellée **« à jour
au dernier scan »** pour ne pas laisser croire à un état temps réel.

---

## 4. API serveur

Nouveau mixin **`RosterMixin`** (`server/_session_roster.py`), ajouté à la composition
`Session(... , RosterMixin, SessionBase)` (`session.py:19`), même style que `NamesMixin`. Routage
dans `httpd.py`, réutilisant `_json` / `_locked_json` (`httpd.py:48/56`), le garde CSRF/DNS-rebind
`_guard(require_origin=True)` pour les POST (`:63`, `:213`) et le `_io_lock` des mutations.

| Méthode & route | Corps | Réponse | Rôle |
|---|---|---|---|
| `GET /api/roster` | — | `{schema, classes:[…], unfiled_label, calculators:[…], counts:{class→n}}` | Liste le parc (classes triées + calcs joints aux noms + pastille à-jour). |
| `POST /api/roster/rename` | `{key, name}` | `{ok, key, name}` | Renomme (délègue à `device_names.set_name`, vide ⇒ défaut). |
| `POST /api/roster/move` | `{keys:[…], class}` | `{ok, moved}` | Déplace **une ou plusieurs** calcs ; `class=null` ⇒ « Sans classe ». |
| `POST /api/roster/delete` | `{keys:[…]}` | `{ok, deleted}` | Supprime les enregistrements (un re-scan les recrée — **pas de liste « ignorés »**). |
| `POST /api/roster/class/create` | `{name}` | `{ok, classes}` | Crée une classe (vide autorisée). |
| `POST /api/roster/class/rename` | `{from, to}` | `{ok, classes}` | Renomme + réaffecte ses calcs. |
| `POST /api/roster/class/delete` | `{name, confirm?}` | `{ok}` **ou** `{ok:false, needs_confirm:true, count:N}` | Vide ⇒ suppression directe ; non vide **sans** `confirm` ⇒ demande confirmation ; **avec** `confirm` ⇒ ses calcs retombent en « Sans classe » (**jamais perdues**). |

- **Objet de chaque `calculators[]`** : `{ key, model, name, default, class, known_firmware,
  known_family, known_model, last_scan, up_to_date }`. `key = "model:serial"` sert d'**id d'action**
  (attribut `data-key`), **jamais rendu en texte** (§6). `default` = affichage de repli
  (`_name_identity`, `_session_names.py:9`).
- **Upsert-on-scan** : **pas** d'endpoint public dédié — effet de bord de `POST /api/device/rescan`
  (§3). `roster_upsert_current()` reste appelable directement pour les tests.

---

## 5. UX frontend (onglet « Parc »)

Nouvel onglet **« Parc »** dans `.tabbar` (`index.html:332`), rendu **seulement** si
`STATE.mode === "classroom"` (`app.js:65`), à côté de `System / Apps / Scripts`. Le rendu réutilise
`$`, `esc`, **`jsStr`** (échappement sûr pour handlers inline, cf. O'Brien, `app.js:10`), `t()`,
`toast`, et `const reduced` (`app.js:14`).

**Disposition** : rail des classes (gauche) + table du roster (droite).

- **Rail des classes** : `Toutes` · `Sans classe` · chaque classe (**tri alphanumérique**), avec
  compteurs (`counts`), boutons réels (`aria-pressed`, filtre actif). Bouton **+ Ajouter une
  classe** ; par classe : renommer / supprimer (suppression ⇒ **confirmation** si non vide).
- **Table du roster** — colonnes : **icône** (glyphe famille via `calc.js`), **nom** (édition
  inline), **firmware connu + pastille à-jour**, **dernier scan** (relatif), **actions**. **Aucune
  colonne numéro de série.**
- **Renommer** : édition inline (input/`contenteditable`) → `POST /api/roster/rename`.
- **Déplacer** — trois chemins :
  1. **Menu déroulant** par ligne (« Déplacer vers… ») → `POST /api/roster/move` (un `key`).
  2. **Glisser-déposer** d'une ligne sur un bucket du rail.
  3. **Multi-sélection** (cases à cocher) + **barre groupée** (« Déplacer vers… », « Supprimer »)
     → `move`/`delete` avec **plusieurs** `keys`.
  Le **déroulant + la multi-sélection sont le repli clavier accessible du DnD**.
- **Supprimer une classe** : modale de confirmation si non vide (ses calcs → « Sans classe ») ;
  vide ⇒ suppression directe.

### i18n (parité FR/EN)

Nouvelles clés **dans les deux blocs** `i18n.js` (`fr:` `i18n.js:7`, `en:` `:174`), **triées** et
dans le **même ordre** — garanti par `tests/test_i18n.py` (parité + tri + « toute clé utilisée dans
`app.js` est traduite »). Jeu représentatif (alpha) : `parc`, `roster_add_class`,
`roster_bulk_selected`, `roster_class_all`, `roster_col_actions`, `roster_col_firmware`,
`roster_col_lastscan`, `roster_col_name`, `roster_delete`, `roster_delete_class_confirm`,
`roster_empty`, `roster_known_fw`, `roster_lastscan`, `roster_move_to`, `roster_unfiled`,
`roster_uptodate`.

### Accessibilité

- **Repli DnD** = déroulant + multi-sélection (déjà ci-dessus), tout au clavier.
- **Focus** : édition inline et modale gèrent le focus (retour au déclencheur après fermeture) ;
  boutons du rail focusables (`:focus-visible` déjà stylé `index.html:46`).
- **`prefers-reduced-motion`** : le `const reduced` (`app.js:14`) coupe les animations de DnD et de
  compteurs (comme `runMeter`).
- Table sémantique (en-têtes `th`), rail en boutons `aria-pressed`, live-region `toast`
  (`role=status`) pour confirmer déplacements/suppressions.

---

## 6. Confidentialité / sécurité

- **Beaucoup de numéros de série d'élèves persistés au repos.** Le serial = Base64(UID MCU),
  identifiant matériel **stable** d'une calculatrice précise (donc quasi-PII : il désigne l'appareil
  d'un élève). Un parc de classe en accumule des dizaines.
- **Posture retenue — locale uniquement, pas de cloud en mode classe** : le fichier reste sous le
  dossier config du poste enseignant (même base que le token). Aucune sortie réseau pour les données
  de parc ; les mutations passent le garde CSRF/DNS-rebind loopback (`httpd.py:63`).
- **Le serial n'apparaît jamais dans les listes** : il est la **clé interne** (`model:serial`) et
  l'`id d'action` (`data-key`), jamais un texte affiché. Dans la vue mono-appareil il reste
  **flouté / clic-pour-révéler** comme aujourd'hui.
- **Rétention minimale** : supprimer une calculatrice **efface** l'enregistrement (pas de tombstone
  ni de liste « ignorés ») ; un re-scan la recrée.
- **Permissions** : réutiliser le dossier `nwupdater` que l'auth durcit déjà en `0700`
  (`auth.py:264`) ; le roster n'est pas un secret comme le token, mais concentre beaucoup de
  serials — resserrer les droits est prudent, à signaler dans les notes de version.
- **Pourquoi ce choix** : minimisation et localité des données (le fichier reste chez l'enseignant),
  surface d'exposition réduite, compatible RGPD (traitement local, pas d'affichage d'identifiant).

---

## 7. Plan de test

Miroir de `tests/test_device_names.py` (round-trips de magasin, méthodes de session sur device
virtuel, dispatch HTTP sur port loopback éphémère avec en-tête `Origin`).

- **Unitaire `classroom_roster.py`** : `roster_path` (résolution env), upsert (création + refresh
  idempotent), move (simple / multiple), delete, class create/rename/delete (**vide ⇒ direct** vs
  **non vide ⇒ needs_confirm puis repli « Sans classe »**), **jointure du nom** (le nom vient de
  `device-names.json`), **coexistence/migration** (roster absent ⇒ vide, noms préservés),
  **tolérance corruption** (JSON cassé ⇒ parc vide), **schema** inconnu ⇒ lecture prudente.
- **Session `RosterMixin`** : `roster()`, `roster_move()`, `roster_delete()`, class-CRUD contre un
  device virtuel ; **upsert-on-attach** déclenché par `attach_*` sous `policy.classroom`.
- **API serveur** : un test par route (`_get`/`_post` avec `Origin`), dont le **flux de confirmation
  de suppression de classe** (2 étapes) et le **move en masse** (plusieurs `keys`).
- **i18n** : `tests/test_i18n.py` reste vert (parité FR/EN + tri) avec les nouvelles clés.
- **UI smoke** (`tests/test_ui_smoke.py` / `test_ui_logic.py`) : l'onglet Parc se rend, les handlers
  move/bulk/delete-class existent, **aucun serial** n'est rendu en texte.
- **Couverture ≥ 80** : `pyproject.toml [tool.coverage.report] fail_under = 80` (`pyproject.toml:73`)
  ; le nouveau module doit être intégralement couvert pour ne pas faire baisser le seuil.

---

## 8. Livraison par phases (2.0.0-rc)

Chaque phase est **livrable et verte** (tests + mypy + ruff), et **dépend de l'atterrissage de la
fondation « magasin de noms »** (tâche parallèle) pour la clé `model:serial`.

- **Phase 0 — Fondation magasin.** `classroom_roster.py` : `roster_path`, load/save tolérant,
  `upsert` / `move` / `delete` / class-CRUD, jointure du nom, `schema`, tolérance corruption +
  tests unitaires. Aucune UI.
- **Phase 1 — Parc lecture seule.** `RosterMixin` + `GET /api/roster` ; **upsert-on-scan** câblé
  dans le chemin `rescan`/`attach` sous `policy.classroom` ; onglet **Parc** affiche le rail des
  classes + la table (nom, firmware connu + pastille, dernier scan). Roster visible, non éditable.
- **Phase 2 — Édition.** `rename`, `move` (déroulant), `delete` calc, class create/rename/delete
  avec **confirmation**. Chemin **clavier accessible complet**.
- **Phase 3 — DnD + multi-sélection.** Glisser une ligne sur le rail ; cases à cocher + barre
  groupée (réutilisent `move`/`delete`). Déroulant/multi-sélection restent le **repli a11y**.
- **Phase 4 — Finitions.** Balayage i18n (parité FR/EN), reduced-motion, gestion du focus, états
  vides, compteurs, pastille « à jour » via catalogue, mise à jour docs + captures d'écran.

---

## 9. Risques & questions ouvertes

### Explicitement HORS V1 (garde anti-dérive de périmètre)

- **[HORS V1]** Dossiers **imbriqués** / sous-classes — un seul niveau de tag, décision verrouillée.
- **[HORS V1]** **Historique** par appareil / timeline des scans.
- **[HORS V1]** **Export/import CSV** du parc.
- **[HORS V1]** **Notes** libres par calculatrice.
- **[HORS V1]** **Sync cloud du nom en mode classe** — le nommage classe est **local pur** ; la
  sync est un sujet **Individuel**, séparément différé (`_session_names.py:36`).

### Top risques

1. **Couplage à la fondation « magasin de noms » en cours.** Sa forme finale (endpoints
   `/api/device/name`, clé) peut bouger. *Mitigation* : joindre sur la clé partagée `model:serial`
   et passer par `device_names.get_name/set_name` — ne pas réimplémenter ni dépendre de sa forme
   exacte.
2. **Serials au repos (confidentialité).** Beaucoup d'identifiants matériels d'élèves persistés.
   *Mitigation* : local-only, jamais affiché, droits du dossier resserrés, mention en notes de
   version (§6).
3. **Sémantique de l'upsert-on-scan** pour les devices **démo/virtuels** et le churn de re-branchage
   (thrash de `last_scan` sous le poll de santé). *Mitigation* : upsert **idempotent** (n'écrit que
   si un champ change), et décision explicite d'enrôler ou non les démos.

Autres points à trancher : collision au renommage de classe, ordre/locale du tri alphanumérique des
classes, comportement du bucket « Toutes ».

### Question OUVERTE (différée, à discuter)

- **« Flasher toute la classe » en un geste.** Aujourd'hui **le flash reste une calculatrice à la
  fois** (chacune branchée individuellement). Une action « flasher la classe » soulève des questions
  d'UX et de sûreté (file d'attente, séquentiel guidé, branchement un-par-un, gestion des erreurs
  par appareil). **Non conçu en V1** — capturé ici pour une discussion approfondie ultérieure.
