# Politique de sécurité / Security Policy

> Projet **bénévole et de hobby**, sans garantie (voir [DISCLAIMER](DISCLAIMER.md)). Les
> engagements ci-dessous sont tenus **dans la mesure de nos moyens**, sans SLA.

## Français

### Signaler une vulnérabilité

`nwupdater` manipule une donnée sensible (le jeton `remember_user_token` de votre compte
NumWorks) et expose une petite API locale. Si vous découvrez un problème de sécurité :

- **De préférence, en privé** : onglet **Security → Report a vulnerability** du dépôt
  (GitHub Private Vulnerability Reporting) — <https://github.com/1e1/epsilon-updater/security>.
- À défaut, ouvrez une **issue** : <https://github.com/1e1/epsilon-updater/issues> — mais
  **sans y publier de détail exploitable** tant que le correctif n'est pas disponible.

Merci d'inclure : version concernée, étapes de reproduction, impact estimé, et l'OS/navigateur.

### Ce qui nous intéresse en priorité

- Fuite ou stockage non protégé du jeton (`~/.config/nwupdater/credentials.json`).
- Contournement du garde anti-CSRF / anti-DNS-rebinding du serveur local (`127.0.0.1`).
- Altération d'un firmware entre le téléchargement et le flashage (l'empreinte SHA-256 est
  journalisée précisément pour rendre cela détectable — voir
  [GOOD-FAITH DECLARATION](GOOD-FAITH-DECLARATION.md) §3.1).

### Notre engagement

- Accuser réception sous un délai raisonnable et vous tenir informé du traitement.
- Corriger de bonne foi les failles confirmées, puis créditer le rapporteur s'il le souhaite.

### Objection d'un ayant droit

NumWorks SAS ou tout autre ayant droit qui estimerait ce projet contraire à ses droits peut
nous saisir par les mêmes canaux. Conformément à la
[DÉCLARATION DE BONNE FOI](GOOD-FAITH-DECLARATION.md) §7, nous nous engageons à **répondre**
et à **corriger ou retirer** l'outil sur demande motivée.

## English

### Reporting a vulnerability

`nwupdater` handles a sensitive secret (your NumWorks `remember_user_token`) and exposes a
small local API. If you find a security issue:

- **Preferably privately**: the repo's **Security → Report a vulnerability** tab
  (GitHub Private Vulnerability Reporting) — <https://github.com/1e1/epsilon-updater/security>.
- Otherwise open an **issue** — <https://github.com/1e1/epsilon-updater/issues> — **without
  posting exploitable details** until a fix is available.

Please include: affected version, reproduction steps, estimated impact, and OS/browser.

### What we care about most

- Leakage or unprotected storage of the token (`~/.config/nwupdater/credentials.json`).
- Bypass of the local server's CSRF / DNS-rebinding guard (`127.0.0.1`).
- Tampering of a firmware between download and flashing (the SHA-256 fingerprint is logged
  precisely to make this detectable).

### Our commitment

- Acknowledge within a reasonable delay and keep you posted.
- Fix confirmed issues in good faith, and credit the reporter if desired.

### Rights-holder objection

NumWorks SAS or any rights holder who considers this project to infringe their rights may
contact us through the same channels. Per the good-faith declaration, we commit to **respond**
and to **fix or withdraw** the tool upon a motivated request.
