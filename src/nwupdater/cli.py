"""nwupdater CLI.

For now it exposes an ``identify`` command. Against a real calculator it needs pyusb
(extra ``usb``); against the built-in virtual device it needs nothing — this is how we
develop and demo without ever touching real USB.

    nwupdater identify --virtual n0110
    nwupdater identify              # real device (requires: pip install nwupdater[usb])
"""

from __future__ import annotations

import argparse
import sys

from . import DISCLAIMER_SHORT
from .dfu.identity import read_identity
from .dfu.protocol import DfuClient
from .models import describe_bcd


def _print_disclaimer() -> None:
    print(f"⚠️  {DISCLAIMER_SHORT}\n", file=sys.stderr)


def _cmd_identify(args) -> int:
    if args.virtual:
        from .testing.virtual_dfu import virtual_calculator
        dev = virtual_calculator(args.virtual, os_version=args.os_version, commit=args.commit)
        client = DfuClient(dev, sleep=lambda *_: None)
        bcd = dev.bcdDevice
        print(f"[virtual] {describe_bcd(bcd)}")
    else:
        dev, bcd, _iface = _open_real_device()
        client = DfuClient(dev, interface=_iface)
        print(describe_bcd(bcd))

    ident = read_identity(client, bcd)
    print(f"  modèle    : {ident.model_name} ({ident.family})")
    print(f"  OS        : {ident.os_version or '?'}  kernel={ident.kernel_version or '?'}")
    print(f"  commit    : {ident.commit or '?'}")
    if ident.external_apps_flash and ident.external_apps_flash != (0, 0):
        s, e = ident.external_apps_flash
        print(f"  apps zone : 0x{s:08x}-0x{e:08x} ({(e - s) // 1024} KiB)")
    print(f"  slotinfo  : {'valide' if ident.slot_info_valid else 'absent/invalide'}")
    return 0


def _cmd_catalog(args) -> int:
    from .catalog.firmware import FirmwareCatalog

    if args.fetch:
        try:
            catalog = FirmwareCatalog.fetch()
            src = "live (my.numworks.com)"
        except Exception as exc:  # network issues -> fall back to snapshot
            print(f"fetch live échoué ({exc}); repli sur le snapshot embarqué", file=sys.stderr)
            catalog = FirmwareCatalog.bundled()
            src = "snapshot embarqué"
    elif args.catalog_file:
        catalog = FirmwareCatalog.load(args.catalog_file)
        src = args.catalog_file
    else:
        catalog = FirmwareCatalog.bundled()
        src = "snapshot embarqué"

    # identity (virtual by default so it runs without USB)
    if args.virtual:
        from .testing.virtual_dfu import virtual_calculator
        dev = virtual_calculator(args.virtual, os_version=args.os_version, commit=args.commit)
        client = DfuClient(dev, sleep=lambda *_: None)
        bcd = dev.bcdDevice
    else:
        dev, bcd, _iface = _open_real_device()
        client = DfuClient(dev, interface=_iface)
    ident = read_identity(client, bcd)

    latest = catalog.latest()
    print(f"catalogue : {len(catalog)} versions (source: {src}) — dernière {latest}")
    print(f"calc      : {ident.model_name} ({ident.family}) OS {ident.os_version or '?'}")
    if ident.os_version and catalog.is_up_to_date(ident.os_version):
        print("→ à jour ✅")
        return 0
    updates = catalog.updates_for(ident.os_version or "0.0.0")
    print(f"→ {len(updates)} mise(s) à jour disponible(s) :")
    for r in updates:
        tag = "  (dernière)" if r is latest else ""
        print(f"    {r.version}{tag}")
    return 0


