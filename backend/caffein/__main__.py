# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ligne de commande Caffein (sur une installation Linux : commande `caffein`).

Serveur
    caffein serve [--host H] [--port P] [--no-scheduler]   interface + API + planificateur
    caffein scheduler                                       planificateur seul
    caffein health                                          vérifie que le serveur répond

Administration
    caffein create-admin --email E [--name N]               crée un administrateur (mot de passe demandé)
    caffein reset-password --email E                        change le mot de passe d'un compte
    caffein users                                           liste les comptes
    caffein migrate                                         applique les migrations de la base
    caffein backup [-o fichier.tar.gz]                      sauvegarde base + documents + clé
    caffein restore fichier.tar.gz [--force]                restaure une sauvegarde
    caffein seed --demo [--reset]                           données de démonstration
    caffein modules [enable|disable <module>]               liste, active ou désactive un module

Scripts d'automatisation
    caffein jobs                                            liste des scripts
    caffein run <script> [--invoice-id N] [--text T] [--force]
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import sys
import time


def _ask_password(confirm: bool = True) -> str:
    password = os.getenv("CAFFEIN_ADMIN_PASSWORD") or getpass.getpass("Mot de passe : ")
    if confirm and not os.getenv("CAFFEIN_ADMIN_PASSWORD") and getpass.getpass("Confirmation : ") != password:
        raise SystemExit("Les mots de passe ne correspondent pas.")
    return password


