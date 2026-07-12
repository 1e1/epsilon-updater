# Déclaration de bonne foi / Good-faith declaration — nwupdater

*Document complémentaire à l'[AVERTISSEMENT / DISCLAIMER](DISCLAIMER.md). En cas de doute, le
code source fait foi : ce projet est ouvert (MIT) et intégralement auditable. / Companion to the
[DISCLAIMER](DISCLAIMER.md). In case of doubt, the source code prevails: this project is open
(MIT) and fully auditable.*

**Version :** 1.0 — 2026-07-12
**Portée / Scope :** l'outil `nwupdater` (cœur headless + page web locale), tous lots confondus.

🇫🇷 [Français](#français) · 🇬🇧 [English](#english)

---

## Français

### 1. Objet et esprit du projet

`nwupdater` est un projet **indépendant, non commercial et de hobby**, sans aucun lien avec
NumWorks SAS. Sa seule finalité est **l'interopérabilité et le droit à la réparation** : offrir
au **propriétaire** d'une calculatrice NumWorks un moyen de la mettre à jour et d'y installer
des applications tierces **sans dépendre de Chrome + WebUSB**, sur le modèle des updaters
communautaires Flipper Zero et Lunii.

Cette déclaration atteste que l'outil est conçu et distribué **de bonne foi** :

- il **n'extrait, ne redistribue et ne modifie aucun binaire propriétaire** NumWorks ;
- il **ne contourne aucune mesure technique de protection** (la signature cryptographique du
  firmware officiel est **préservée intacte**) ;
- il **n'exfiltre aucune donnée** vers l'auteur ou un tiers ;
- il n'agit **que** sur du matériel que l'utilisateur **possède** et avec des identifiants qui
  **lui appartiennent**.

### 2. Pré-requis de fonctionnement

L'outil ne peut, par construction, fonctionner que si **toutes** ces conditions sont réunies —
ce qui garantit qu'il s'exécute dans un cadre légitime :

| Pré-requis | Détail | Pourquoi c'est un garde-fou |
|-----------|--------|------------------------------|
| **Possession physique** | Une vraie calculatrice NumWorks (famille Graphique N01xx ou Scientifique N02xx) branchée en USB par l'utilisateur. | Aucune action à distance possible ; l'opérateur est le propriétaire. |
| **Compte NumWorks personnel** | Le firmware officiel est derrière authentification (401 en anonyme). L'utilisateur fournit **ses propres** identifiants. | Le tool ne héberge ni ne partage aucun binaire : chaque octet vient du serveur officiel, sous la session de l'utilisateur. |
| **Consentement explicite** | Chaque opération d'écriture est déclenchée manuellement, après affichage de l'avertissement. | Rien ne se déclenche silencieusement. |
| **Runtime** | Python 3 ; `pyusb`/`libusb` **uniquement** pour piloter du matériel réel (mode production). | En démo (device virtuel), aucune dépendance ni aucun USB. |
| **Protocole standard** | La calculatrice expose un mode DFU/DfuSe STM32 **standard** (VID 0x0483). | Aucun exploit, aucune faille : on parle le protocole que l'appareil publie lui-même. |

> Sans compte valide **et** sans calculatrice branchée, l'outil ne fait rien d'autre que
> tourner en mode démonstration contre un appareil virtuel en mémoire.

### 3. Non-altération des données — justification

#### 3.1 Le firmware officiel n'est jamais modifié

- Le `.dfu` téléchargé est un **conteneur DfuSe complet et signé par NumWorks**. `nwupdater`
  ne le **réassemble pas**, ne le **repackage pas**, ne le **patche pas** : il le transmet
  **octet pour octet** à la calculatrice.
- Deux contrôles d'intégrité **avant** tout flashage
  ([`catalog/download.py`](src/nwupdater/catalog/download.py)) :
  1. **taille** comparée à celle annoncée par le manifeste officiel (`{model}/{channel}.json`) ;
  2. **signature de format** : rejet si les octets ne commencent pas par la magie `DfuSe`.
- Une **empreinte SHA-256** du binaire est calculée et journalisée (avec version, patch_level et
  taille) dans `~/.config/nwupdater/downloads.log` : preuve vérifiable d'identité bit-à-bit avec
  la source officielle.
- La **signature cryptographique NumWorks reste intacte** : c'est le bootloader de la
  calculatrice qui la vérifie. Un binaire altéré serait de toute façon **rejeté par l'appareil**.

#### 3.2 L'écriture est vérifiée et non destructive par défaut

- Sur les appareils à double slot A/B (N0110/N0120), l'outil flashe **le slot inactif** puis
  fait basculer le boot — le système en cours d'exécution n'est pas touché tant que la nouvelle
  image n'est pas écrite ([`install/installer.py`](src/nwupdater/install/installer.py)).
- Chaque segment écrit est **relu et comparé** (*read-back verify*, activé par défaut) ; toute
  divergence lève une `VerificationError` et interrompt l'opération.
- **Réversibilité** : l'utilisateur peut à tout moment reflasher le firmware officiel de son
  choix via le même mécanisme.

#### 3.3 Lecture de l'appareil en lecture seule

- La détection d'identité (modèle, famille, zone apps) se fait par une lecture DFU **read-only**
  du `platforminfo` — aucune écriture pour identifier la calculatrice.

#### 3.4 Aucune altération des données de l'utilisateur… avec une réserve honnête

- L'outil **ne collecte, ne modifie et ne transmet aucune donnée personnelle** vers l'auteur ou
  un tiers. Aucune télémétrie.
- **Réserve assumée** : flasher un firmware **peut effacer les données présentes sur la
  calculatrice** (scripts, notes). C'est inhérent à toute mise à jour de firmware, indépendant
  de cet outil, et **clairement signalé dans le [DISCLAIMER](DISCLAIMER.md)**. L'utilisateur est
  invité à sauvegarder au préalable.

### 4. Sécurisation des données

#### 4.1 Modèle « bring-your-own-token » — le mot de passe n'est jamais conservé

Inspiré du déverrouillage « Mi Unlock » ([`catalog/auth.py`](src/nwupdater/catalog/auth.py)) :

- Le login joue le formulaire Devise de `my.numworks.com` **en HTTPS** et ne conserve **que** le
  cookie `remember_user_token` (jeton Rails signé). **Le mot de passe n'est jamais écrit sur
  disque ni conservé en mémoire au-delà de la requête.**
- Alternative sans confier le mot de passe : l'utilisateur colle lui-même la valeur du cookie
  `remember_user_token` copiée depuis les DevTools de son navigateur.

#### 4.2 Stockage local traité comme un secret

- Jeton stocké dans `~/.config/nwupdater/credentials.json` (ou `$NWUPDATER_CONFIG_DIR` /
  `$XDG_CONFIG_HOME`).
- Permissions **`0600`** sur le fichier, **`0700`** sur le dossier : lisible par le seul
  propriétaire du compte système.
- **Révocable** : `nwupdater logout` / « Se déconnecter » supprime le fichier ; le jeton peut
  aussi être révoqué côté NumWorks.

#### 4.3 Destinataires : uniquement le serveur officiel

- Les identifiants et le jeton ne partent **que** vers `https://my.numworks.com`, sous la
  session de l'utilisateur. `nwupdater` **n'est pas un intermédiaire** : il ne relaie aucun
  identifiant vers un serveur de l'auteur (il n'en existe aucun).