def _cmd_login(args) -> int:
    """Gérer le jeton d'authentification NumWorks (façon « bring-your-own-token »)."""
    from .catalog import auth as A

    if args.status:
        a = A.load_auth()
        if a is None:
            print("non authentifié — aucun jeton stocké.")
            return 1
        print(f"authentifié : {a.summary()}")
        print(f"stocké dans : {A.config_path()}")
        return 1 if a.is_expired() else 0
    if args.logout:
        print("jeton supprimé." if A.clear_auth() else "aucun jeton à supprimer.")
        return 0

    _print_disclaimer()
    if args.email:
        # Option B : login intégré (le mot de passe n'est jamais stocké, seulement le jeton).
        import getpass
        pwd = args.password or getpass.getpass("Mot de passe NumWorks : ")
        try:
            a = A.login_with_password(args.email, pwd)
        except (A.AuthError, A.TransportError) as exc:
            print(f"échec du login : {exc}", file=sys.stderr)
            return 1
    else:
        # Option A : l'utilisateur colle le jeton (le mot de passe ne touche jamais l'outil).
        if not args.token:
            print("Ouvre https://my.numworks.com/users/sign_in dans ton navigateur, connecte-toi")
            print("(coche « Se souvenir de moi »), puis copie la valeur du cookie")
            print("« remember_user_token » (DevTools → Application → Cookies → my.numworks.com).\n")
        token = (args.token or input("remember_user_token > ")).strip()
        if not token:
            print("aucun jeton fourni.", file=sys.stderr)
            return 1
        a = A.Auth(token)

    if not a.info().get("looks_valid"):
        print("⚠️  ce jeton ne ressemble pas à un remember_user_token NumWorks — enregistré tout de même.",
              file=sys.stderr)
    path = A.save_auth(a)
    print(f"✓ {a.summary()} — enregistré dans {path}")
    return 0


def _require_auth():
    """Charge le jeton stocké, ou None + message d'aide."""
    from .catalog import auth as A
    a = A.load_auth()
    if a is None:
        print("non authentifié — lance d'abord : nwupdater login", file=sys.stderr)
        return None
    if a.is_expired():
        print("jeton expiré — relance : nwupdater login", file=sys.stderr)
        return None
    return a


def _cmd_install(args) -> int:
    from .install.image import FirmwareImage
    from .install.installer import Installer
    from .models import MODELS

    _print_disclaimer()
    if args.virtual:
        from .testing.virtual_dfu import virtual_calculator
        dev = virtual_calculator(args.virtual, os_version=args.os_version, commit=args.commit)
        client = DfuClient(dev, sleep=lambda *_: None)
        bcd = dev.bcdDevice
    else:
        dev, bcd, _iface = _open_real_device()
        client = DfuClient(dev, interface=_iface)

    model = MODELS.get(bcd)
    if model is None:
        print(f"modèle inconnu (bcd 0x{bcd:04x})", file=sys.stderr)
        return 1
    ident = read_identity(client, bcd)
    print(f"calc      : {ident.model_name} ({ident.family}) OS {ident.os_version or '?'}")

    # Safety: flashing REAL hardware is destructive and irreversible if interrupted.
    if not args.virtual and not args.yes:
        print(f"\n⚠️  Vous allez FLASHER une VRAIE calculatrice ({ident.model_name}). Une "
              "coupure de courant\n   ou une image incorrecte peut l'endommager ou la "
              "rendre inutilisable (« brick »).")
        print("   Usage scolaire : si l'utilisateur est mineur, opérez sous supervision d'un adulte.")
        if input("   Tapez « oui » pour confirmer (vaut attestation) : ").strip().lower() not in ("oui", "o", "yes", "y"):
            print("annulé.", file=sys.stderr)
            return 1

    if args.from_cache:
        from .cache.store import FirmwareCache
        blob = FirmwareCache(args.cache_dir).get(model.name, args.to_version)
        if blob is None:
            print(f"absent du cache : {model.name} v{args.to_version} — lance 'preload' d'abord",
                  file=sys.stderr)
            return 1
        image = FirmwareImage.from_dfuse(blob)
        print(f"image     : depuis le cache — {model.name} v{args.to_version} ({image.total_size} o)")
    elif args.download:
        from .catalog import download as D
        a = _require_auth()
        if a is None:
            return 1
        try:
            manifest, blob = D.fetch_firmware(model.name, args.channel, a)
        except (D.AuthRequired, D.DownloadError) as exc:
            print(f"téléchargement échoué : {exc}", file=sys.stderr)
            return 1
        image = FirmwareImage.from_dfuse(blob)
        from datetime import datetime, timezone
        sha256 = D.sha256_hex(blob)
        log_path = D.record_download(manifest, sha256,
                                     when=datetime.now(timezone.utc).isoformat())
        print(f"image     : téléchargée {model.name} [{args.channel}] v{manifest.version} "
              f"(patch {manifest.patch_level}, {image.total_size} o)")
        print(f"sha256    : {sha256}")
        print(f"provenance: journalisée dans {log_path}")
    elif args.dfuse:
        image = FirmwareImage.from_dfuse(open(args.dfuse, "rb").read())
        print(f"image     : {args.dfuse} (DfuSe, {image.total_size} o)")
    else:
        image = FirmwareImage.synthetic(model, version=args.to_version)
        print(f"image     : synthétique v{args.to_version} ({image.total_size} o) [démo offline]")

    def progress(phase, done, total):
        pct = 100 * done // max(total, 1)
        print(f"\r  {phase:6s} {pct:3d}% ({done}/{total} o)", end="", flush=True)

    inst = Installer(client, model, progress=progress)
    try:
        plan = inst.install(image, active_slot=args.active_slot, verify=not args.no_verify, boot=args.boot)
    except Exception as exc:
        print(f"\néchec install : {exc}", file=sys.stderr)
        return 1
    print()
    if plan.full_image:
        print("image     : complète — slots A+B écrits verbatim (comme l'updater officiel)")
    elif plan.target_slot:
        print(f"slot cible : {plan.target_slot} (inactif) — flashé + vérifié")
    installed = inst.read_installed_version(plan)
    if installed is None and model.opaque_firmware:
        print("vérif     : firmware N02xx chiffré/opaque — version non lisible dans le binaire "
              "(source = manifeste ; cf. docs/01-specs/n02xx-firmware-format.md)")
    else:
        print(f"vérif     : version installée relue = {installed}")
    if args.boot:
        print(f"boot      : saut demandé vers 0x{plan.boot_address:08x} (device détaché)")
    return 0


