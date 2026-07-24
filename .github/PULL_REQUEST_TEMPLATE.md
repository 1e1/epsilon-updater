<!-- Merci pour la contribution ! Coche ce qui s'applique. -->

## Résumé

<!-- Que fait cette PR et pourquoi ? -->

## Type

- [ ] Correctif (bug)
- [ ] Fonctionnalité
- [ ] Refactor / qualité
- [ ] Docs / outillage

## Checklist

- [ ] `python3 -m pytest -q` passe (contre le device DFU **virtuel**, sans USB réel ni réseau)
- [ ] `python3 -m ruff check src tests` et `python3 -m mypy src` passent
- [ ] Tests ajoutés/mis à jour pour tout changement de comportement
- [ ] Sortie CLI/Python **en anglais** ; localisation FR/EN uniquement côté GUI web
- [ ] Aucune donnée réelle (jeton, n° de série, dump) ni secret dans le diff
- [ ] `CHANGELOG.md` mis à jour si pertinent

## Notes

<!-- Points d'attention pour la relecture, compromis, suites éventuelles. -->
