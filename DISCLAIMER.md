# ⚠️ Avertissement / Disclaimer

## Français

**`nwupdater` est un projet INDÉPENDANT et de HOBBY.** Ce n'est **PAS** une application
officielle NumWorks et il n'a **AUCUN lien** avec NumWorks SAS.

Le logiciel est fourni **« EN L'ÉTAT », SANS AUCUNE GARANTIE** d'aucune sorte, expresse ou
implicite. Mettre à jour, flasher ou modifier le firmware d'une calculatrice est une
opération **À RISQUE** qui peut :

- endommager l'appareil, temporairement ou définitivement (« brick ») ;
- effacer vos données, scripts ou configurations ;
- invalider la garantie constructeur.

**Vous utilisez cet outil À VOS SEULS RISQUES.** Les auteurs et contributeurs déclinent
toute responsabilité pour tout dommage matériel, perte de données ou tout autre préjudice,
direct ou indirect, résultant de son utilisation.

**Public mineur :** les calculatrices étant des outils scolaires, toute opération de flashage
réalisée par un mineur doit se faire **sous la supervision d'un adulte**.

**Logiciel « non officiel » & examens :** le statut « officiel » (donc la conformité au mode
examen) est une **signature Ed25519 vérifiée par le bootloader à chaque démarrage à froid**,
**entièrement hors ligne** (aucune attestation réseau). Flasher l'**image officielle signée**
avec cet outil puis **redémarrer à froid** (bouton RESET, ou extinction) restaure l'état
**officiel** — le bootloader re-vérifie la signature. En revanche, le **« boot » in-app** (saut
DFU) fait afficher **temporairement** le bandeau **« UNOFFICIAL SOFTWARE »** : le noyau, sans la
clé, ne peut pas vérifier un slot atteint par saut ; un **démarrage à froid efface ce bandeau**.
Un firmware **modifié ou non signé** reste « non officiel » — la signature ne peut pas être
forgée. Constaté sur une N0120 réelle. **Pour un examen surveillé à enjeu, n'utilisez que l'image
officielle, vérifiez le statut de l'appareil après un démarrage à froid, et confirmez au besoin
auprès de l'établissement ou de NumWorks.**

« NumWorks » et « Epsilon » sont des marques de leurs détenteurs respectifs, mentionnées à
des fins d'interopérabilité uniquement.

## English

**`nwupdater` is an INDEPENDENT, HOBBY project.** It is **NOT** an official NumWorks
application and has **NO affiliation** with NumWorks SAS.

The software is provided **"AS IS", WITHOUT WARRANTY** of any kind. Updating, flashing or
modifying a calculator's firmware is a **RISKY** operation that may damage the device
(permanently — "brick"), erase your data, or void the manufacturer's warranty.

**You use this tool ENTIRELY AT YOUR OWN RISK.** The authors and contributors accept no
liability for any hardware damage, data loss or other harm resulting from its use.

**Minors:** as calculators are school tools, any flashing performed by a minor should be done
**under adult supervision**.

**"Unofficial software" & exams:** the "official" status (hence exam-mode compliance) is an
**Ed25519 signature verified by the bootloader at every cold boot**, **entirely offline** (no
network attestation). Flashing the **official signed image** with this tool and then
**cold-booting** (RESET button, or power-cycle) restores **official** status — the bootloader
re-verifies the signature. By contrast, the **in-app "boot"** (DFU jump) shows the
**"UNOFFICIAL SOFTWARE"** banner **transiently**: the kernel, lacking the key, cannot verify a
slot entered by a jump; a **cold boot clears it**. **Modified or unsigned** firmware stays
"unofficial" — the signature cannot be forged. Observed on a real N0120. **For a high-stakes
proctored exam, use only the official image, verify the device's status after a cold boot, and
confirm with your institution or NumWorks if in doubt.**

"NumWorks" and "Epsilon" are trademarks of their respective owners, referenced for
interoperability purposes only.
