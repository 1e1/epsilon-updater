# Authenticité du firmware & mode examen (« UNOFFICIAL SOFTWARE »)

Comment une calculatrice NumWorks décide **« officiel »** vs **« UNOFFICIAL SOFTWARE »**, et
comment ce verdict conditionne le **mode examen**. Analyse recoupée sur trois sources : le
**firmware Epsilon** (open source, tags 16.0.0–18.2.2 + master), le **flux WebUSB/DFU officiel**
(miroirs communautaires implémentant le même protocole que `my.numworks.com`), et des **tests sur
N0120 réelle**. Convention : **[source]** = lu dans le code, **[matériel]** = observé sur
l'appareil, **[fermé]** = logique dans le bootloader propriétaire, inférée.

## TL;DR

- « Officiel » est une **propriété cryptographique du slot** (QSPI externe), pas de la flash
  interne et pas un drapeau persistant. Chaque slot = `[SP HEADER | KERNEL | EXTRA | USERLAND |
  SIGNATURE]` ; le **bootloader** (flash interne `0x08000000`, clé publique gravée) vérifie une
  **signature Ed25519 (64 o) couvrant noyau+userland groupés** **à chaque démarrage à froid**.
- Vérification **100 % embarquée / hors ligne**. **Aucune** étape réseau. Le seul « en ligne » =
  télécharger une fois l'image déjà signée (`my.numworks.com/firmwares/<modèle>/<canal>.dfu`,
  protégé par compte).
- Le noyau garde un **`ClearanceLevel`** (`NumWorks` / `NumWorksAndThirdPartyApps` / `ThirdParty`)
  qui démarre à `NumWorks` et ne peut que **descendre**. Tout ce que le noyau en marche ne peut pas
  garantir cryptographiquement — typiquement un userland atteint par un **saut DFU** au lieu d'un
  boot à froid par le bootloader — est **forcé à `ThirdParty`**, ce qui déclenche le bandeau
  **« UNOFFICIAL SOFTWARE »** et désactive le mode examen.
- **Conséquence pratique** : flasher l'**image officielle signée** puis **redémarrer à froid**
  (RESET) rend l'appareil **officiel**, hors ligne. Le « UNOFFICIAL » n'apparaît que si on entre
  dans le slot par le **saut DFU** (`leave`) ; un boot à froid l'efface. Un firmware **non signé**
  reste « non officiel » (la signature ne se forge pas).

## 1. Le mécanisme de confiance

**Algorithme : Ed25519.** Étayé par `SingleSignatureLength = 64` (taille d'une signature Ed25519)
dans la config mémoire, et par la rétro-ingénierie communautaire du bootloader. La clé publique
(32 o) est **gravée dans le bootloader** ; elle n'est **pas** dans l'open source. **[source]/[fermé]**

**Ce qui est signé : le groupe `KERNEL + USERLAND` du slot.** Documenté dans le commentaire de
disposition mémoire de `shared/ion/src/device/include/n0110/config/board.h` (identique en
`n0120/`) :

```
|| SP HEADER | KERNEL A | EXTRA DATA | USERLAND A | SIGNATURE |
- SP HEADER: || SECURITY LEVEL | PAYLOAD LENGTH (SANS HEADER) ||
```

et confirmé par l'issue Epsilon #1866 (« the group kernel + userland signature is checked when
booting up »). La zone signature est réservée par l'éditeur de liens
(`shared/ion/src/device/userland/flash/userland_shared.ld`, section `.signature` remplie de `0xFF`
comme placeholder) ; la vraie signature est écrite ensuite par l'outil de signature (fermé) de
NumWorks. Un OS auto-compilé jamais signé garde `0xFF` → échec de vérification. **[source]**

Tailles (`n0110`/`n0120` `config/board.h`) : `SignedPayloadLength = 8` (en-tête SP),
`SingleSignatureLength = 64` (Ed25519), `NumberOfSignatures = 16` → `SignatureLength = 1024 o`
(zone multi-signatures réservée). **[source]**

## 2. Où apparaît « UNOFFICIAL SOFTWARE »

Le bandeau vit dans `ion/src/device/kernel/warning_display.cpp` (tag 18.2.2). Le déclencheur est
`switchExecutableSlot()` (`ion/src/device/n0110/kernel/drivers/board.cpp`) : **aucune crypto**, il
vérifie seulement le magic de l'en-tête userland et l'égalité de version, puis **rétrograde
inconditionnellement en `ThirdParty` et affiche le bandeau**. La machine d'état de clairance
(`authentication.cpp`) est **à sens unique** (`downgradeClearanceLevelTo`, l'assert impose
`level > courant`) et coupe la LED pour le code non fiable. **[source]**

