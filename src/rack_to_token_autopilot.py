"""Compatibility facade over the real Rack-to-Token controller.

The historical repository exposed ``RackToTokenAutopilot.evaluate(request)``.
That API is preserved, but it now executes the real fleet allocator instead of
a scaffold allow/refuse stub.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from rack_token_controller import (
    FleetDecision,
    OperatingEnvelope,
    RackTelemetry,
    RackToTokenAutopilot as FleetController,
)


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


@dataclass(frozen=True)
class RackToTokenAutopilotRequest:
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    budget: float = 1.0
    grant_id: str | None = None
    not_after: float | None = None


@dataclass(frozen=True)
class RackToTokenAutopilotReceipt:
    decision: Decision
    reasons: tuple[str, ...]
    digest: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "digest": self.digest,
            "metrics": self.metrics,
        }


class RackToTokenAutopilot:
    """Backward-compatible request facade for the canonical fleet controller.

    ``payload`` must contain ``racks`` and ``target_tokens_per_second`` and may
    contain an ``envelope`` object. ``budget`` remains a compatibility admission
    field only; physical capacity is always derived from telemetry/envelopes.
    """

    def evaluate(self, req: RackToTokenAutopilotRequest) -> RackToTokenAutopilotReceipt:
        reasons: list[str] = []
        if not isinstance(req.subject_id, str) or not req.subject_id.strip():
            reasons.append("subject_id_missing")
        if not isinstance(req.budget, (int, float)) or isinstance(req.budget, bool) or req.budget <= 0:
            reasons.append("budget_non_positive")
        if reasons:
            body = {"subject_id": req.subject_id, "budget": req.budget, "reasons": reasons}
            return RackToTokenAutopilotReceipt(Decision.REFUSE, tuple(reasons), _digest(body))

        try:
            rows = req.payload.get("racks")
            if not isinstance(rows, list):
                raise ValueError("racks_missing")
            target = float(req.payload["target_tokens_per_second"])
            envelope_raw = req.payload.get("envelope") or {}
            if not isinstance(envelope_raw, dict):
                raise ValueError("envelope_must_be_object")
            controller = FleetController(OperatingEnvelope(**envelope_raw))
            allocation = controller.allocate_fleet([RackTelemetry(**row) for row in rows], target)
        except (KeyError, TypeError, ValueError) as exc:
            reason = f"invalid_request:{exc}"
            body = {"subject_id": req.subject_id, "reason": reason}
            return RackToTokenAutopilotReceipt(Decision.REFUSE, (reason,), _digest(body))

        decision = Decision.ALLOW if allocation.decision is FleetDecision.ALLOW else Decision.REFUSE
        metrics = {
            "subject_id": req.subject_id,
            "compatibility_budget": float(req.budget),
            "target_tokens_per_second": allocation.target_tokens_per_second,
            "allocated_tokens_per_second": allocation.allocated_tokens_per_second,
            "unmet_tokens_per_second": allocation.unmet_tokens_per_second,
            "assignments": dict(allocation.assignments),
            "rack_actions": {row.rack_id: row.action.value for row in allocation.rack_decisions},
            "controller_digest": allocation.digest,
        }
        body = {
            "subject_id": req.subject_id,
            "budget": float(req.budget),
            "grant_id": req.grant_id,
            "decision": decision.value,
            "allocation_digest": allocation.digest,
            "reasons": allocation.reasons,
        }
        return RackToTokenAutopilotReceipt(
            decision=decision,
            reasons=allocation.reasons,
            digest=_digest(body),
            metrics=metrics,
        )


Mechanism = RackToTokenAutopilot
