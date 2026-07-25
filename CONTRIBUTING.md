# Contribuer à nwupdater

Merci de votre intérêt ! Ce projet est **indépendant et non officiel** (voir
[`DISCLAIMER.md`](DISCLAIMER.md)). Contributions bienvenues, dans le respect des règles
ci-dessous.

## Règle d'or : jamais d'USB réel dans le dépôt

Tout le code et **tous les tests** s'exécutent contre le **device DFU virtuel**
(`src/nwupdater/testing/virtual_dfu.py`) et un serveur local stdlib — **sans matériel, sans
réseau**. Le seul chemin qui touche du vrai USB (`dfu/usbio.py`) reçoit `pyusb` par
**injection** et n'est jamais exercé par la suite de tests. N'ajoutez pas de test qui exige
une calculatrice, un port USB ou un accès réseau.

## Mise en route

```bash
python -m pip install -e ".[dev]"     # pytest + ruff + bandit
python -m pytest -q                   # doit être 100 % vert
python -m ruff check src tests        # lint (0 erreur)
python -m bandit -r src -ll           # scan sécurité
```

## Style & qualité

- **Lint** : `ruff` (config dans `pyproject.toml`, ligne à 100). CI le vérifie.
- **Identifiants** en anglais ; docstrings/commentaires acceptés FR ou EN (rester cohérent
  au sein d'un module).
- Fonctions réseau/USB **pures et injectables** (transport/pyusb en paramètre) → testables
  hors-ligne. Les écritures disque (secrets, cache, journaux) restent hors des fonctions
  réseau.
- Toute modification de comportement s'accompagne d'un test.

## Sécurité

- **Aucun secret dans le dépôt.** Le jeton `remember_user_token` est stocké hors-arbre
  (`~/.config/nwupdater/credentials.json`, `0600`), jamais commité. On ne stocke **jamais**
  le mot de passe.
- Valider toute entrée interpolée dans une URL/chemin (cf. `download._check_model`).
- Signaler une vulnérabilité : voir [`SECURITY.md`](SECURITY.md).

## Portée

- **Guide illustré du contributeur** : [`docs/07-contributing/`](docs/07-contributing/README.md) —
  quatre façons de contribuer (référencer une app/script, modifier le front, interfacer une API
  NumWorks, ajouter un device), avec schémas et exemples.
- Base de connaissance et specs : [`docs/`](docs/README.md).
- On ne contourne **aucune** protection : on rejoue des dialogues documentés et on flashe des
  firmwares **officiels signés** récupérés tels quels. Voir
  [`GOOD-FAITH-DECLARATION.md`](GOOD-FAITH-DECLARATION.md).
