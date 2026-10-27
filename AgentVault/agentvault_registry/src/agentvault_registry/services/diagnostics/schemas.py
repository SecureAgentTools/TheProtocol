"""Pydantic schemas for the Command Center diagnostics API."""

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


CheckStatus = Literal["ok", "warn", "fail", "unknown"]
TargetStatus = Literal["healthy", "degraded", "down", "unknown"]


class RemediationHint(BaseModel):
    action_id: str
    description: str
    destructive: bool = False
    requires_confirmation: bool = True


class CheckResult(BaseModel):
    check_id: str
    target: str
    status: CheckStatus
    latency_ms: int
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    evidence: str = ""
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    remediation: Optional[RemediationHint] = None

    def truncate_evidence(self, max_bytes: int = 4096) -> "CheckResult":
        if len(self.evidence) > max_bytes:
            self.evidence = self.evidence[:max_bytes] + "\n…[truncated]"
        return self


class CheckDescriptor(BaseModel):
    check_id: str
    title: str
    description: str
    cost_ms: int
    category: Literal["supply", "spire", "teg", "network", "kafka", "leader", "logs", "certs", "config"]


class TargetSummary(BaseModel):
    operator_id: str
    display_name: str
    # The frame the target belongs to: this registry's own name, or "T" for an ephemeral frame-test's chained
    # operator (§FEFRAME W4 residue, V0521). Was Literal["A", "B", "C", "T"]: the retired frames' letters, with every
    # operator on every current frame labelled "A". A widening that forgets the schema 500s (§SWEEPFIX, 2026-07-30).
    frame: str
    role: Literal["mainframe", "operator", "frame"]   # "frame": this registry itself when it is a frame (§MCPTEST30 V0562)
    cloud_url: Optional[str] = None
    # §MCPTEST30 (V0562): this registry itself (targets.self_target), a frame ("frame") or an operator ("operator": its
    # Command Center lists itself too, and the frame-only checks do not apply to it)
    is_self: bool = False
    status: TargetStatus = "unknown"
    last_snapshot_at: Optional[datetime] = None
    check_results: list[CheckResult] = Field(default_factory=list)


class RunRequest(BaseModel):
    check_ids: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    force: bool = False


class RunAllRequest(BaseModel):
    target: str
    force: bool = False


class ActionRequest(BaseModel):
    target: str
    dry_run: bool = False


class ActionResult(BaseModel):
    action_id: str
    target: str
    status: Literal["ok", "fail", "skipped"]
    summary: str
    evidence: str = ""
    dry_run: bool = False
    triggered_check: Optional[CheckResult] = None
    invoked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
