# Sources & références

## Officiel NumWorks
- Site / produit : https://www.numworks.com/ — un seul produit (graphing calculator).
- Simulateur en ligne : https://www.numworks.com/simulator/ (télécharger : `/simulator/download/`)
- Workshop / mise à jour (WebUSB) : https://my.numworks.com — landing page annoncée par le descripteur WebUSB de la calculatrice.
- Support update : https://www.numworks.com/support/handheld/update/
- Specs techniques : https://www.numworks.com/engineering/specs/
- Blog « Writing a device updater? Consider WebUSB! » : https://www.numworks.com/blog/webusb-firmware-update/
- Code source : https://github.com/numworks/epsilon (fork local dans ce workspace)

## Protocole DFU / implémentations hôte (à réimplémenter sans WebUSB)
- **webdfu_numworks** (fork WebDFU pour NumWorks) : https://github.com/TI-Planet/webdfu_numworks — démo live : https://ti-planet.github.io/webdfu_numworks/n0110/
- Autres forks : quentinguidee, daitangio, M4xi1m3, Itai12 (mêmes bases).
- Documentation DFU communautaire tierce (rétro-ingénierie indépendante du protocole).
- Flasher Python officiel du repo : `tools/device/dfu.py` (implémente DFU/DfuSe via pyusb, sans dfu-util).
- Spec USB DFU 1.1 + ST AN3156 (protocole DFU STM32) + UM0391 (format DfuSe).

## Communauté / hardware
- TI-Planet (news N0120, specs) : https://tiplanet.org/forum/
- Cemetech (révisions hardware) : https://www.cemetech.net/forum/
- Wikipedia NumWorks : https://en.wikipedia.org/wiki/NumWorks
- OS alternatifs (contexte) : Omega (getomega.dev), Upsilon.

## Références internes au repo `epsilon`
- Côté device (vérité du protocole) : `shared/ion/src/device/shared/usb/` (`calculator.h`, `dfu_interface.cpp`, `stack/descriptor/*`).
- Config par modèle : `shared/ion/src/device/include/{n0110,n0115,n0120}/config/`.
- Simulateur (USB stub) : `shared/ion/src/simulator/shared/usb.cpp` (vide), `shared/ion/src/shared/dummy/usb.cpp`.
- Docs firmware : `epsilon/docs/`, `epsilon/external_apps/README.md`.

> Convention : distinguer **[confirmé]** (lu/vérifié dans une source) de **[inféré]**.