Point clé : **le noyau n'a pas la clé et ne vérifie aucune signature.** Quand un userland est
atteint par la sortie DFU (`shared/ion/src/device/shared/usb/calculator_userland_leave.cpp` →
`Board::updateClearanceLevelForUnauthenticatedUserland` → `ThirdParty`), il est marqué non
authentifié **par principe** (« je n'ai pas boot-vérifié ce slot »). L'état officiel est donc
**re-dérivé à chaque boot à froid par le bootloader** — ce n'est pas un bit collant. **[source]**

## 3. Pas d'attestation en ligne

Le flux WebUSB officiel est une transaction **purement locale** WebUSB → DFU sur un `.dfu`
**pré-signé** téléchargé une fois. Recherche `fetch`/`XMLHttpRequest`/`WebSocket`/`http(s)://` dans
tous les fichiers du flux (miroirs `Omega-Numworks/numworks.js`, `M4xi1m3/webdfu_numworks`) :
**rien de réseau** pendant le flash ; seuls des `navigator.usb.*`. Aucune inscription d'appareil,
aucun challenge de signature, aucun certificat par appareil. Le seul contact serveur = le
**téléchargement** du `.dfu` (401 si non connecté = auth de fichier, pas attestation). **[source]**

Séquence : régions **externes d'abord** (slots QSPI, sans reboot), **flash interne en dernier**
(avec le *leave*/reboot). `flashExternal` → `do_download(..., false)` ; `flashInternal` →
`do_download(..., true)`. Le stockage utilisateur n'est pas touché par le flash firmware. **[source]**

## 4. Sélection A/B au démarrage à froid

Faite par le **bootloader fermé**. L'open source ne contient ni compteur de boot ni sélecteur
persistant. Les deux slots sont symétriques (`SlotAOffset = 0` → `0x90000000` ;
`SlotBOffset = ExternalFlashLength/2` → `0x90400000`), chacun un payload signé autonome. Le code
en marche sait dans quel slot il tourne **par sa propre adresse** (`isRunningSlotA()`,
`board_dual_slots.cpp`). La RE communautaire décrit : le bootloader **valide le slot bas d'abord ;
sinon le slot haut ; sinon recovery/DFU**. **[source]/[fermé]**

**[matériel N0120]** À version égale (A et B en 25.2.0), le bootloader boote **A (slot bas)** —
observé deux fois (flash de B puis RESET → A ; flash de A puis RESET → A). Il ne persiste aucun
sélecteur : rebrancher l'USB ne suffit pas (l'appareil reste sur batterie, jamais redémarré à
froid) ; seul le bouton **RESET** (ou une extinction) provoque un vrai boot à froid.

## 5. Mode examen : conditionné au verdict

Le mode examen est une config 16 bits (`ExamMode::Configuration`) stockée dans les *persisting
bytes* du slot. Le gating est explicite dans `shared/ion/src/shared/exam_mode.cpp` : si
`clearanceLevel() == ThirdParty`, `get()` renvoie `Off` et `set(actif)` fait un `Reset::core()`
(→ le bootloader reboote le slot **officiel**, qui peut alors entrer en mode examen). Renforcé
côté apps (`settings/main_controller.cpp` `hideExamModes()` pour `ThirdParty` ;
`apps_container.cpp` force `Off` après DFU si clairance ≠ `NumWorks`). Autrement dit : **un
firmware non officiel ne peut pas être en mode examen actif.** **[source]**

## 6. Constats matériels (N0120 réelle)

| Test | Action | Écran | Interprétation |
|---|---|---|---|
| A | Flash slot inactif (octets officiels 25.2.0, vérif octet-exact) | — | Slot actif intact ; rien booté |
| B | `leave` (saut DFU) vers le slot flashé | **UNOFFICIAL SOFTWARE** | Noyau rétrograde le slot atteint par saut |
| C | **RESET** (boot à froid) | **pas de bandeau** (officiel) | Bootloader re-vérifie la signature → `NumWorks` |
| D | Lecture du slot actif après RESET | slot **A** | Sélection bas-d'abord à version égale |

Conclusion matérielle : **le « UNOFFICIAL » venait du saut DFU, pas des octets.** Les mêmes octets
officiels signés bootent **officiel** dès qu'on passe par un **boot à froid**.

## 7. Implications pour nwupdater

- **MàJ hors ligne vers un firmware officiel conforme examen : FAISABLE.** Conditions : (1) image
  **officielle signée** (téléchargée via `catalog.download`, jamais un binaire modifié) ; (2)
  entrer dans le slot par un **boot à froid** (RESET / extinction), **pas** par le `boot()` in-app
  (saut DFU).
- **`boot()` (`_session_firmware.py`)** fait un saut DFU → « UNOFFICIAL » **transitoire**. Après un
  flash firmware, l'UI doit orienter vers un **RESET** (cf. `fw_reboot`/`exam_warn`), pas le saut.
- **On ne peut pas signer.** Un firmware custom/modifié restera « non officiel » — c'est le design
  (intégrité examen), et c'est correct.
- **Mode classe** : le flash « en un clic » depuis le cache (image officielle, sans auto-boot) est
  compatible « officiel » à condition que l'élève **redémarre à froid** ensuite.

## 8. Limites / zones fermées

La **routine de vérification Ed25519**, la **clé publique/privée** et la **logique de sélection A/B
+ recovery** sont dans le **bootloader propriétaire** (`numworks/epsilon-bootloader`, privé) :
algorithme = Ed25519 et « signé sur noyau+userland » sont établis par la taille 64 o, les
commentaires de disposition, l'issue #1866 et la RE communautaire, mais le vérifieur n'a pas pu
être lu directement. Le rôle exact de `NumberOfSignatures = 16` et l'ordre de priorité A/B précis
ne sont pas confirmés en source.

## Sources

- Firmware : [numworks/epsilon](https://github.com/numworks/epsilon) — `config/board.h`,
  `userland_shared.ld`, `warning_display.cpp`, `authentication.cpp`, `board.cpp`
  (`switchExecutableSlot`), `calculator_userland_leave.cpp`, `exam_mode.cpp`,
  `board_dual_slots.cpp` (tags 16.0.0–18.2.2 + master) ; issue
  [#1866](https://github.com/numworks/epsilon/issues/1866).
- Flux WebUSB : `Omega-Numworks/numworks.js` (`Numworks.js`, `Storage.js`, `Recovery.js`) ;
  `M4xi1m3/webdfu_numworks` (`dfu.js`, `dfuse.js`, `dfu-util.js`) — même protocole que
  `my.numworks.com`.
- Matériel : tests N0120 réelle (juillet 2026), cf. table §6 et
  [../03-transfer-install/implementation.md](../03-transfer-install/implementation.md).
