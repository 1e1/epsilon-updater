# Fixtures — réponses réelles de my.numworks.com

Réponses HTTP **authentiques** capturées une fois depuis `my.numworks.com`, pour que les
tests auth/download rejouent des payloads réels **hors-ligne** (aucun appel réseau, aucun
compte requis pour lancer les tests).

| Fichier | Contenu | Provenance |
|---------|---------|------------|
| `signin_form.html` | champ `authenticity_token` du formulaire Devise (structure réelle) | `GET /users/sign_in` |
| `manifest_n0110_stable.json` | manifeste firmware Graphique (v25.2.0) | `GET /firmwares/n0110/stable.json` (authentifié) |
| `manifest_n0200_stable.json` | manifeste firmware Scientifique (v3.0.0) | `GET /firmwares/n0200/stable.json` (authentifié) |

## Ce qui n'est **jamais** ici (par conception)

- **Aucun jeton / cookie** : la valeur du CSRF est remplacée par `REDACTED_CSRF_TOKEN` ; le
  `remember_user_token` n'est ni capturé ni stocké.
- **Aucun binaire firmware** : les `.dfu` officiels (propriété NumWorks, plusieurs Mo) ne
  sont pas versionnés. Les tests de flash utilisent un DfuSe **synthétique** (voir
  `FirmwareImage.synthetic`).

## Rafraîchir

```bash
NWUPDATER_EMAIL=… NWUPDATER_PASSWORD=… python3 tests/fixtures/refresh.py
```
Le script se connecte (jeton gardé en mémoire, jamais écrit), récupère les manifestes et
redacte le CSRF. Identifiants lus dans l'environnement — **jamais** en dur dans le dépôt.