def main(argv: list[str] | None = None) -> int:
    from . import config  # charge .env / CAFFEIN_ENV_FILE avant de lire les valeurs par défaut

    parser = argparse.ArgumentParser(prog="caffein", description="Caffein — l'ERP libre et modulaire des petites entreprises")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Lancer le serveur web")
    serve.add_argument("--host", default=config.HOST)
    serve.add_argument("--port", type=int, default=config.PORT)
    serve.add_argument("--no-scheduler", action="store_true", help="Ne pas lancer le planificateur intégré")
    serve.add_argument("--reload", action="store_true", help="Rechargement automatique (développement)")

    sub.add_parser("scheduler", help="Lancer uniquement le planificateur")
    sub.add_parser("health", help="Vérifier que le serveur local répond (healthcheck)")
    sub.add_parser("migrate", help="Appliquer les migrations de la base")
    sub.add_parser("users", help="Lister les comptes")

    create_admin = sub.add_parser("create-admin", help="Créer un compte administrateur")
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--name", default="")

    reset_pw = sub.add_parser("reset-password", help="Changer le mot de passe d'un compte")
    reset_pw.add_argument("--email", required=True)

    backup = sub.add_parser("backup", help="Sauvegarder les données")
    backup.add_argument("-o", "--output", help="Fichier de sortie (.tar.gz)")
    restore = sub.add_parser("restore", help="Restaurer une sauvegarde")
    restore.add_argument("archive")
    restore.add_argument("--force", action="store_true", help="Écraser les données existantes")

    seed = sub.add_parser("seed", help="Créer les données de démonstration")
    seed.add_argument("--demo", action="store_true", help="Jeu de démonstration complet")
    seed.add_argument("--reset", action="store_true", help="Effacer les données métier avant (les comptes sont conservés)")

    modules = sub.add_parser("modules", help="Lister, activer ou désactiver les modules")
    modules.add_argument("action", nargs="?", choices=("enable", "disable"))
    modules.add_argument("module", nargs="?", help="clé du module (sales, stock, hr…)")

    sub.add_parser("jobs", help="Lister les scripts d'automatisation")
    run = sub.add_parser("run", help="Exécuter un script maintenant")
    run.add_argument("job")
    run.add_argument("--invoice-id", type=int)
    run.add_argument("--text")
    run.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s", datefmt="%H:%M:%S")

    if args.command == "serve":
        if args.no_scheduler:
            os.environ["CAFFEIN_SCHEDULER"] = "0"
        import uvicorn

        uvicorn.run("caffein.api.main:app", host=args.host, port=args.port, reload=args.reload, log_level="info",
                    proxy_headers=True, forwarded_allow_ips=os.getenv("CAFFEIN_FORWARDED_ALLOW_IPS") or "127.0.0.1")
        return 0

    if args.command == "health":
        import urllib.request

        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{config.PORT}/api/health", timeout=4) as resp:
                print(resp.read().decode())
            return 0
        except OSError as exc:
            print(f"Serveur injoignable : {exc}", file=sys.stderr)
            return 1

    if args.command == "restore":
        from .backup import restore as do_restore

        do_restore(args.archive, force=args.force)
        print(f"Sauvegarde restaurée dans {config.DATA_DIR}. Redémarrez le service.")
        return 0

    from . import auth, db

    db.init_db()

    if args.command == "migrate":
        print(f"Base à jour : schéma v{db.schema_version()} ({config.DB_PATH})")
        return 0

    if args.command == "users":
        for u in auth.list_users():
            state = "actif" if u["active"] else "désactivé"
            print(f"{u['id']:>3}  {u['email']:<36} {u['role']:<7} {state:<10} {u['full_name']}")
        return 0

    if args.command == "create-admin":
        user = auth.create_user(args.email, _ask_password(), args.name, "admin")
        print(f"Administrateur créé : {user['email']}")
        return 0

    if args.command == "reset-password":
        row = auth.get_user_by_email(args.email)
        if not row:
            print(f"Aucun compte pour {args.email}", file=sys.stderr)
            return 1
        auth.set_password(row["id"], _ask_password())
        print("Mot de passe modifié ; les sessions ouvertes ont été fermées.")
        return 0

    if args.command == "backup":
        from .backup import backup as do_backup

        print(f"Sauvegarde créée : {do_backup(args.output)}")
        return 0

    if args.command == "modules":
        from .core import modules as registry
        from .core.errors import Conflict, NotFound

        if args.action:
            if not args.module:
                print("Indiquez le module : caffein modules enable stock", file=sys.stderr)
                return 2
            try:
                registry.set_enabled(args.module, args.action == "enable")
            except (Conflict, NotFound) as exc:
                print(str(exc) or "Module inconnu.", file=sys.stderr)
                return 1
        for m in registry.describe():
            state = "toujours actif" if m["core"] else ("actif" if m["enabled"] else "inactif")
            deps = f"  (nécessite : {', '.join(m['depends'])})" if m["depends"] else ""
            print(f"{m['key']:<12} {state:<15} {m['label'][0]}{deps}")
        return 0

    if args.command == "seed":
        from .seed import init_instance
        from .seed import seed as do_seed

        if not args.demo:
            init_instance(reset=args.reset)
            print("Instance initialisée (sans données de démonstration).")
            return 0
        created = do_seed(reset=args.reset)
        print("Données de démonstration créées." if created else "La base contient déjà des données (ajoutez --reset).")
        return 0

    from .jobs import JOBS, describe_jobs, run_job

    if args.command == "jobs":
        for j in describe_jobs():
            print(f"{j['name']:<26} {j['schedule_label']:<42} remplace : {j['replaces']}")
        return 0

    if args.command == "scheduler":
        from .scheduler import Scheduler

        scheduler = Scheduler()
        scheduler.start()
        print("Planificateur démarré — Ctrl+C pour arrêter.")
        try:
            while scheduler.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.stop()
        return 0

    if args.command == "run":
        if args.job not in JOBS:
            print(f"Script inconnu : {args.job}. Disponibles : {', '.join(JOBS)}", file=sys.stderr)
            return 2
        kwargs = {}
        if args.invoice_id is not None:
            kwargs["invoice_id"] = args.invoice_id
        if args.text:
            kwargs["text"] = args.text
        if args.force:
            kwargs["force"] = True
        result = run_job(args.job, trigger="cli", actor="cli", **kwargs)
        print(f"[{result['status']}] {result['summary']}")
        if result.get("details"):
            print(json.dumps(result["details"], ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] != "error" else 1
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:  # erreurs de validation (email, mot de passe…)
        print(f"Erreur : {exc}", file=sys.stderr)
        sys.exit(1)
