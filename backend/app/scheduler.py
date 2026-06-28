"""Scheduler APScheduler: corre el reconciliador cada ``reconcile_interval_seconds``.

``BackgroundScheduler`` corre en su propio hilo, así que el ``subprocess`` de ccusage
(bloqueante) no toca el event loop de FastAPI. Idempotente: arrancar dos veces no crea
dos schedulers.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.services.reconciler import reconcile_once

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job() -> None:
    try:
        reconcile_once()
    except Exception:  # red de seguridad: un fallo del job nunca debe matar el scheduler
        logger.exception("Fallo no controlado en la reconciliación")


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.scheduler_enabled or _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        _job,
        trigger="interval",
        seconds=settings.reconcile_interval_seconds,
        id="reconcile",
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info(
        "Scheduler de reconciliación iniciado (cada %ss)",
        settings.reconcile_interval_seconds,
    )
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
