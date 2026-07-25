# Objectif & contraintes

## But

Créer un **utilitaire de mise à jour** pour les calculatrices NumWorks qui fonctionne
**sans navigateur Chrome et sans WebUSB**. Aujourd'hui NumWorks impose la mise à jour via
son « Workshop » web (`my.numworks.com`) qui utilise **WebUSB** — une API disponible
uniquement sur Chrome / Chromium / Edge. On veut un outil autonome.

L'utilitaire doit :

1. Détecter le modèle de calculatrice branchée (Graphique / Scientifique + révision
   hardware N0100/N0110/N0115/N0120) et la version d'OS installée.
2. Lister les mises à jour disponibles (catalogue).
3. Récupérer et installer une mise à jour de firmware.
4. Récupérer et installer des applications tierces.
5. Exposer tout ça via une **page web locale** ouverte dans le navigateur système
   (le cœur reste un module *headless* natif qui parle USB).

## Contraintes imposées

- **JAMAIS d'USB réel.** Tout le développement et les tests se font contre des appareils
  **virtuels / mockés** (voir [../01-specs/emulators-and-usb-analysis.md](../01-specs/emulators-and-usb-analysis.md)).
- **Docker autorisé** (utile pour le gadget USB virtuel Linux, la capture usbmon, et les
  builds reproductibles).
- Documentation récupérable sur le site officiel NumWorks et ses dépôts Git.
- Compte de test NumWorks fourni (pour explorer le Workshop / les apps). On ne pilote pas
  un navigateur réel avec ; on documente les endpoints.

## Modèle d'architecture visé

```
┌──────────────────────────────────────────────────────────────────┐
│  Navigateur système (n'importe lequel)                            │
│   ↕ HTTP localhost                                                │
│  Page web locale (UI de sélection MàJ / apps)   ← Lot 5           │
└──────────────────────────────────────────────────────────────────┘
                     ↕ (API locale REST/WebSocket)
┌──────────────────────────────────────────────────────────────────┐
│  Cœur headless natif (libusb)                                     │
│   • Client catalogue MàJ   ← Lot 2   • Apps tierces   ← Lot 4     │
│   • Moteur DFU/DfuSe (flash, upload, detach)   ← Lot 3            │
└──────────────────────────────────────────────────────────────────┘
                     ↕ USB (réel en prod, VIRTUEL en dev/test)
┌──────────────────────────────────────────────────────────────────┐
│  Calculatrice NumWorks  /  Appareil DFU virtuel (dev)            │
└──────────────────────────────────────────────────────────────────┘
```

Le point-clé : plutôt que de reposer sur un flashage web (WebUSB / WebSerial), tout l'USB est
piloté par le cœur natif ; on garde une UI web, mais servie en local pour l'ergonomie — sans
dépendre de WebUSB.

## Pourquoi c'est faisable

La calculatrice n'expose pas un protocole propriétaire opaque : elle est un **périphérique
DFU / DfuSe standard** (le même que le bootloader STM32), enrichi de descripteurs WebUSB.
Tout le dialogue « bas niveau » est de la **lecture/écriture d'adresses mémoire** via les
commandes DFU. On peut donc le rejouer avec `libusb` (ou pyusb) sans navigateur. Détails :
[../01-specs/usb-dfu-protocol.md](../01-specs/usb-dfu-protocol.md).
