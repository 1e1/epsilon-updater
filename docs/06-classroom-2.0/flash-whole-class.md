# Flasher toute la classe — note d'exploration (question ouverte, HORS V1)

> **Exploration de conception**, pas un engagement. Prolonge la question ouverte de
> `docs/06-classroom-2.0/plan.md` §9 (« *Flasher toute la classe* en un geste »). Décrit **comment**
> on pourrait guider l'enseignant pour mettre à jour le firmware d'une classe entière, sans rien
> coder ni promettre. Le mode classe V1 (parc/roster) reste ce qui est livré ; ce document existe
> pour cadrer une discussion ultérieure, pas pour ouvrir un chantier.

Légende : **[EXISTE]** = déjà en place, réutilisable tel quel · **[À BÂTIR]** = n'existe pas encore ·
**[HORS V1]** = explicitement reporté, comme dans `plan.md` §9.

---

## 1. La contrainte de base : **une calculatrice à la fois, branchée individuellement**

Tout part d'un fait matériel et logiciel qu'aucune UX ne peut contourner :

- **Il n'y a pas de bus multi-appareils.** Le flash passe par l'USB/DFU, une calculatrice
  physiquement branchée à la fois. `find_calculator` (`dfu/usbio.py:118`) énumère et prend
  **`found[0]`** — le **premier** appareil trouvé. Deux calculatrices branchées en même temps ⇒
  sélection **ambiguë** (on ne sait pas laquelle on ouvre). La règle de sûreté est donc :
  **une seule calculatrice branchée à la fois.**
- **La session ne connaît qu'un appareil.** `SessionBase` porte un état **mono-appareil** :
  `self.device`, `self.client`, `self.model`, `self.bcd` (`_session_base.py:62`). `attach_real()`
  (`_session_base.py:77`) ouvre **une** calculatrice via `usbio.open_calculator()`. Tout l'I/O
  appareil est sérialisé par un unique `_io_lock` (`_session_base.py:69`) — le serveur est
  **mono-client, mono-poignée USB** par construction.
- **Le flash lui-même est déjà « une-par-une ».** C'est écrit noir sur blanc dans `plan.md` §1 :
  « **Le flash reste une calculatrice à la fois** (chacune branchée individuellement). »

**Conséquence de conception.** « Flasher la classe » **ne peut pas** être un fan-out parallèle.
C'est nécessairement une **séquence guidée** : la même boucle *brancher → identifier → flasher →
débrancher* que le mode individuel, **répétée** pour chaque élève, avec une **orchestration**
par-dessus qui sait où on en est dans la classe. Tout le reste de ce document découle de là.

---

## 2. Le flux séquentiel guidé (proposé) **[À BÂTIR]**

Une **file d'attente** (la « tournée de flash ») pilote la même boucle d'attache/flash déjà
existante, une calculatrice après l'autre.

### 2.1 Construire la file

- **Depuis le parc** : l'enseignant choisit une **classe** dans le rail (`plan.md` §5) ; la file =
  les calculatrices de cette classe, lues via `classroom_roster.all_entries()`
  (`classroom_roster.py:92`) filtrées par `class`. Chaque entrée porte déjà `key = "model:serial"`,
  `name`, `known_family`, `known_firmware`, `known_model` — tout ce qu'il faut pour **afficher** la
  file et **cibler** chaque appareil sans le brancher.
