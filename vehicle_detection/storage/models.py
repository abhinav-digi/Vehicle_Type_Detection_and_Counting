"""
Data model.

Design choice worth calling out: counts are keyed by (date, vehicle_type_id)
in a single table rather than split into separate "live" and "history"
tables. Today's counts ARE the row where date = today; once the date rolls
over, new increments simply land under a new date key. There is no data to
physically move at midnight, which is what FR3 ("reset to new date, keep
history date-wise") asks for — it falls out of the schema for free instead
of needing an explicit, failure-prone migration step.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .db import Base


class VehicleType(Base):
    __tablename__ = "vehicle_types"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DailyVehicleCount(Base):
    __tablename__ = "daily_vehicle_counts"
    __table_args__ = (UniqueConstraint("date", "vehicle_type_id"),)

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, index=True)
    vehicle_type_id = Column(Integer, ForeignKey("vehicle_types.id"), nullable=False)
    count = Column(Integer, default=0, nullable=False)

    vehicle_type = relationship("VehicleType")


class DetectionEvent(Base):
    """
    Raw per-vehicle event log. Not required for the counts themselves, but
    cheap to keep and useful for debugging or re-aggregating counts later if
    a counting bug is ever found after the fact.
    """

    __tablename__ = "detection_events"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    source_id = Column(String, nullable=False, index=True)
    vehicle_type_id = Column(Integer, ForeignKey("vehicle_types.id"), nullable=False)
    track_id = Column(Integer, nullable=False)

    vehicle_type = relationship("VehicleType")
