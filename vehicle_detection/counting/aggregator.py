"""
Owns the "count a vehicle exactly once" rule (FR1) and the vehicle-type
registry (FR2).

Counting rule for v1 (documented assumption, see design doc open question 1):
a vehicle is counted the moment its track_id is first seen — not when it
crosses a line/zone. Simpler, and matches the original ask; revisit if
directional/zone-based counting is needed later.

Known v1 limitation (design doc open question 2): the "already counted"
set is in-memory per source. If the process restarts mid-stream, a vehicle
still in frame could be counted again. Acceptable for a single-camera POC;
would need a durable/track-resumption strategy to fix for production.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from storage.models import DailyVehicleCount, DetectionEvent, VehicleType
from tracking.base import TrackedDetection

logger = logging.getLogger(__name__)


class VehicleCounter:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._counted_keys: set[tuple[str, int]] = set()  # (source_id, track_id)

    def process(
        self,
        tracked_detections: List[TrackedDetection],
        source_id: str,
        event_time: datetime | None = None,
    ) -> None:
        event_time = event_time or datetime.utcnow()
        today = event_time.date()

        new_ones = [
            td
            for td in tracked_detections
            if (source_id, td.track_id) not in self._counted_keys
        ]
        if not new_ones:
            return

        session: Session = self._session_factory()
        try:
            for td in new_ones:
                self._counted_keys.add((source_id, td.track_id))
                vehicle_type = self._get_or_create_vehicle_type(
                    session, td.class_name, event_time
                )
                self._increment_daily_count(session, today, vehicle_type.id)
                session.add(
                    DetectionEvent(
                        timestamp=event_time,
                        source_id=source_id,
                        vehicle_type_id=vehicle_type.id,
                        track_id=td.track_id,
                    )
                )
            session.commit()
            logger.info(
                "Counted %d new unique vehicle(s) from source=%s: %s",
                len(new_ones),
                source_id,
                [d.class_name for d in new_ones],
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _get_or_create_vehicle_type(
        session: Session, name: str, seen_at: datetime
    ) -> VehicleType:
        vehicle_type = session.query(VehicleType).filter_by(name=name).first()
        if vehicle_type is not None:
            return vehicle_type

        # Two different NEW track_ids of a type never seen before can arrive
        # in the same frame (e.g. two cars entering together), and two
        # concurrent sources (two streams, or a stream + an upload) can
        # discover the same new type at the same time in separate sessions.
        # Either way, a second "not found -> insert" can race the first.
        # A SAVEPOINT lets us attempt the insert and, if it collides,
        # roll back just that attempt and re-read what the winner wrote —
        # without losing any other pending changes in this session/batch.
        try:
            with session.begin_nested():
                vehicle_type = VehicleType(name=name, first_seen_at=seen_at)
                session.add(vehicle_type)
                session.flush()
            logger.info("New vehicle type registered: %s", name)
            return vehicle_type
        except IntegrityError:
            return session.query(VehicleType).filter_by(name=name).one()

    @staticmethod
    def _increment_daily_count(session: Session, date_, vehicle_type_id: int) -> None:
        row = (
            session.query(DailyVehicleCount)
            .filter_by(date=date_, vehicle_type_id=vehicle_type_id)
            .first()
        )
        if row is not None:
            row.count += 1
            return

        # Same race as above, one level down: multiple new vehicles of the
        # SAME type in one frame (e.g. two cars, both first seen this
        # frame) would otherwise both try to insert today's first row for
        # that type.
        try:
            with session.begin_nested():
                row = DailyVehicleCount(date=date_, vehicle_type_id=vehicle_type_id, count=1)
                session.add(row)
                session.flush()
        except IntegrityError:
            row = (
                session.query(DailyVehicleCount)
                .filter_by(date=date_, vehicle_type_id=vehicle_type_id)
                .one()
            )
            row.count += 1
