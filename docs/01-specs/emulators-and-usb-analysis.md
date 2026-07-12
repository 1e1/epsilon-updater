# Lot 1 — Émulateurs & analyse de la communication USB

> **La question centrale du Lot 1** : « il existe des émulateurs sur le site officiel,
> comment les reconstituer localement pour analyser la communication USB de la
> calculatrice ? »

## Constat majeur : l'émulateur officiel n'a PAS d'USB

L'émulateur en ligne (`numworks.com/simulator/`) et le simulateur desktop sont **le même
code** que l'OS, compilé pour la cible `simulator` (desktop natif via SDL, ou web via
Emscripten/WASM). Or, sur cette cible, **la couche USB est un stub vide** :

- `shared/ion/src/simulator/shared/usb.cpp` → **fichier de 0 octet**.
- L'implémentation réellement liée est `shared/ion/src/shared/dummy/usb.cpp` : `isPlugged()`,
  `DFU()`, `enable()`… sont des **no-ops**.
- Tout le protocole DFU/DfuSe (`shared/ion/src/device/shared/usb/…`) n'est compilé que pour
  la cible **device** (STM32 / ARM), jamais pour le simulateur.

**Conséquence** : on ne peut PAS capturer un dialogue USB en lançant l'émulateur officiel.
L'émulateur sert à exécuter l'OS (écran, clavier, apps), pas à parler USB. La « vérité
terrain » du protocole USB est donc :

1. Le **code source device** (`shared/ion/src/device/shared/usb/`) — descripteurs +
   machine à états DFU. C'est notre référence d'implémentation.
2. Les **implémentations hôte open-source** (webdfu_numworks, `tools/device/dfu.py`) — le
   côté ordinateur, que l'on réimplémente.

Voir le protocole détaillé dans [usb-dfu-protocol.md](usb-dfu-protocol.md).

## À quoi sert quand même de reconstituer l'émulateur

- **Générer des artefacts de firmware** : builder l'OS (device *et* simulateur) donne des
  binaires `.bin`/`.dfu` réels à utiliser comme charge utile de test pour les Lots 3/4.
- **Comprendre l'app `usb`** : l'écran « branchez à un ordinateur » (`apps/usb`) montre le
  déclenchement du mode DFU côté OS.
- **Comparer les descripteurs** : on lit dans le code exactement quels descripteurs la vraie
  calculatrice renverra, pour que notre **appareil virtuel** soit fidèle.

### Reconstituer l'émulateur localement

```shell
# Simulateur desktop (SDL)
make PLATFORM=simulator clean
make -j8 PLATFORM=simulator epsilon.app.run

# Simulateur web (WASM, = l'émulateur en ligne) — nécessite emsdk 4.0.10 (.emsdk-version)
make PLATFORM=simulator PLATFORM=web ...   # cf. shared/ion/src/simulator/web
```

Le SDK s'installe via `tools/setup.sh`. Toolchain épinglée : `.tool-versions`
(node 22.14.0, ruby 2.7.2) et `.emsdk-version` = `4.0.10`. À isoler dans **Docker** pour la
reproductibilité (voir plus bas).

## Stratégie retenue : un APPAREIL DFU VIRTUEL (jamais d'USB réel)

Puisqu'on ne doit jamais brancher de calculatrice, et que l'émulateur officiel ne fait pas
d'USB, on développe l'updater contre un **périphérique USB DFU virtuel** qui imite fidèlement
les descripteurs et la machine à états de la vraie calculatrice. Trois niveaux de fidélité,
du plus simple au plus réaliste :

### Niveau 1 — Mock applicatif (au niveau des transferts DFU) ⭐ point de départ

Un objet Python/natif qui expose la **même interface que `usb.core.Device`** de pyusb
(`ctrl_transfer`, `read`, `write`) et implémente la machine à états DFU. Le moteur DFU de
l'updater parle à ce mock au lieu d'un vrai bus USB.

- ✅ Zéro privilège, tourne partout (macOS inclus), tests unitaires rapides.
- ✅ Suffit pour développer et valider **toute la logique** des Lots 3/4 (set address,
  erase, dnload, upload, getstatus, detach) et modéliser deux slots + platforminfo.
- ❌ Ne valide pas l'énumération USB réelle ni les drivers OS.

### Niveau 2 — Gadget USB virtuel Linux (dummy_hcd + configfs/gadgetfs) dans Docker

Le module noyau `dummy_hcd` crée une **paire hôte/périphérique USB 100 % logicielle** ; via
`configfs`/`FunctionFS` on implémente une fonction DFU qui renvoie exactement les descripteurs
de `calculator.h`. Le périphérique apparaît alors comme un vrai device sur un vrai bus
virtuel — `libusb` le voit, et on peut **capturer avec `usbmon` + Wireshark/tshark**.

- ✅ Énumération USB réelle, capture pcap authentique, valide libusb côté hôte.
- ✅ Reproductible en conteneur Linux.
- ❌ Nécessite un noyau Linux avec `dummy_hcd`/`gadgetfs` et un conteneur **privilégié** ;
  sur macOS il faut une VM Linux (Docker Desktop en fournit une, mais le chargement de
  modules noyau y est limité → prévoir une VM Linux dédiée, p.ex. lima/UTM).

### Niveau 3 — Firmware device recompilé en périphérique QEMU / USB/IP

Faire tourner le vrai code USB device (`shared/ion/src/device/shared/usb/`) hors STM32, soit
émulé sous **QEMU** (machine STM32), soit exposé via **USB/IP**. Fidélité maximale (c'est le
vrai code), mais coût d'ingénierie élevé.

> **Décision** : on démarre au **Niveau 1** (mock applicatif) pour dérisquer toute la logique
> des Lots 3/4 vite et sur macOS, puis on ajoute le **Niveau 2** en Docker pour valider
> l'énumération/capture réelle. Le Niveau 3 reste optionnel.

## Capturer le dialogue USB « de référence » sans hardware

On veut un pcap de référence du dialogue Workshop↔calculatrice. Sans hardware réel, on
l'obtient en **branchant notre updater (ou webdfu) sur l'appareil virtuel Niveau 2** et en
capturant avec `usbmon` :

```shell
# dans le conteneur/VM Linux
modprobe usbmon
tshark -i usbmonX -w /captures/dfu-session.pcapng
```

Les captures vont dans [`../reference/captures/`](../reference/captures/).

## Environnement Docker (esquisse)

- `docker/emulator-build/` — image avec emsdk 4.0.10 + node 22.14 + ruby 2.7.2 +
  arm-none-eabi pour builder OS et artefacts `.dfu`/`.bin`.
- `docker/virtual-dfu/` — image Linux privilégiée avec `dummy_hcd`, `gadgetfs`/configfs,
  `usbmon`, `tshark`, `libusb` pour le périphérique virtuel Niveau 2 + capture.

À implémenter dans le Lot 1 (livrable outillage). Voir
[../00-overview/roadmap.md](../00-overview/roadmap.md).
