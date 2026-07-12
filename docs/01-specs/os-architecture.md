# Lot 1 — Architecture de l'OS Epsilon

Source : lecture du firmware `epsilon` (fork local), notamment
`shared/ion/src/device/include/n0110/config/board.h`, `.../internal_flash.h`,
`shared/ion/src/device/shared/usb/*`, et `epsilon/docs/`.

## Vue d'ensemble

Epsilon est l'OS des calculatrices NumWorks (~11 apps de maths). Le code est organisé en
couches :

- **Poincaré** — moteur de calcul symbolique / mathématique.
- **Escher** — framework UI.
- **Ion** — couche d'abstraction matérielle (HAL). C'est ici que vit tout le code USB/DFU.
  - `shared/ion/src/device/…` → cible **matériel réel** (STM32, ARM Cortex-M). **C'est la
    seule cible qui implémente réellement l'USB/DFU.**
  - `shared/ion/src/simulator/…` → cible **simulateur** (desktop + web/WASM). L'USB y est
    un **stub vide** (voir [emulators-and-usb-analysis.md](emulators-and-usb-analysis.md)).
- **apps/** — les applications (dont `apps/usb` qui affiche l'écran « branchez à un
  ordinateur » et déclenche le mode DFU).

## Chaîne de démarrage (modèles N0110 et +)

Architecture **secure-boot à double slot** introduite avec le stockage flash externe :

```
Reset ──▶ Bootloader ST (ROM)
       └▶ Bootloader NumWorks (flash interne)
          └▶ vérifie la signature du "Signed Payload" du slot actif (A ou B)
             └▶ Kernel (privilégié)
                └▶ Userland (non privilégié, apps + Python)
```

- **Bootloader** : en flash interne, occupe quasiment tout (voir carte mémoire). Rôle :
  choisir/valider le slot, entrer en DFU, sauter vers le kernel.
- **Kernel** : code privilégié minimal (drivers, MPU, exceptions). Relocalisé en SRAM au
  boot (contraintes VTOR).
- **Userland** : le gros de l'OS (apps, Poincaré, Python), s'exécute non privilégié sous
  protection MPU.

Cette séparation kernel/userland + signature est ce qui permet à NumWorks de distinguer un
firmware **officiel signé** d'un **firmware tiers** : un tiers ne peut pas signer, donc le
mode examen est verrouillé et tout reset/crash restaure l'officiel.

## Slots A / B (flash externe, N0110+)

La flash externe QSPI de **8 MiB** est coupée en **deux slots identiques** (A et B) de
4 MiB. On flashe toujours le slot **inactif**, puis on bascule — c'est un update
« atomique » qui ne peut pas laisser la calculatrice dans un état non bootable.

Layout d'un slot (d'après `board.h`) :

```
|            SLOT (4 MiB)                                            |
| 64K            | 64K/0      | 61~62 × 64K            | 64K         |
|      SIGNED PAYLOAD A                | EXTERNAL APPS | PERSISTING  |
| SP HEADER|KERNEL A | EXTRA DATA | USERLAND A | SIGN. |            BYTES |
```

- **SP HEADER** : `SECURITY LEVEL | PAYLOAD LENGTH`.
- **KERNEL** : `HEADER | INIT VECTOR | CODE | 0b111…1`.
- **USERLAND** : `HEADER | INIT VECTOR | CODE`.
- **EXTERNAL APPS** : zone réservée aux **applications tierces** (~61–62 × 64K). C'est là
  que le Lot 4 installe les apps récupérées du store.
- **PERSISTING BYTES** : 64K persistants (device name, etc.).
- **SIGNATURE** : 16 signatures de 64 octets (`SignatureLength = 64 × 16`).

Le **header** (kernel/userland) contient les infos que l'hôte lit par DFU pour connaître
version, commit, etc. → c'est la brique « platforminfo » (voir
[usb-dfu-protocol.md](usb-dfu-protocol.md)).

## Carte mémoire N0110 (référence)

| Zone | Adresse | Taille | Notes |
|------|---------|--------|-------|
| Flash interne (AXIM) | `0x08000000` | `0x10000` (64 KiB) | Bootloader (56K) + trampoline (8K) |
| Bootloader (ITCM) | `0x00200000` | 56 KiB | Alias ITCM du même flash |
| Bootloader ST (ROM) | `0x00100000` | — | System bootloader STM32 (DFU usine) |
| Flash externe QSPI | `0x90000000` | `0x800000` (8 MiB) | Slots A/B + apps + persist |
| Slot A | `0x90000000` | 4 MiB | `SlotAOffset = 0` |
| Slot B | `0x90400000` | 4 MiB | `SlotBOffset = ExternalFlashLength/2` |
| Kernel (virt.) | `0x90000000` | 64 KiB | Début de slot |
| SRAM | `0x20000000` | `0x40000` (256 KiB) | Data/BSS/heap/stack userland + kernel |
| Flasher (SRAM) | `0x20030000` | 64 KiB | `FlasherOffset = SRAMLength - 64K` — code de flash chargé en RAM |

Secteurs flash interne (`internal_flash.h`) : `0x08000000, 0x08004000, 0x08008000,
0x0800C000, 0x08010000` → 4 secteurs de 16 KiB.

> Les tailles diffèrent légèrement pour N0100 (pas de flash externe) et pour N0115/N0120
> (mêmes 8 MiB externes, mais MCU différent). Voir
> [hardware-variants.md](hardware-variants.md).

## Ce que ça implique pour l'updater

1. **Lecture d'identité** = un `DFU_UPLOAD` depuis l'adresse du header/platforminfo → on
   obtient modèle + version sans rien écrire (safe, lecture seule).
2. **Update OS** = écrire le nouveau *signed payload* dans le slot inactif via
   `DFU_DNLOAD` + `set address pointer`, puis `detach`/jump.
3. **Apps tierces** = écrire dans la zone EXTERNAL APPS du slot actif.
4. Le double-slot rend le développement **plus sûr à mocker** : notre appareil virtuel doit
   modéliser deux slots et un pointeur d'adresse.