- **Ad-hoc** : une file « tout ce qui se branche » sans passer par une classe (utile pour un poste
  partagé ou une classe non encore rangée). Chaque appareil identifié est traité puis, s'il est
  inconnu, auto-enrôlé au passage (l'upsert-on-scan existe déjà, `_session_roster.py:16`).
- **Pré-marquage « déjà à jour »** : le parc connaît déjà `known_firmware` + une pastille
  `up_to_date` « à jour au dernier scan » (`_session_roster.py:129`). La file peut **pré-cocher**
  comme *à sauter* les calculatrices déjà à la dernière version — l'enseignant flashe seulement le
  reste. (Un re-scan au branchement re-vérifie la version réelle : le pré-marquage n'est qu'une
  aide, jamais une décision finale.)

### 2.2 La boucle, par appareil

Pour chaque entrée de la file, dans l'ordre :

| Étape | Ce qui se passe | S'appuie sur |
|---|---|---|
| **1. Inviter à brancher** | « Branchez **`<nom>`** et mettez-la en mode DFU » (ex. N0110 : RESET en maintenant la touche 6). Le message de `NoCalculatorFound` (`usbio.py:124`) porte déjà ce mode d'emploi. | prompt UI **[À BÂTIR]** |
| **2. Détecter le branchement** | Le *hotplug watch* voit l'appareil apparaître. `device_health()` (`_session_base.py:144`) passe `connected:false → true` ; un `POST /api/device/rescan` (`httpd.py:239`) attache. | `device_health` **[EXISTE]** |
| **3. Identifier** | Lire l'identité DFU : `_identity()` → `CalculatorIdentity` (`dfu/identity.py:47`) donne `model_name`, `serial_number` (Base64 UID MCU), `family`, `os_version`. Clé = `device_names._key(model, serial)` = `model:serial`. | identité **[EXISTE]** |
| **4. Confirmer le bon appareil** | Comparer la clé lue à la clé **attendue** (entrée courante de la file). Match ⇒ on continue ; non-match ⇒ voir §5.1. | garde **[À BÂTIR]** |
| **5. Flasher + vérifier** | `install_firmware(..., from_cache=True, ...)` (`_session_firmware.py:101`) → `Installer.install(image, active_slot=self._active_slot(), verify=True, boot=False)` (`installer.py:181`). Chaque segment est **relu et comparé** (`flash()`, `installer.py:167`) ; `read_installed_version(plan)` relit l'en-tête userland flashé (`installer.py:201`). | flash+verify **[EXISTE]** |
| **6. Rebooter officiel** | `boot()` (`_session_firmware.py:165`) fait un DFU *leave* vers le **bootloader** `0x08000000`, pas vers le slot — le firmware reste **officiel** / compatible mode examen (§5.2). | boot **[EXISTE]** |
| **7. Inviter à débrancher** | « Terminé pour **`<nom>`** — débranchez. » Le *hotplug watch* voit l'appareil partir : `device_health()` renvoie `{connected:false, lost:true}` et auto-`detach()` (`_session_base.py:158`) — c'est le **signal d'avancer**. | `device_health` **[EXISTE]** |
| **8. Avancer** | Marquer l'entrée *faite*, passer à la suivante, revenir à l'étape 1. | orchestrateur **[À BÂTIR]** |

Le fil rouge : les étapes 2, 5, 6, 7 **existent déjà** (c'est exactement le cycle du mode
individuel) ; ce qu'il faut bâtir, c'est **l'enchaînement** (1, 4, 8) et son **état**.

### 2.3 Suivre la progression à travers la classe

Un **état de tournée** (nouvel objet d'orchestration, p.ex. un `ClassFlashMixin` côté session,
miroir stylistique de `RosterMixin`) tient :

- la **liste ordonnée** des cibles (`key`, `nom`, `known_family`, version cible) ;
- un **statut par entrée** : `en_attente → branchée → identifiée → confirmée → flash_en_cours →
  vérifiée → faite`, plus les sorties `échouée` / `sautée` / `mauvais_appareil` ;
- un **curseur** (l'entrée courante) et des **compteurs** (faites / restantes / échouées) pour une
  **barre de progression de classe** et un tableau ligne-par-ligne (réutilise le style « table du
  roster » de `plan.md` §5, colonnes *nom · statut · action*).

**Où vit cet état.** Deux options à trancher, non bloquantes ici :
1. **En mémoire de session** — simple, mais perdu si le serveur redémarre au milieu.
2. **Persisté** à côté du roster (`<config>/nwupdater/…`, même base que `classroom-roster.json`,
   `classroom_roster.py:26`), pour une **reprise après relance**. La rétention de serials au repos
   impose alors les mêmes précautions que le roster (`plan.md` §6) — local uniquement, jamais
   affiché, droits `0700`.

Une **troisième voie, sans nouvel état persistant** : dériver « déjà faite » de la vérité que le
parc écrit **déjà** — après un flash + re-scan, `known_firmware` est rafraîchi et la pastille
`up_to_date` bascule (`_session_roster.py:70`). La tournée peut alors se **reconstruire** à tout
moment depuis le roster : *faites* = à jour, *restantes* = en retard. Reprise gratuite, zéro
duplication.

---

## 3. Erreurs par appareil & reprise **[À BÂTIR par-dessus de l'existant]**

Principe directeur : **un appareil qui échoue ne bloque jamais les autres.** La classe est une file,
pas une transaction unique.

- **Échec isolé.** Un `VerificationError` (relecture ≠ écriture, `installer.py:176`), un
  `CompatibilityError`, un câble arraché en plein flash, un `errTARGET` DFU — tout cela remonte
  aujourd'hui comme une exception que `httpd.py` transforme en JSON d'erreur (`httpd.py:214`).
  L'orchestrateur **capte** l'échec, marque l'entrée `échouée` **avec sa raison**, et **passe à la
  suivante** au lieu d'interrompre la tournée.
- **File reprenable.** Rejouer une tournée ne doit rien re-flasher d'inutile : les entrées `faites`
  (ou déjà `up_to_date`) sont **sautées**, seules les `échouée` / `en_attente` restent. Une entrée
  échouée est **re-tentable** (« Réessayer ») en la rebranchant — la boucle §2.2 repart à l'étape 1
  pour cette seule calculatrice.
- **Vérifier après le flash, toujours.** `verify=True` est le défaut de `Installer.install`
  (`installer.py:188`) : chaque segment est relu (`flash()`), puis `read_installed_version(plan)`
  relit l'en-tête userland (`installer.py:201`) et `install_firmware` renvoie `verified_version`
  (`_session_firmware.py:161`). L'entrée ne passe à `faite` **que si** la version relue correspond à
  la cible. Cas particulier **N02xx (scientifique)** : firmware **opaque/chiffré**, pas d'en-tête
  userland lisible ⇒ `read_installed_version` renvoie `None` (`installer.py:201`). La preuve reste la
  **relecture segment-par-segment** pendant `flash()` ; le contrôle « version = cible » n'est
  disponible que sur les familles à en-tête (N01xx). À signaler dans l'UI de la tournée.
- **Interruption de la tournée** (fermeture, coupure) : voir §2.3 — soit reprise depuis l'état
  persisté, soit reconstruction depuis le roster (`known_firmware` / `up_to_date`).

---

## 4. Mauvais appareil & sûreté **[garde À BÂTIR, garanties matérielles EXISTANTES]**

### 4.1 Vérifier que l'appareil branché est **le bon** (`model:serial`)

Le parc possède déjà l'identité **stable** de chaque calculatrice : la clé `model:serial`, où
`serial` = Base64(UID MCU), 16 car. (`dfu/identity.py:36`), le **même** identifiant que le magasin
de noms. À l'étape 4 de la boucle, l'orchestrateur lit la clé de l'appareil branché
(`_identity()`) et la **compare à la clé attendue** :

- **Match** ⇒ on flashe.
- **Non-match mais présent dans la file** ⇒ l'élève a branché **une autre** calculatrice de la
  classe : proposer de **réordonner** (traiter celle-ci maintenant) plutôt que de refuser.
- **Non-match et inconnue du parc** ⇒ **stop** : demander confirmation explicite avant de flasher un
  appareil hors-classe (éviter de flasher la calculatrice d'un prof, d'un autre groupe…). L'auto-
  enrôlement du roster (`upsert_on_scan`, `classroom_roster.py:119`) peut l'ajouter, mais le **flash**
  reste une action confirmée, jamais automatique sur une identité inattendue.

C'est un **garde logiciel à écrire** ; la donnée pour l'écrire (l'identité + la file attendue)
existe déjà.

### 4.2 Mode examen & rester « officiel »

Enjeu propre au parc scolaire (cf. `docs/01-specs/firmware-authenticity.md`) : **seul un firmware
officiel peut entrer en mode examen**. Un *leave* DFU **dans le slot QSPI** fait basculer le kernel
en « **UNOFFICIAL SOFTWARE** » et **désactive le mode examen** — inacceptable pour une classe qui
passe un examen. La parade **existe déjà** et doit être la fin **obligatoire** de chaque flash de la
tournée : `boot()` fait le *leave* vers le **bootloader** `0x08000000` (`_session_firmware.py:165`,
`BOOTLOADER_RESET_ADDRESS`), ce qui déclenche un *cold boot* re-vérifiant la signature du slot et
**garde l'appareil officiel** (comportement du flux WebUSB officiel, `official-flash-flow-captured`).
La tournée **ne doit jamais** sauter directement dans le slot flashé.

### 4.3 Récupération d'un flash interrompu (garantie A/B **[EXISTE]**)

Sur les modèles à double slot (N0110/N0120), `install_firmware` flashe **le slot inactif**
(`_active_slot()`, `_session_firmware.py:81`) — le slot **actif** (celui qui tourne) est protégé en
écriture par le matériel et n'est **jamais** touché. `plan_install` (`installer.py:85`) applique
cette règle. **Conséquence forte pour une classe** : un flash interrompu (câble arraché à mi-course)
**ne peut pas briquer** la calculatrice — le slot qui tournait est intact, l'appareil reboote
dessus. On rebranche et on **réessaie** (§3), sans risque. C'est exactement ce qui rend une tournée
de classe **sûre à reprendre**. (Les modèles mono-slot N0100/N02xx n'ont pas cette atomicité A/B :
à signaler comme risque résiduel côté UI pour ces familles.)

### 4.4 Modèles / familles **mixtes** dans une même classe

Une vraie classe mélange N0110, N0120 (graphique) et N0200 (scientifique). L'infra gère déjà le
**par-appareil** :

- **Bon firmware par famille** : `install_firmware(from_cache=True)` cible le cache du **modèle
  branché** (`self.model.name`) ; `preload_all()` (`_session_firmware.py:38`) **pré-cache la dernière
  version de CHAQUE modèle connu** — « toute une flotte mixte prête hors-ligne », y compris le vrai
  `.dfu` officiel quand on est connecté. La tournée choisit donc automatiquement l'image de la
  bonne famille via l'identité lue à l'étape 3.
- **Bonne stratégie de slot** : `plan_install` distingue A/B (N01xx) du mono-slot (N0100/N02xx) et
  du `.dfu` officiel multi-slots verbatim — **sans** intervention de l'orchestrateur.
- **Cible de version par appareil** : la pastille `up_to_date` est déjà **par famille**
  (`_roster_up_to_date`, `_session_roster.py:129`, via `_catalog_for`). « À jour » veut dire quelque
  chose de correct pour chaque modèle de la file.

Rien à concevoir de spécial pour le mixte, **sauf** l'**affichage** (grouper/étiqueter la file par
famille) et l'exception de vérification N02xx (§3).

---

## 5. Ce qui EXISTE (réutilisé) vs ce qui reste à BÂTIR

**Réutilisé tel quel — [EXISTE] :**

- **Le cycle flash + vérif d'un appareil** : `FirmwareMixin.install_firmware`
  (`_session_firmware.py:101`) → `Installer.install(..., verify=True)` (`installer.py:181`), relecture
  segment-par-segment (`flash`, `installer.py:167`) + `read_installed_version` (`installer.py:201`).
- **L'atomicité A/B & la sûreté « officiel »** : slot inactif (`_active_slot`,
  `_session_firmware.py:81`) + `boot()` vers le bootloader (`_session_firmware.py:165`).
- **L'identité & la clé** : `_identity()` / `read_identity` (`dfu/identity.py:47`), clé `model:serial`
  (`device_names._key`).
- **Le hotplug (branché/débranché)** : `device_health()` et ses transitions `lost`/`connected`
  (`_session_base.py:144`), l'attache `attach_real()` + le seam `_on_attached → _after_scan`
  (`_session_base.py:113`), et l'endpoint `POST /api/device/rescan` (`httpd.py:239`).
- **Le parc / roster** : source de la file et de l'auto-enrôlement — `all_entries`
  (`classroom_roster.py:92`), `RosterMixin` (`_session_roster.py`), pastille `up_to_date`.
- **Le cache firmware hors-ligne, multi-familles** : `preload_all()` (`_session_firmware.py:38`),
  `install_firmware(from_cache=True)`.

**À construire — [À BÂTIR] :**

- **L'orchestrateur de tournée** : la file ordonnée + la machine à états par entrée + le curseur +
  les compteurs (§2.3). Vraisemblablement un `ClassFlashMixin` de session (miroir de `RosterMixin`)
  et quelques routes (`POST /api/class-flash/{start,next,retry,skip,cancel}`, `GET /api/class-flash`).
- **Les invites brancher / débrancher** : traduire les transitions `device_health` en messages
  « branchez `<nom>` (mode DFU) » / « débranchez, on avance » (étapes 1 et 7).
- **Le garde mauvais-appareil** : comparer la clé `model:serial` lue à la clé attendue (§4.1).
- **L'UI de tournée** : barre de progression de classe + tableau ligne-par-ligne (statut, réessayer,
  sauter), onglet/vue visible **seulement en mode classe** (comme le parc, `plan.md` §5), avec parité
  i18n FR/EN (`plan.md` §5, `tests/test_i18n.py`).
