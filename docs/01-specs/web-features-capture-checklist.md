# Découverte des fonctions web — checklist de capture

> Projet indépendant, non officiel. On capture le dialogue de l'**app officielle** (Chrome +
> my.numworks.com) pour comprendre appairage / scripts / apps / MAJ, afin de les réimplémenter
> en headless. Connexion avec **ton vrai compte NumWorks**.

## Outil

Exécutable `nwupdater-capture` (packagé via GitHub — voir « Packaging » plus bas) :

```
nwupdater-capture serve                 # page locale : installe le userscript + checklist
# … tu joues les scénarios dans Chrome ; la capture est CONTINUE ; Ctrl-C → capture.json …
nwupdater-capture scrub capture.json --value TON_EMAIL   # enlève tes données perso
nwupdater-capture analyze capture.scrubbed.json          # carte d'API par fonctionnalité
```

La capture se fait **dans le navigateur**, en continu, via un **userscript** (Tampermonkey /
Violentmonkey) qui s'injecte automatiquement sur `*.numworks.com` (hooks `fetch`/XHR +
`navigator.usb`) et **pousse chaque trame au fil de l'eau vers `nwupdater-capture serve`**. Le
**serveur est le magasin durable** → rien n'est perdu quand tu changes de page. Le userscript ne
lit pas les cookies (httpOnly) et caviarde les champs sensibles.

> **Pourquoi un userscript et pas un bookmarklet ?** Le bookmarklet perd tout à chaque
> changement de page (il faut le re-cliquer). Le userscript s'injecte tout seul sur chaque page
> et la capture ne s'interrompt jamais. (Le bookmarklet `/capture-hook.js` reste dispo en repli
> mono-page.)

## Installation (une fois, sur le Mac de test)

1. Lance `nwupdater-capture serve` (double-clic ou terminal) → une page locale s'ouvre.
2. Installe l'extension **Tampermonkey** (ou Violentmonkey) dans Chrome/Firefox.
3. Sur la page locale, clique **« Installer nw-capture »** → Tampermonkey propose l'installation
   → *Installer*. Autorise l'accès à `127.0.0.1` quand il le demande (c'est pour envoyer les
   trames à l'exécutable local).

## Procédure

1. Ouvre `my.numworks.com` et **connecte-toi** (ton vrai compte). Le panneau « capture continue »
   apparaît en bas à droite — **la capture tourne déjà**.
2. Avant **chaque** étape, choisis le **scénario** dans le panneau (ça pose une marque). Ensuite
   navigue/agis librement : les trames sont estampillées du scénario courant, sans rien perdre
   entre les pages. Bouton **Pause/Reprendre** si besoin.
3. Déroule la checklist ci-dessous.
4. Terminé : **Ctrl-C** dans le terminal de `serve` → `capture.json` est écrit.
5. `nwupdater-capture scrub capture.json --value TON_EMAIL` puis envoie-moi `capture.scrubbed.json`.

## Checklist des scénarios (ordre conseillé)

Colonnes **N01xx** (Graphique) / **N02xx** (Scientifique) = le scénario s'applique-t-il à ce
modèle. La N02xx est l'édition **sans Python** → seuls appairage + MAJ (+ désappairage) existent ;
tout le reste (scripts, apps) est **spécifique N01xx**.

| # | Scénario (id panneau) | Action à faire | N01xx | N02xx | Écrit sur la calc ? |
|---|---|---|:--:|:--:|---|
| 1 | `pair` — **Appairage** | brancher la calc, la lier au compte | ✅ | ✅ | non (lecture id) |
| 2 | `scripts-list` — **Lister scripts** | ouvrir la liste des scripts Python | ✅ | ❌ pas de Python | non |
| 3 | `scripts-read` — **Lire un script** | ouvrir/éditer le contenu d'un script | ✅ | ❌ | non |
| 4 | `scripts-edit` — **Créer/pousser** | créer/modifier un script, le **synchroniser** | ✅ | ❌ | **oui** |
| 5 | `apps-list` — **Lister apps** | apps intégrées + état d'activation | ✅ | ❌ pas d'apps | non |
| 6 | `app-install` — **Charger une app** | installer une app externe | ✅ | ❌ | **oui** |
| 7 | `app-delete` — **Supprimer une app** | désinstaller l'app de l'étape 6 | ✅ | ❌ | **oui** |
| 8 | `updates-list` — **Lister MAJ** | afficher les MAJ dispo — **NE PAS appliquer** | ✅ | ✅ | non |
| 9 | `unpair` — **Désappairage** | délier du compte (**à la fin** : invalide la session) | ✅ | ✅ | ? |
| — | `other` — **Autre** | exploration (renommer, mode examen, sauvegarde…) | ✅ | ✅ | ? |

**N02xx** (déjà capturé) : seuls `pair`, `updates-list`, `unpair` sont pertinents.
**N01xx** : tous les scénarios (a Python + apps) — **restant à capturer** (aucune Graphique testée à ce jour).

Note : les étapes 4/6/7 **écrivent** sur la calculatrice (scripts/apps) — c'est voulu et
réversible. Ne **pas** appliquer de mise à jour firmware.

## ⚠️ Compte réel

Le dump contiendra ton email, n° de série, contenu de scripts. **Toujours passer `scrub`
avant de partager.** Les secrets (mot de passe, CSRF, cookies) sont déjà exclus par le hook.

## Packaging (pour l'agent packaging)

- Entrée console : **`nwupdater-capture = "nwupdater.tools.capture_cli:main"`**.
- Donnée à embarquer : `nwupdater/tools/web/capture-hook.js` (package-data `nwupdater.tools`
  = `web/*.js`).
- Cibles demandées : **macOS Intel (x86_64) au minimum** ; bienvenus aussi macOS arm64/universal2,
  Linux, Windows. Stdlib pur → PyInstaller sans dépendance lourde.
- Rien à signer côté USB (la capture passe par le navigateur, pas par libusb).