def _cmd_apps(args) -> int:
    from .apps.installer import AppInstaller
    from .apps.store import THIRD_PARTY_WARNING, AppStore

    if args.virtual:
        from .testing.virtual_dfu import virtual_calculator
        dev = virtual_calculator(args.virtual, os_version=args.os_version, commit=args.commit)
        client = DfuClient(dev, sleep=lambda *_: None)
        bcd = dev.bcdDevice
    else:
        dev, bcd, _iface = _open_real_device()
        client = DfuClient(dev, interface=_iface)
    ident = read_identity(client, bcd)
    has_region = bool(ident.external_apps_flash and ident.external_apps_flash != (0, 0))

    store = AppStore.load(args.store_file) if args.store_file else AppStore.bundled()
    compat = store.compatible(family=ident.family, device_api_level=args.api_level,
                              has_external_apps=has_region)
    print(f"calc      : {ident.model_name} ({ident.family}) OS {ident.os_version or '?'}")
    print(f"store     : {len(store)} apps — {len(compat)} compatible(s) (API level {args.api_level})")
    for e in compat:
        print(f"    {e.name:12s} v{e.version:5s} — {e.description}")
    if not has_region:
        print("    (aucune zone apps externes sur ce modèle)")

    if args.install:
        from .formats.nwa import build_nwa
        entry = store.get(args.install)
        if entry is None:
            print(f"app inconnue: {args.install}", file=sys.stderr)
            return 1
        print(f"\n⚠️  {THIRD_PARTY_WARNING}")
        if not args.virtual and not getattr(args, "yes", False):
            if input("   Tapez « oui » pour installer : ").strip().lower() not in ("oui", "o", "yes", "y"):
                print("annulé.", file=sys.stderr)
                return 1
        # démo offline: synthétise un .nwa (les URLs du store sont des exemples)
        blob = build_nwa(entry.name, api_level=entry.api_level, code=b"\x00" * 1024)
        inst = AppInstaller(client, external_apps_flash=ident.external_apps_flash or (0, 0),
                            device_api_level=args.api_level)
        try:
            res = inst.install(blob)
        except Exception as exc:
            print(f"échec install app : {exc}", file=sys.stderr)
            return 1
        print(f"→ installé '{res.name}' @0x{res.address:08x} ({res.size} o), vérifié ✅")
    return 0


def _human(n):
    for u in ("o", "Ko", "Mo"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} Go"


def _cmd_preload(args) -> int:
    """Pré-télécharger un OS dans le cache (démo: image synthétique)."""
    from .cache.store import FirmwareCache
    from .install.image import FirmwareImage
    from .models import MODELS

    model = next((m for m in MODELS.values() if m.name == args.model), None)
    if model is None:
        print(f"modèle inconnu: {args.model}", file=sys.stderr)
        return 1
    if args.download:
        from .catalog import download as D
        a = _require_auth()
        if a is None:
            return 1
        try:
            manifest, blob = D.fetch_firmware(model.name, args.channel, a)
        except (D.AuthRequired, D.DownloadError) as exc:
            print(f"téléchargement échoué : {exc}", file=sys.stderr)
            return 1
        version = manifest.version
    else:
        if not args.version:
            print("précise une version, ou utilise --download pour récupérer la dernière officielle",
                  file=sys.stderr)
            return 1
        blob = FirmwareImage.synthetic(model, version=args.version).to_dfuse()
        version = args.version
    cache = FirmwareCache(args.cache_dir)
    entry = cache.put(model.name, version, blob)
    st = cache.status()
    print(f"pré-téléchargé : {model.name} v{version} ({_human(entry.size)})")
    print(f"cache          : version {st['version']} · modèles {st['models']} · {_human(st['total_size'])}")
    print("→ prêt à flasher toute une classe hors-ligne (une seule version conservée, purge à 30 j).")
    return 0


