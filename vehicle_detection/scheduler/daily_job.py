"""
Because DailyVehicleCount is keyed by date already (see storage/models.py),
the day boundary handles itself: new counts simply land under a new date
the moment the clock ticks past midnight. No migration/reset job is needed
for correctness.

This module still exists (matching the original design) as a real hook
point for day-boundary features that DO need code to run — e.g. emailing a
daily summary, pushing metrics, pruning old detection_events. For v1 it
just logs yesterday's totals.
"""

import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from storage.models import DailyVehicleCount, VehicleType

logger = logging.getLogger(__name__)


def log_daily_summary(session_factory) -> None:
    session = session_factory()
    try:
        yesterday = date.today() - timedelta(days=1)
        rows = (
            session.query(VehicleType.name, DailyVehicleCount.count)
            .join(DailyVehicleCount, DailyVehicleCount.vehicle_type_id == VehicleType.id)
            .filter(DailyVehicleCount.date == yesterday)
            .all()
        )
        summary = {name: count for name, count in rows}
        logger.info("Daily summary for %s: %s", yesterday.isoformat(), summary)
    finally:
        session.close()


def start_scheduler(session_factory) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: log_daily_summary(session_factory),
        trigger="cron",
        hour=0,
        minute=0,
        id="daily_summary",
    )
    scheduler.start()
    logger.info("Daily summary scheduler started (runs at 00:00 server time)")
    return scheduler
