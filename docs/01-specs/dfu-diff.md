# `dfu-diff` — caractériser le chiffrement par comparaison de versions

> Projet indépendant, non officiel. Outil d'analyse pour l'interopérabilité. Les binaires
> NumWorks ne sont **pas** redistribués (voir `GOOD-FAITH-DECLARATION.md`).

## Pourquoi

Le firmware Scientifique (N02xx) est un blob **chiffré/opaque** (cf.
[`n02xx-firmware-format.md`](n02xx-firmware-format.md)). Un seul exemplaire n'apprend presque
rien du chiffrement. **Deux versions** peuvent révéler le *mode* :

| Signature observée | Interprétation |
|---|---|
| Beaucoup d'octets égaux au **même offset**, dispersés | Réutilisation de keystream (flux/CTR, nonce fixe) — `C1⊕C2` expose `P1⊕P2` |
| **Préfixe** identique long puis divergence (~1/256 ensuite) | Chiffrement par blocs **CBC** à clé/IV identiques, ou en-tête plaintext partagé |
| ~aucune corrélation (~1/256 d'octets égaux) | Clé/nonce **par build** → chiffrement correct, rien à extraire |
| 100 % égaux | Versions **identiques** |

Le verdict « chiffrement » n'est émis que pour des entrées à **haute entropie** (≥ 7,5 b/o).
Pour du firmware en clair (Epsilon graphique), l'outil rend un diff binaire ordinaire, sans
prétention cryptographique.

## Usage

```bash
python -m nwupdater.tools.dfudiff ANCIEN.dfu NOUVEAU.dfu        # rapport lisible
python -m nwupdater.tools.dfudiff ANCIEN.dfu NOUVEAU.dfu --json # sortie machine
```

L'outil apparie les segments DfuSe par adresse et, pour chaque adresse commune, rapporte :
taille, % d'octets égaux (global et après-préfixe), préfixe commun, plus longue plage commune,
blocs de 16 o identiques, entropie de chaque côté, et un **verdict**.

## État actuel (2026-07-12) — bloqué faute de 2ᵉ version

`my.numworks.com` ne sert que le build courant : `n0200/stable.dfu` **==** `n0200/beta.dfu`
(tous deux **3.0.0**, même SHA-256) ; les versions historiques renvoient 404. Il n'existe donc
**aucune paire à comparer aujourd'hui**. L'outil est prêt : dès qu'une v4 sortira, comparer le
3.0.0 archivé (empreinte dans [`../reference/known-firmwares.json`](../reference/known-firmwares.json))
au nouveau `.dfu` donnera un verdict.

## Note d'honnêteté

Le diff peut révéler le *mode* (réutilisation de keystream / clé fixe) mais **pas** la clé.
Si NumWorks utilise une clé/nonce distincts par build (attendu), le résultat sera
« INDÉPENDANT » : on confirmera seulement que c'est proprement chiffré. Aucune tentative de
déchiffrement n'est faite.
