"""Federation operator model for per-operator event authentication."""
from sqlalchemy import Column, String, Integer, Float, DateTime
from sqlalchemy.sql import func
from ..database.connection import Base


class FederationOperator(Base):
    __tablename__ = "federation_operators"

    id = Column(String(36), primary_key=True)
    operator_name = Column(String(200), nullable=False)
    license_key_hash = Column(String(64), nullable=False, unique=True, index=True)
    spiffe_id = Column(String(255), nullable=True, unique=True, index=True)  # mTLS identity
    status = Column(String(20), nullable=False, default="active")  # active, suspended, revoked
    max_events_per_minute = Column(Integer, default=1000)
    event_count = Column(Integer, default=0)
    last_event_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # SF-5B: Bayesian trust discount — synced from registry PeerRegistry.bayesian_discount
    bayesian_discount = Column(Float, nullable=False, default=1.0, server_default="1.0")