#### 4.4 Surface réseau locale minimale et protégée

- La page web est servie par un serveur **lié à la boucle locale `127.0.0.1`** uniquement
  ([`server/httpd.py`](src/nwupdater/server/httpd.py)) — jamais exposé au réseau.
- **Anti-CSRF / anti-DNS-rebinding** : chaque appel `/api/` est filtré (`_guard`). L'en-tête
  `Host` doit être un nom de boucle locale (bloque le DNS-rebinding), et tout `Origin` présent
  doit correspondre à notre propre origine (bloque un POST depuis une page malveillante). Une
  requête cross-origin ou à `Host` étranger reçoit **403**. La boucle locale n'étant pas une
  frontière de sécurité suffisante quand un jeton y est stocké, ce contrôle ferme la brèche.
- Arrêt automatique sur inactivité (heartbeat), instance unique, aucune console.

#### 4.5 Minimisation (esprit RGPD)

- **Aucune** donnée personnelle collectée par l'auteur, **aucun** compte tiers, **aucun**
  traceur. La seule donnée sensible manipulée (le jeton) reste **entièrement locale**.

### 5. Cadre juridique invoqué

`nwupdater` se place sur le terrain du **droit à l'interopérabilité**, reconnu par :

- **France** — art. L.122-6-1, IV du Code de la propriété intellectuelle (décompilation admise
  pour l'interopérabilité) ;
- **Union européenne** — art. 6 de la directive 2009/24/CE sur la protection des programmes
  d'ordinateur ;
- **États-Unis** — clause d'interopérabilité du DMCA, §1201(f).

Point déterminant : l'outil **ne contourne aucune mesure technique de protection**. La signature
cryptographique du firmware n'est ni cassée ni éludée — elle est **transmise intacte** et
**vérifiée par la calculatrice elle-même**. L'outil se contente de parler le protocole DFU/DfuSe
que l'appareil publie de lui-même.

**Usage nominatif des marques** : « NumWorks » et « Epsilon » ne sont cités qu'à des fins
d'identification et d'interopérabilité (voir [DISCLAIMER](DISCLAIMER.md)). **Aucune garantie ni
responsabilité** n'est offerte : ce point est intégralement traité par le DISCLAIMER, non dupliqué
ici.

### 6. Engagements complémentaires et feuille de route

État des éléments identifiés lors de la conception, tenus à jour avec le code :

| # | Élément | État |
|---|---------|------|
| 1 | Anti-CSRF / anti-DNS-rebinding sur l'API locale (`Origin`+`Host`) | ✅ **implémenté** (§4.4) |
| 2 | Cadre juridique de l'interopérabilité invoqué | ✅ §5 |
| 3 | Réversibilité (le firmware officiel reste reflashable) | ✅ §3.2 — érigé en engagement |
| 4 | Versionnement daté de la déclaration | ✅ en-tête |
| 5 | **Empreinte SHA-256 du `.dfu`** journalisée (avec version/patch_level/taille) dans `~/.config/nwupdater/downloads.log`, pour prouver l'identité bit-à-bit avec la source officielle | ✅ **implémenté** ([download.py](src/nwupdater/catalog/download.py), CLI + API) |
| 6 | **Canal de divulgation responsable** pour tout problème de sécurité ou objection de l'ayant droit, avec engagement de réponse et de retrait | ✅ **implémenté** ([SECURITY.md](SECURITY.md)) |
| 7 | **Public mineur** — supervision adulte pour tout flashage (usage scolaire) | ✅ **implémenté** (DISCLAIMER, CLI, UI web) |
| 8 | **Auditabilité** — code ouvert (MIT) : chaque affirmation ci-dessus est vérifiable dans les sources, non simplement déclarative | ✅ intrinsèque |

> Tous les éléments ci-dessus sont désormais **implémentés** ; cette liste reste un registre
> vivant, tenu à jour avec le code — distinguer le fait de l'intention fait partie de la bonne foi.

### 7. Engagement

Les auteurs s'engagent à maintenir ces propriétés (non-altération, non-redistribution,
minimisation des données, préservation de la signature) et à **retirer ou corriger** l'outil à
la demande motivée de l'ayant droit. La présente déclaration vaut engagement ; **le code source,
ouvert, en est la preuve vérifiable.**

