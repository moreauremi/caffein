# SPDX-License-Identifier: AGPL-3.0-or-later
"""Planificateur intégré — remplace les déclencheurs n8n (Schedule Trigger, Cron).

Tourne dans un thread du serveur web (CAFFEIN_SCHEDULER=1, par défaut) ou seul :
    python -m caffein scheduler
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from . import config
from .jobs import JOBS, NEXT_RUNS, job_enabled, run_job

log = logging.getLogger("caffein.scheduler")
TICK_SECONDS = 5
FIRST_INTERVAL_DELAY = timedelta(seconds=8)


def next_run(schedule: dict, now: datetime, first: bool = False) -> datetime | None:
    if schedule["type"] == "interval":
        return now + (FIRST_INTERVAL_DELAY if first else timedelta(minutes=schedule["minutes"]))
    if schedule["type"] == "daily":
        hour, minute = (int(x) for x in schedule["time"].split(":"))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)
    return None  # scripts déclenchés par événement


class Scheduler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="caffein-scheduler", daemon=True)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        now = datetime.now(config.TIMEZONE)
        for name, spec in JOBS.items():
            nxt = next_run(spec.schedule, now, first=True)
            if nxt:
                NEXT_RUNS[name] = nxt
        log.info("Planificateur démarré : %s", ", ".join(f"{n} → {t:%d/%m %H:%M}" for n, t in NEXT_RUNS.items()))

        while not self._stop_event.wait(TICK_SECONDS):
            now = datetime.now(config.TIMEZONE)
            for name, due in list(NEXT_RUNS.items()):
                if now < due:
                    continue
                if not job_enabled(name):  # module désactivé : le script attend sa réactivation
                    NEXT_RUNS[name] = next_run(JOBS[name].schedule, now)
                    continue
                try:
                    result = run_job(name, trigger="schedule")
                    if result.get("id"):
                        log.info("[%s] %s — %s", name, result["status"], result["summary"])
                except Exception:  # le planificateur ne doit jamais s'arrêter
                    log.exception("Erreur inattendue dans %s", name)
                NEXT_RUNS[name] = next_run(JOBS[name].schedule, datetime.now(config.TIMEZONE))


_instance: Scheduler | None = None


def start_background() -> Scheduler:
    global _instance
    if _instance is None or not _instance.is_alive():
        _instance = Scheduler()
        _instance.start()
    return _instance


def stop_background() -> None:
    if _instance is not None:
        _instance.stop()