- **(À trancher) la persistance de la tournée** vs sa reconstruction depuis le roster (§2.3).

---

## 6. Cadre : **futur, HORS V1** — ce que cette note n'engage pas

Comme `plan.md` §9, on **verrouille** le périmètre pour éviter la dérive :

- **[HORS V1]** L'orchestrateur de tournée et son UI (tout le §2, §5-*à bâtir*) — **non conçu pour
  livraison**, seulement esquissé ici.
- **[HORS V1]** Toute forme de **flash parallèle / multi-appareils** — impossible sans fan-out de
  bus (voir §1), donc **hors sujet** ; le séquentiel guidé est la **seule** forme envisageable.
- **[HORS V1]** La **persistance** d'un état de tournée (fichier dédié) — à ne considérer que si la
  reconstruction depuis le roster (§2.3) se révèle insuffisante.
- **[HORS V1]** Le **téléchargement/authentification** en masse — la tournée s'appuie sur le cache
  **déjà** rempli (`preload_all`) ; elle n'introduit pas de nouveau chemin réseau.

**Ce qui reste vrai pour V1** : le flash demeure **une calculatrice à la fois, branchée
individuellement** (`plan.md` §1). Ce document ne fait que **décrire un futur possible** au-dessus
de cette contrainte, pour nourrir la discussion — **aucun changement de code, aucun engagement.**

### Points à trancher plus tard

1. État de tournée : en mémoire, persisté, ou reconstruit depuis le roster ?
2. Vérification N02xx (pas d'en-tête userland lisible) : quelle preuve de succès afficher ?
3. Risque résiduel mono-slot (N0100/N02xx) : quel garde UX faute d'atomicité A/B ?
4. Ordre de la file : ordre du parc, par famille, ou « en retard d'abord » ?
5. Politique sur appareil **inattendu/hors-classe** branché en pleine tournée (§4.1).
