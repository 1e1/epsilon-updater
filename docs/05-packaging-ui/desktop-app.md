# Lot 5 — App double-clic (macOS / Windows / Linux)

Objectif : lancer l'updater **par un double-clic**, sans terminal, **sans compte payant**
Apple/Microsoft (donc **binaires non signés**).

## Trois façons de l'obtenir

### 1. Récupérer l'app prête à l'emploi (recommandé) — zéro commande locale
La CI GitHub (`.github/workflows/build-apps.yml`) compile les 3 plateformes à chaque push
et à chaque tag `vX.Y.Z`. On télécharge le `.zip` de son OS depuis :
- l'onglet **Actions** → le run → **Artifacts**, ou
- la **Release** (si on a poussé un tag `git tag v0.1.0 && git push --tags`).

### 2. Compiler en local (une commande) — nécessite Python + PyInstaller
```bash
pip install pyinstaller pillow .
python packaging/icon/generate_icons.py --arrow up   # icônes .icns/.ico/.png
pyinstaller packaging/nwupdater.spec --noconfirm     # -> dist/
```
Résultat dans `dist/` : `NumWorks Updater.app` (macOS) · `NumWorks Updater.exe` (Windows) ·
`NumWorks Updater` (Linux).

### 3. Lanceurs zéro-build (si Python est déjà installé)
Doubles-clics sans rien compiler (`packaging/launchers/`) :
- macOS : `NumWorks Updater.command` (1ère fois : clic droit → Ouvrir)
- Windows : `NumWorks Updater.bat`
- Linux : `numworks-updater.desktop`

## Premier lancement d'un binaire NON signé (le « développeur non identifié »)

Aucun compte payant → l'OS affiche un avertissement **une seule fois** :

| OS | Message | Contournement (une fois) |
|----|---------|--------------------------|
| macOS | « développeur non identifié » | **Clic droit → Ouvrir** → Ouvrir. (ou `xattr -dr com.apple.quarantine "NumWorks Updater.app"`) |
| Windows | « Windows a protégé votre PC » (SmartScreen) | **Informations complémentaires → Exécuter quand même** |
| Linux | — | `chmod +x "NumWorks Updater"` puis lancer (selon le gestionnaire de fichiers) |

## Comportement de l'app

- Démarre le serveur local sur un **port libre** (127.0.0.1) et **ouvre le navigateur**.
- **Instance unique** : un 2ᵉ double-clic ne relance pas de serveur — il **rouvre l'onglet**
  de l'instance déjà lancée (détectée via un fichier `instance.json` + sonde `/api/ping`).
- **Arrêt automatique sur inactivité** : la page envoie un *heartbeat* (`/api/ping`) toutes
  les 30 s tant que l'onglet est ouvert. Onglet/navigateur fermé → plus de heartbeat → le
  serveur **s'arrête seul** après le délai d'inactivité (**15 min** par défaut,
  `NWUPDATER_IDLE_TIMEOUT` en secondes, `0` pour désactiver).
- Fenêtre sans console (`console=False`). Arrêt manuel : bouton **Quitter** dans la page
  (`POST /api/quit`), ou fermer le processus.
- **USB réel** : l'app **détecte une vraie calculatrice** au démarrage (`pyusb` + `libusb`
  bundlés via `libusb-package`). Si aucune n'est branchée (ou `NWUPDATER_DEMO=1`), elle bascule
  automatiquement en **démo virtuelle** (badge DÉMO). Le bouton « Capturer la séquence »
  fonctionne donc sur le vrai matériel dans l'app packagée.

> Réglages équivalents en CLI : `nwupdater ui --single-instance --idle-timeout 900`.

## Icône

- Source : `packaging/icon/icon.svg` + `generate_icons.py` (dessin vectoriel du « N », sans
  dépendance de police) → `icon.icns` (macOS), `icon.ico` (Windows), `icon_256.png` (Linux).
- Changer le sens de la flèche : `generate_icons.py --arrow down`.

## Pourquoi PyInstaller (et pas un simple script)

Un binaire PyInstaller **embarque Python** → l'utilisateur final n'a **rien à installer**.
On ne peut pas cross-compiler : chaque OS se compile sur sa propre machine — d'où la **CI
multi-OS** qui évite d'avoir un Mac + un PC + un Linux sous la main.
