# Contrat de capture (harness ⇄ analyseur) — première-allumage Scientifique

> Artefact de **synchronisation** entre l'agent « harness » (produit la capture) et l'agent
> « analyse » (`nwupdater.tools.capture_analyze`, qui la lit). Projet indépendant, non officiel.

## Scénario capturé

Sur le Mac de test : lancer l'app → s'authentifier → brancher la calculatrice **Scientifique
(N0200), premier allumage hors boîte** → **tenter** le téléchargement de la Version 3 →
**s'arrêter avant tout transfert vers la calculatrice** (séquence rejouable). Le serveur peut
**refuser** (calculatrice non enregistrée sur le compte). On rapatrie le dump pour analyse.

## Format canonique : la sortie de `capture_session.run_capture()`

Le harness produit **un seul objet JSON** (fichier `capture.json`) :

```json
{
  "scenario": "scientific-first-boot-download-no-flash",
  "timestamp": "…", "flashed": false, "calculator_serial": "…",
  "usb":  { … rapport diagnose() … , "transfers": [ … CapturingDevice … ] },
  "web":  { "outcome": "downloaded|refused_or_error|auth_required",
            "firmware": {"version","size","sha256"}?, "error": "…"?,
            "transfers": [ … RecordingTransport … ] },
  "redaction": "secrets caviardés ; firmware non versionné (taille+sha256)"
}
```

### USB — `usb.transfers` (producteur : `nwupdater.dfu.capture.CapturingDevice`)
```json
{"seq":0,"dir":"OUT","bmRequestType":"0x21","bRequest":1,"wValue":"0x0000","wIndex":0,"data_len":5,"data":"2100000098"}
```
`dir` = `IN`/`OUT` ; `bmRequestType`/`wValue` en chaîne hex ; `data` en hex (tronqué à 2048 o).

### WEB — `web.transfers` (producteur : `nwupdater.net_capture.RecordingTransport`)
```json
{"seq":0,
 "request":  {"method":"GET","url":"…/firmwares/n0200/stable.dfu","headers":{"Cookie":"[REDACTED]"},"body":null},
 "response": {"status":200,"headers":{…},"body":{"size":237606,"sha256":"…","content_type":"application/octet-stream","binary":true}}}
```
Secrets caviardés (mot de passe, CSRF, `Cookie`/`Set-Cookie`). Le `.dfu` n'est **jamais**
stocké : seulement `size` + `sha256` (comparés à `docs/reference/known-firmwares.json`).
Petits corps JSON (login, enrôlement) : `body.text` conservé pour extraire n° de série /
message d'erreur.

## Ce que l'analyseur en tire

- **USB** → décodage sémantique DFU/DfuSe : adresses **lues** (identité), absence d'**écriture**
  (doit être nulle), erreurs GETSTATUS.
- **WEB** → `outcome`, classification (login/manifeste/`.dfu`), **enrôlement** de device
  (`/devices`, `/calculators`, POST inconnu…) et **refus** (≥400) — hypothèse « non enregistrée ».
- **Corrélation** : un n° de série (lu en USB ou rapporté par le harness) réapparaît-il dans un
  corps WEB ?

`capture_analyze.analyze(source)` accepte l'objet dict, un `capture.json`, ou un répertoire le
contenant (une disposition héritée `usb.jsonl`/`web.jsonl`/`web.har` reste tolérée).