---

## English

### 1. Purpose and spirit of the project

`nwupdater` is an **independent, non-commercial, hobby** project with no affiliation whatsoever
to NumWorks SAS. Its sole purpose is **interoperability and the right to repair**: giving the
**owner** of a NumWorks calculator a way to update it and install third-party apps **without
depending on Chrome + WebUSB**, following the community Flipper Zero and Lunii updaters.

This declaration attests that the tool is designed and distributed **in good faith**:

- it **does not extract, redistribute or modify any proprietary** NumWorks binary;
- it **circumvents no technical protection measure** (the official firmware's cryptographic
  signature is **preserved intact**);
- it **exfiltrates no data** to the author or any third party;
- it acts **only** on hardware the user **owns**, with credentials that **belong to them**.

### 2. Operating prerequisites

By construction, the tool can only work when **all** of these conditions are met — which
guarantees it runs within a legitimate frame:

| Prerequisite | Detail | Why it is a safeguard |
|--------------|--------|------------------------|
| **Physical possession** | A genuine NumWorks calculator (Graphing N01xx or Scientific N02xx family) plugged in over USB by the user. | No remote action is possible; the operator is the owner. |
| **Personal NumWorks account** | The official firmware sits behind authentication (401 when anonymous). The user supplies **their own** credentials. | The tool neither hosts nor shares any binary: every byte comes from the official server, under the user's own session. |
| **Explicit consent** | Every write operation is triggered manually, after the warning is shown. | Nothing happens silently. |
| **Runtime** | Python 3; `pyusb`/`libusb` **only** to drive real hardware (production mode). | In demo mode (virtual device), no dependency and no USB at all. |
| **Standard protocol** | The calculator exposes a **standard** STM32 DFU/DfuSe mode (VID 0x0483). | No exploit, no vulnerability: we speak the protocol the device itself publishes. |

