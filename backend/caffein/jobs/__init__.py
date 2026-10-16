# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scripts d'automatisation Python — remplacent les workflows n8n.

Chaque script est une fonction enregistrée avec `@job(...)`. Il peut être lancé :
- par le planificateur intégré (caffein/scheduler.py), selon son `schedule` ;
- depuis l'interface (page Automatisations → « Lancer ») ou l'API ;
- en ligne de commande : `python -m caffein run <nom>`.

Chaque exécution est journalisée dans la table `job_runs`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .. import config, db

log = logging.getLogger("caffein.jobs")


@dataclass
class JobSpec:
    name: str
    title: str
    description: str
    replaces: str
    schedule: dict
    func: Callable[..., dict]
    manual: bool = True
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def schedule_label(self) -> str:
        s = self.schedule
        if s["type"] == "interval":
            return "Toutes les minutes" if s["minutes"] == 1 else f"Toutes les {s['minutes']} minutes"
        if s["type"] == "daily":
            return f"Tous les jours à {s['time'].replace(':', 'h')} (Paris)"
        return s.get("label", "Sur événement")


JOBS: dict[str, JobSpec] = {}
LAST_CHECK: dict[str, str] = {}   # dernière exécution « silencieuse » (rien à faire)
NEXT_RUNS: dict[str, datetime] = {}  # renseigné par le planificateur


def every(minutes: int) -> dict:
    return {"type": "interval", "minutes": minutes}


def daily(time: str) -> dict:
    return {"type": "daily", "time": time}


def on_event(label: str) -> dict:
    return {"type": "event", "label": label}


def job(name: str, *, title: str, description: str, replaces: str, schedule: dict, manual: bool = True):
    def decorator(func: Callable[..., dict]) -> Callable[..., dict]:
        JOBS[name] = JobSpec(name, title, description, replaces, schedule, func, manual)
        return func
    return decorator


def run_job(name: str, trigger: str = "manual", actor: str | None = None, **kwargs: Any) -> dict:
    """Exécute un script et journalise le résultat. `actor` : email de l'utilisateur à l'origine du lancement."""
    spec = JOBS.get(name)
    if spec is None:
        raise KeyError(f"Script inconnu : {name}")

    started = db.now_iso()
    run_id = db.insert("job_runs", {"job": name, "trigger": trigger, "actor": actor, "status": "running", "started_at": started})
    # Un même script ne tourne jamais deux fois en parallèle (ex. dépôt + planificateur)
    if not spec.lock.acquire(timeout=120):
        db.update("job_runs", run_id, {"status": "error", "summary": "Exécution précédente toujours en cours",
                                       "finished_at": db.now_iso()})
        return get_run(run_id)
    try:
        result = spec.func(**kwargs) or {}
        status = result.pop("status", "success")
        summary = result.pop("summary", "")
    except Exception as exc:  # le journal doit tout capturer, comme n8n
        log.exception("Le script %s a échoué", name)
        status, summary, result = "error", str(exc) or exc.__class__.__name__, {"error": repr(exc)}
    finally:
        spec.lock.release()

    if result.pop("quiet", False) and trigger == "schedule" and status == "success":
        # Rien à faire : on ne pollue pas l'historique (le planificateur tourne chaque minute)
        db.execute("DELETE FROM job_runs WHERE id = ?", (run_id,))
        LAST_CHECK[name] = db.now_iso()
        return {"id": None, "job": name, "trigger": trigger, "actor": actor, "status": status, "summary": summary,
                "details": result, "started_at": started, "finished_at": LAST_CHECK[name]}

    db.update("job_runs", run_id, {"status": status, "summary": summary, "details": db.dumps(result),
                                   "finished_at": db.now_iso()})
    return get_run(run_id)


def get_run(run_id: int) -> dict:
    row = db.fetch_one("SELECT * FROM job_runs WHERE id = ?", (run_id,))
    row["details"] = db.loads(row["details"], {})
    return row


def list_runs(limit: int = 50, job_name: str | None = None, jobs: set[str] | None = None) -> list[dict]:
    """Historique des exécutions ; `jobs` limite aux scripts que l'utilisateur peut voir."""
    sql = "SELECT * FROM job_runs"
    params: tuple = ()
    where = []
    if job_name:
        where.append("job = ?")
        params += (job_name,)
    if jobs is not None:
        names = sorted(jobs) or [""]
        where.append(f"job IN ({', '.join('?' for _ in names)})")
        params += tuple(names)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
    rows = db.fetch_all(sql, params + (limit,))
    for row in rows:
        row["details"] = db.loads(row["details"], {})
    return rows


# Ordre d'affichage dans l'interface (du plus fréquent au plus ponctuel)
DISPLAY_ORDER = ["process_inbox", "generate_pdf", "send_invoice", "auto_reminders", "onboarding_emails",
                 "newsletter_notifications", "fiscal_alerts", "setup_drive"]


def job_module(name: str) -> str | None:
    """Module propriétaire d'un script (déclaré dans `Module.jobs`)."""
    from ..core import modules as registry

    return next((m.key for m in registry.load().values() if name in m.jobs), None)


def job_enabled(name: str) -> bool:
    """Un script appartient à un module : il ne tourne pas si ce module est désactivé."""
    from ..core import modules as registry

    module = job_module(name)
    return module is None or registry.is_enabled(module)


def describe_jobs(levels: dict[str, int] | None = None) -> list[dict]:
    """Scripts visibles : ceux des modules actifs que l'utilisateur peut consulter (`levels`)."""
    out = []
    ordered = sorted(JOBS.values(), key=lambda s: DISPLAY_ORDER.index(s.name) if s.name in DISPLAY_ORDER else 99)
    for spec in ordered:
        module = job_module(spec.name)
        if not job_enabled(spec.name) or (levels is not None and module and levels.get(module, 0) < 1):
            continue
        last = db.fetch_one("SELECT * FROM job_runs WHERE job = ? ORDER BY started_at DESC, id DESC LIMIT 1", (spec.name,))
        if last:
            last["details"] = db.loads(last["details"], {})
        nxt = NEXT_RUNS.get(spec.name)
        out.append({
            "name": spec.name, "module": module, "title": spec.title, "description": spec.description, "replaces": spec.replaces,
            "schedule": spec.schedule, "schedule_label": spec.schedule_label, "manual": spec.manual,
            "last_run": last, "last_check": LAST_CHECK.get(spec.name),
            "next_run": nxt.isoformat() if nxt and config.SCHEDULER_ENABLED else None,
            "running": spec.lock.locked(),
        })
    return out


# Enregistrement des scripts (l'import déclenche les décorateurs @job)
from . import (  # noqa: E402,F401
    auto_reminders,
    fiscal_alerts,
    generate_pdf,
    newsletter_notifications,
    onboarding_emails,
    process_inbox,
    send_invoice,
    setup_drive,
)