def _cmd_cache(args) -> int:
    import time as _t

    from .cache.store import FirmwareCache
    cache = FirmwareCache(args.cache_dir)
    if args.clear:
        cache.clear()
        print("cache vidé.")
        return 0
    if args.prune:
        removed = cache.prune()
        print(f"purge : {len(removed)} entrée(s) expirée(s) supprimée(s).")
    st = cache.status()
    if not st["version"]:
        print("cache vide.")
        return 0
    days = max(0, (st["expires_at"] - _t.time()) / 86400)
    print(f"version   : {st['version']}")
    print(f"modèles   : {', '.join(st['models'])}")
    print(f"taille    : {_human(st['total_size'])}")
    print(f"expire    : dans {days:.0f} j (TTL {st['ttl_days']} j)")
    return 0


def _cmd_ui(args) -> int:
    from .server.httpd import serve
    from .server.session import Session

    session = Session(model_name=args.virtual or "n0110", os_version=args.os_version,
                      commit=args.commit, api_level=args.api_level, real=args.real)
    serve(session, host=args.host, port=args.port, open_browser=not args.no_browser,
          single_instance=args.single_instance,
          idle_timeout=args.idle_timeout if args.idle_timeout > 0 else None)
    return 0


def _open_real_device():
    """Open + configure + claim a real calculator's DFU interface. Production only.

    Returns ``(device, bcdDevice, interface)``. Exits with a helpful message if pyusb is
    missing or no calculator/DFU interface is available."""
    try:
        import usb.core
        import usb.util
    except ImportError:
        print("pyusb requis pour le mode réel : pip install 'nwupdater[usb]'", file=sys.stderr)
        raise SystemExit(2)
    from .dfu import usbio
    try:
        od = usbio.find_calculator(usb.core, usb.util)
    except usbio.UsbError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    return od.dev, od.bcd_device, od.interface


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwupdater",
        description="NumWorks updater (headless, sans WebUSB) — projet indépendant NON officiel",
        epilog=f"AVERTISSEMENT : {DISCLAIMER_SHORT}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="s'authentifier à my.numworks.com (jeton, pour télécharger l'OS)")
    p_login.add_argument("--token", metavar="VALUE", help="coller directement la valeur du cookie remember_user_token")
    p_login.add_argument("--email", metavar="ADDR", help="login intégré : email du compte (mot de passe demandé)")
    p_login.add_argument("--password", metavar="PWD", help="mot de passe (sinon demandé sans écho) — jamais stocké")
    p_login.add_argument("--status", action="store_true", help="afficher l'état du jeton stocké")
    p_login.add_argument("--logout", action="store_true", help="supprimer le jeton stocké")
    p_login.set_defaults(func=_cmd_login)

    p_id = sub.add_parser("identify", help="lire modèle + version OS d'une calculatrice")
    p_id.add_argument("--virtual", metavar="MODEL", help="utiliser un device virtuel (n0110, n0120, n0200…)")
    p_id.add_argument("--os-version", default="23.2.4", help="version OS du device virtuel")
    p_id.add_argument("--commit", default="abc1234", help="commit du device virtuel")
    p_id.set_defaults(func=_cmd_identify)

    p_cat = sub.add_parser("catalog", help="lister les mises à jour disponibles pour une calculatrice")
    p_cat.add_argument("--virtual", metavar="MODEL", help="utiliser un device virtuel (n0110, n0200…)")
    p_cat.add_argument("--os-version", default="23.2.4", help="version OS du device virtuel")
    p_cat.add_argument("--commit", default="abc1234", help="commit du device virtuel")
    p_cat.add_argument("--fetch", action="store_true", help="rafraîchir le catalogue en ligne (my.numworks.com)")
    p_cat.add_argument("--catalog-file", metavar="PATH", help="charger le catalogue depuis un fichier JSON local")
    p_cat.set_defaults(func=_cmd_catalog)

    p_ins = sub.add_parser("install", help="flasher un firmware (démo: contre le device virtuel)")
    p_ins.add_argument("--virtual", metavar="MODEL", help="utiliser un device virtuel (n0110, n0200…)")
    p_ins.add_argument("--os-version", default="23.2.4", help="version OS courante du device virtuel")
    p_ins.add_argument("--commit", default="abc1234", help="commit du device virtuel")
    p_ins.add_argument("--to-version", default="99.9.9", help="version cible (image synthétique)")
    p_ins.add_argument("--download", action="store_true",
                       help="télécharger le vrai firmware officiel (nécessite 'login')")
    p_ins.add_argument("--channel", default="stable", choices=["stable", "beta"],
                       help="canal de téléchargement (stable/beta)")
    p_ins.add_argument("--dfuse", metavar="PATH", help="flasher un fichier .dfu (DfuSe) réel")
    p_ins.add_argument("--from-cache", action="store_true", help="flasher depuis le cache (pré-téléchargé)")
    p_ins.add_argument("--cache-dir", metavar="DIR", help="répertoire du cache firmware")
    p_ins.add_argument("--active-slot", default="A", choices=["A", "B"], help="slot actif (A/B)")
    p_ins.add_argument("--no-verify", action="store_true", help="désactiver la vérification read-back")
    p_ins.add_argument("--boot", action="store_true", help="démarrer le slot flashé (detach+jump)")
    p_ins.add_argument("--yes", "-y", action="store_true",
                       help="ne pas demander confirmation avant de flasher une VRAIE calculatrice")
    p_ins.set_defaults(func=_cmd_install)

    p_app = sub.add_parser("apps", help="lister / installer des applications tierces")
    p_app.add_argument("--virtual", metavar="MODEL", help="utiliser un device virtuel (n0110, n0200…)")
    p_app.add_argument("--os-version", default="23.2.4", help="version OS du device virtuel")
    p_app.add_argument("--commit", default="abc1234", help="commit du device virtuel")
    p_app.add_argument("--api-level", type=int, default=0, help="EXTERNAL_APPS_API_LEVEL du device")
    p_app.add_argument("--store-file", metavar="PATH", help="catalogue d'apps JSON local")
    p_app.add_argument("--install", metavar="NAME", help="installer une app (démo: .nwa synthétique)")
    p_app.add_argument("--yes", "-y", action="store_true",
                       help="ne pas demander confirmation avant d'installer une app tierce")
    p_app.set_defaults(func=_cmd_apps)

    p_pre = sub.add_parser("preload", help="pré-télécharger un OS dans le cache (mode classe)")
    p_pre.add_argument("model", help="modèle (n0110, n0120, n0200…)")
    p_pre.add_argument("version", nargs="?", help="version à mettre en cache (ex: 25.2.0) ; omis avec --download")
    p_pre.add_argument("--download", action="store_true",
                       help="télécharger le vrai firmware officiel (nécessite 'login')")
    p_pre.add_argument("--channel", default="stable", choices=["stable", "beta"],
                       help="canal de téléchargement (stable/beta)")
    p_pre.add_argument("--cache-dir", metavar="DIR", help="répertoire du cache firmware")
    p_pre.set_defaults(func=_cmd_preload)

    p_ca = sub.add_parser("cache", help="état du cache firmware (statut / purge / vidage)")
    p_ca.add_argument("--prune", action="store_true", help="supprimer les entrées expirées (>30 j)")
    p_ca.add_argument("--clear", action="store_true", help="vider le cache")
    p_ca.add_argument("--cache-dir", metavar="DIR", help="répertoire du cache firmware")
    p_ca.set_defaults(func=_cmd_cache)

    p_ui = sub.add_parser("ui", help="ouvrir l'interface web locale dans le navigateur")
    p_ui.add_argument("--virtual", metavar="MODEL", default="n0110", help="modèle du device virtuel")
    p_ui.add_argument("--os-version", default="23.2.4", help="version OS du device virtuel")
    p_ui.add_argument("--commit", default="abc1234", help="commit du device virtuel")
    p_ui.add_argument("--api-level", type=int, default=0, help="EXTERNAL_APPS_API_LEVEL du device")
    p_ui.add_argument("--host", default="127.0.0.1", help="adresse d'écoute (loopback par défaut)")
    p_ui.add_argument("--port", type=int, default=8765, help="port d'écoute")
    p_ui.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur")
    p_ui.add_argument("--real", action="store_true", help="piloter une vraie calculatrice (pyusb)")
    p_ui.add_argument("--single-instance", action="store_true", help="réutiliser une instance déjà lancée")
    p_ui.add_argument("--idle-timeout", type=float, default=0, help="arrêt auto après N s d'inactivité (0=désactivé)")
    p_ui.set_defaults(func=_cmd_ui)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