> Without a valid account **and** a plugged-in calculator, the tool does nothing but run in
> demonstration mode against an in-memory virtual device.

### 3. Data non-alteration — justification

#### 3.1 The official firmware is never modified

- The downloaded `.dfu` is a **complete DfuSe container signed by NumWorks**. `nwupdater` does
  **not reassemble, repackage or patch** it: it transmits it **byte for byte** to the calculator.
- Two integrity checks **before** any flashing
  ([`catalog/download.py`](src/nwupdater/catalog/download.py)):
  1. **size** compared against the one declared by the official manifest (`{model}/{channel}.json`);
  2. **format signature**: rejected if the bytes do not start with the `DfuSe` magic.
- A **SHA-256 fingerprint** of the binary is computed and logged (with version, patch level and
  size) in `~/.config/nwupdater/downloads.log`: verifiable proof of bit-for-bit identity with the
  official source.
- The **NumWorks cryptographic signature stays intact**: the calculator's bootloader verifies it.
  A tampered binary would in any case be **rejected by the device**.

#### 3.2 Writing is verified and non-destructive by default

- On dual-slot A/B devices (N0110/N0120), the tool flashes the **inactive slot** then switches
  the boot target — the running system is untouched until the new image is written
  ([`install/installer.py`](src/nwupdater/install/installer.py)).
- Every written segment is **read back and compared** (*read-back verify*, on by default); any
  mismatch raises a `VerificationError` and aborts the operation.
- **Reversibility**: the user can reflash the official firmware of their choice at any time via
  the same mechanism.

#### 3.3 Read-only reads of the device

- Identity detection (model, family, apps region) uses a **read-only** DFU read of `platforminfo`
  — no write is performed to identify the calculator.

#### 3.4 No alteration of the user's data… with an honest caveat

- The tool **collects, modifies and transmits no personal data** to the author or a third party.
  No telemetry.
- **Acknowledged caveat**: flashing a firmware **may erase the data present on the calculator**
  (scripts, notes). This is inherent to any firmware update, independent of this tool, and
  **clearly stated in the [DISCLAIMER](DISCLAIMER.md)**. Users are advised to back up first.

### 4. Data security

#### 4.1 "Bring-your-own-token" model — the password is never kept

Inspired by the "Mi Unlock" flow ([`catalog/auth.py`](src/nwupdater/catalog/auth.py)):

- Login plays the `my.numworks.com` Devise form **over HTTPS** and keeps **only** the
  `remember_user_token` cookie (a signed Rails token). **The password is never written to disk
  nor kept in memory beyond the request.**
- Alternative without handing over the password: the user themselves pastes the value of the
  `remember_user_token` cookie copied from their browser's DevTools.

#### 4.2 Local storage treated as a secret

