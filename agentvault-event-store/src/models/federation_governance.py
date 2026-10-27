"""Federation governance models — cross-registry proposals to the mainframe.

Three-tier governance:
  Tier 1: LOCAL — agents propose/vote within their registry (existing system)
  Tier 2: FEDERATION PROPOSAL — operator elevates passed local proposal to federation
  Tier 3: MAINFRAME DECISION — commander veto window, then auto-apply
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..database.connection import Base
import uuid


class FederationProposal(Base):
    __tablename__ = "federation_proposals"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    proposal_type = Column(String(50), nullable=False, default="federation_policy_change")
    policy_diff = Column(JSONB, nullable=True)  # Proposed changes as JSON

    # Status: VOTING → PASSED/FAILED → VETOED/APPLIED
    status = Column(String(20), nullable=False, default="VOTING", index=True)

    # Origin: which registry elevated this proposal
    origin_registry_id = Column(String(255), nullable=False)  # SPIFFE ID or operator DID
    origin_proposal_id = Column(Integer, nullable=True)  # Local proposal ID that passed
    origin_tally = Column(JSONB, nullable=True)  # Evidence: {votes_for, votes_against, pass_rate, quorum_met}
    proposer_operator_name = Column(String(200), nullable=False)

    # Thresholds
    quorum_percent = Column(Float, nullable=False, default=20.0)  # 20% of network veToken power
    pass_percent = Column(Float, nullable=False, default=66.0)  # Supermajority
    min_registries = Column(Integer, nullable=False, default=2)  # Votes from ≥ N distinct registries

    # Voting window
    duration_seconds = Column(Integer, nullable=False, default=604800)  # 7 days default
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    end_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # Post-tally
    tallied_at = Column(DateTime(timezone=True), nullable=True)
    veto_deadline = Column(DateTime(timezone=True), nullable=True)  # Set when PASSED
    vetoed_by = Column(String(255), nullable=True)
    veto_reason = Column(String(1000), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)

    # Tally results (stored after tally)
    votes_for = Column(Integer, default=0)
    votes_against = Column(Integer, default=0)
    total_voters = Column(Integer, default=0)
    distinct_registries = Column(Integer, default=0)
    pass_rate = Column(Float, nullable=True)
    quorum_met = Column(Boolean, nullable=True)
    # §MEMBERSHIP D2 (2026-10-02): a BALLOT proposal is decided by one ballot per registry (weight 1), not by agents'
    # power; its tally takes the eligible registries from the host registry and keeps what it counted.
    ballot_mode = Column(Boolean, nullable=False, default=False, server_default="false")
    ballot_summary = Column(JSONB, nullable=True)

    # Relationships
    votes = relationship("FederationVote", back_populates="proposal", cascade="all, delete-orphan")


class FederationVote(Base):
    __tablename__ = "federation_votes"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id = Column(PgUUID(as_uuid=True), ForeignKey("federation_proposals.id"), nullable=False, index=True)
    voter_did = Column(String(255), nullable=False, index=True)
    voter_registry_id = Column(String(255), nullable=False)  # Which registry submitted this vote
    vote_in_favor = Column(Boolean, nullable=False)
    voting_power = Column(Integer, nullable=False)  # veToken power snapshot (trust-weighted)
    raw_voting_power = Column(Integer, nullable=False)  # Original power before trust weighting
    reason = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # §MEMBERSHIP D2: a REGISTRY's ballot (voter_did = voter_registry_id = "registry:<trust domain>/<name>", weight 1)
    choice = Column(String(8), nullable=True)          # for | against | abstain; NULL on an agent's vote
    ballot_jws = Column(Text, nullable=True)            # the signed ballot as delivered (the host registry verified it)
    ballot_basis = Column(JSONB, nullable=True)         # members (the linked local vote) or operator
    eligibility = Column(JSONB, nullable=True)          # the host's eligibility snapshot when the ballot arrived

    # Relationships
    proposal = relationship("FederationProposal", back_populates="votes")

    __table_args__ = (
        UniqueConstraint("proposal_id", "voter_did", name="uix_federation_votes_proposal_voter"),
    )