- Token stored in `~/.config/nwupdater/credentials.json` (or `$NWUPDATER_CONFIG_DIR` /
  `$XDG_CONFIG_HOME`).
- Permissions **`0600`** on the file, **`0700`** on the directory: readable only by the owning
  system account.
- **Revocable**: `nwupdater logout` / "Sign out" deletes the file; the token can also be revoked
  on the NumWorks side.

#### 4.3 Recipients: the official server only

- Credentials and the token go **only** to `https://my.numworks.com`, under the user's own
  session. `nwupdater` **is not an intermediary**: it relays no credential to any author-run
  server (there is none).

#### 4.4 Minimal, protected local network surface

- The web page is served by a server **bound to loopback `127.0.0.1`** only
  ([`server/httpd.py`](src/nwupdater/server/httpd.py)) — never exposed to the network.
- **Anti-CSRF / anti-DNS-rebinding**: every `/api/` call is filtered (`_guard`). The `Host`
  header must be a loopback name (blocks DNS-rebinding), and any present `Origin` must match our
  own (blocks a POST from a malicious page). A cross-origin request or one with a foreign `Host`
  gets **403**. Since loopback alone is not a sufficient security boundary when a token is stored
  there, this control closes the gap.
- Automatic shutdown on inactivity (heartbeat), single instance, no console.

#### 4.5 Minimization (GDPR spirit)

- **No** personal data collected by the author, **no** third-party account, **no** tracker. The
  only sensitive datum handled (the token) stays **entirely local**.

### 5. Legal framework invoked

`nwupdater` stands on the ground of the **right to interoperability**, recognized by:

- **France** — art. L.122-6-1, IV of the Intellectual Property Code (decompilation allowed for
  interoperability);
- **European Union** — art. 6 of Directive 2009/24/EC on the legal protection of computer
  programs;
- **United States** — the interoperability clause of the DMCA, §1201(f).

The decisive point: the tool **circumvents no technical protection measure**. The firmware's
cryptographic signature is neither broken nor bypassed — it is **transmitted intact** and
**verified by the calculator itself**. The tool merely speaks the DFU/DfuSe protocol the device
publishes on its own.

**Nominative use of trademarks**: "NumWorks" and "Epsilon" are cited only for identification and
interoperability purposes (see [DISCLAIMER](DISCLAIMER.md)). **No warranty or liability** is
offered: that point is fully handled by the DISCLAIMER and not duplicated here.

### 6. Additional commitments and roadmap

Status of the items identified during design, kept in sync with the code:

| # | Item | Status |
|---|------|--------|
| 1 | Anti-CSRF / anti-DNS-rebinding on the local API (`Origin`+`Host`) | ✅ **implemented** (§4.4) |
| 2 | Interoperability legal framework invoked | ✅ §5 |
| 3 | Reversibility (official firmware stays reflashable) | ✅ §3.2 — raised to a commitment |
| 4 | Dated versioning of the declaration | ✅ header |
| 5 | **SHA-256 fingerprint of the `.dfu`** logged (with version/patch_level/size) in `~/.config/nwupdater/downloads.log`, to prove bit-for-bit identity with the official source | ✅ **implemented** ([download.py](src/nwupdater/catalog/download.py), CLI + API) |
| 6 | **Responsible disclosure channel** for any security issue or rights-holder objection, with a commitment to respond and withdraw | ✅ **implemented** ([SECURITY.md](SECURITY.md)) |
| 7 | **Minors** — adult supervision for any flashing (school use) | ✅ **implemented** (DISCLAIMER, CLI, web UI) |
| 8 | **Auditability** — open source (MIT): every claim above is verifiable in the sources, not merely declarative | ✅ intrinsic |

> All the items above are now **implemented**; this list remains a living register, kept in sync
> with the code — distinguishing fact from intent is part of good faith.

### 7. Commitment

The authors commit to maintaining these properties (non-alteration, non-redistribution, data
minimization, signature preservation) and to **withdraw or correct** the tool upon a motivated
request from the rights holder. This declaration stands as a commitment; **the open source code
is its verifiable proof.**
