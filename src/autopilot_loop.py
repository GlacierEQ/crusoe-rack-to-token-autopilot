"""Stateful Rack-to-Token Autopilot control loop.

The underlying controller computes a safe decision from each telemetry sample.
This loop adds operational semantics needed for repeated execution:

- emergency safety actions apply immediately;
- non-emergency scale changes require consecutive confirmation samples;
- a cooldown prevents command flapping;
- token allocation changes below a configurable materiality threshold are held;
- serialized state is deterministic and can be persisted by the caller.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from rack_token_controller import (
    FleetAllocation,
    FleetDecision,
    RackAction,
    RackTelemetry,
    RackToTokenAutopilot,
)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


EMERGENCY_ACTIONS = {
    RackAction.DRAIN,
    RackAction.THERMAL_THROTTLE,
    RackAction.POWER_THROTTLE,
    RackAction.NETWORK_THROTTLE,
}


@dataclass(frozen=True)
class LoopPolicy:
    confirmation_cycles: int = 2
    cooldown_cycles: int = 2
    min_reallocation_ratio: float = 0.05

    def validate(self) -> None:
        if not isinstance(self.confirmation_cycles, int) or isinstance(self.confirmation_cycles, bool) or self.confirmation_cycles < 1:
            raise ValueError("confirmation_cycles_invalid")
        if not isinstance(self.cooldown_cycles, int) or isinstance(self.cooldown_cycles, bool) or self.cooldown_cycles < 0:
            raise ValueError("cooldown_cycles_invalid")
        if not isinstance(self.min_reallocation_ratio, (int, float)) or isinstance(self.min_reallocation_ratio, bool):
            raise ValueError("min_reallocation_ratio_invalid")
        if not 0.0 <= float(self.min_reallocation_ratio) <= 1.0:
            raise ValueError("min_reallocation_ratio_out_of_range")


@dataclass
class RackLoopState:
    applied_action: RackAction = RackAction.HOLD
    candidate_action: RackAction = RackAction.HOLD
    candidate_cycles: int = 0
    cooldown_remaining: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied_action": self.applied_action.value,
            "candidate_action": self.candidate_action.value,
            "candidate_cycles": self.candidate_cycles,
            "cooldown_remaining": self.cooldown_remaining,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RackLoopState":
        if not isinstance(raw, Mapping):
            raise ValueError("rack_loop_state_invalid")
        candidate_cycles = raw.get("candidate_cycles", 0)
        cooldown = raw.get("cooldown_remaining", 0)
        if not isinstance(candidate_cycles, int) or candidate_cycles < 0:
            raise ValueError("candidate_cycles_invalid")
        if not isinstance(cooldown, int) or cooldown < 0:
            raise ValueError("cooldown_remaining_invalid")
        return cls(
            applied_action=RackAction(raw.get("applied_action", RackAction.HOLD.value)),
            candidate_action=RackAction(raw.get("candidate_action", RackAction.HOLD.value)),
            candidate_cycles=candidate_cycles,
            cooldown_remaining=cooldown,
        )


@dataclass
class AutopilotState:
    cycle: int = 0
    racks: dict[str, RackLoopState] = field(default_factory=dict)
    last_assignments: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "racks": {key: self.racks[key].as_dict() for key in sorted(self.racks)},
            "last_assignments": dict(sorted(self.last_assignments.items())),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AutopilotState":
        if not isinstance(raw, Mapping):
            raise ValueError("autopilot_state_invalid")
        cycle = raw.get("cycle", 0)
        if not isinstance(cycle, int) or cycle < 0:
            raise ValueError("cycle_invalid")
        racks_raw = raw.get("racks") or {}
        assignments_raw = raw.get("last_assignments") or {}
        if not isinstance(racks_raw, Mapping) or not isinstance(assignments_raw, Mapping):
            raise ValueError("autopilot_state_collections_invalid")
        assignments: dict[str, float] = {}
        for key, value in assignments_raw.items():
            if not isinstance(key, str) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError("last_assignments_invalid")
            assignments[key] = float(value)
        return cls(
            cycle=cycle,
            racks={str(key): RackLoopState.from_dict(value) for key, value in racks_raw.items()},
            last_assignments=assignments,
        )


@dataclass(frozen=True)
class LoopReceipt:
    cycle: int
    fleet_decision: FleetDecision
    target_tokens_per_second: float
    proposed_assignments: dict[str, float]
    applied_assignments: dict[str, float]
    rack_actions: dict[str, RackAction]
    suppressed_actions: dict[str, str]
    fleet_metrics: dict[str, float]
    state: dict[str, Any]
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "fleet_decision": self.fleet_decision.value,
            "target_tokens_per_second": self.target_tokens_per_second,
            "proposed_assignments": dict(sorted(self.proposed_assignments.items())),
            "applied_assignments": dict(sorted(self.applied_assignments.items())),
            "rack_actions": {key: value.value for key, value in sorted(self.rack_actions.items())},
            "suppressed_actions": dict(sorted(self.suppressed_actions.items())),
            "fleet_metrics": self.fleet_metrics,
            "state": self.state,
            "digest": self.digest,
        }


class RackToTokenControlLoop:
    def __init__(
        self,
        controller: RackToTokenAutopilot | None = None,
        policy: LoopPolicy = LoopPolicy(),
        state: AutopilotState | None = None,
    ) -> None:
        policy.validate()
        self.controller = controller or RackToTokenAutopilot()
        self.policy = policy
        self.state = state or AutopilotState()

    def _apply_action(self, rack_id: str, candidate: RackAction) -> tuple[RackAction, str | None]:
        state = self.state.racks.setdefault(rack_id, RackLoopState())
        if candidate in EMERGENCY_ACTIONS:
            state.applied_action = candidate
            state.candidate_action = candidate
            state.candidate_cycles = self.policy.confirmation_cycles
            state.cooldown_remaining = self.policy.cooldown_cycles
            return candidate, None

        if state.cooldown_remaining > 0:
            state.cooldown_remaining -= 1
            return state.applied_action, "cooldown_active"

        if candidate == state.applied_action:
            state.candidate_action = candidate
            state.candidate_cycles = 0
            return state.applied_action, None

        if candidate != state.candidate_action:
            state.candidate_action = candidate
            state.candidate_cycles = 1
        else:
            state.candidate_cycles += 1

        if state.candidate_cycles >= self.policy.confirmation_cycles:
            state.applied_action = candidate
            state.candidate_cycles = 0
            state.cooldown_remaining = self.policy.cooldown_cycles
            return candidate, None
        return state.applied_action, "awaiting_confirmation"

    def _material_allocation_change(self, proposed: Mapping[str, float]) -> bool:
        previous = self.state.last_assignments
        keys = set(previous).union(proposed)
        previous_total = sum(previous.values())
        proposed_total = sum(proposed.values())
        denominator = max(1.0, previous_total, proposed_total)
        movement = sum(abs(float(proposed.get(key, 0.0)) - float(previous.get(key, 0.0))) for key in keys)
        return movement / denominator >= self.policy.min_reallocation_ratio

    def step(self, telemetry: Iterable[RackTelemetry], target_tokens_per_second: float) -> LoopReceipt:
        rows = list(telemetry)
        allocation: FleetAllocation = self.controller.allocate_fleet(rows, target_tokens_per_second)
        decisions = {item.rack_id: item for item in allocation.rack_decisions}
        self.state.cycle += 1
        applied_actions: dict[str, RackAction] = {}
        suppressed: dict[str, str] = {}
        for rack_id in sorted(decisions):
            action, reason = self._apply_action(rack_id, decisions[rack_id].action)
            applied_actions[rack_id] = action
            if reason is not None:
                suppressed[rack_id] = reason

        proposed = dict(allocation.assignments)
        emergency_changed = any(decisions[rack_id].action in EMERGENCY_ACTIONS for rack_id in decisions)
        if not self.state.last_assignments or emergency_changed or self._material_allocation_change(proposed):
            applied = proposed
            self.state.last_assignments = dict(proposed)
        else:
            applied = dict(self.state.last_assignments)
            suppressed["__allocation__"] = "reallocation_below_materiality_threshold"

        total_power = sum(row.rack_power_kw for row in rows)
        total_tokens = sum(row.tokens_per_second for row in rows)
        ready_gpus = sum(row.ready_gpus for row in rows)
        all_gpus = sum(row.gpu_count for row in rows)
        metrics = {
            "observed_tokens_per_second": round(total_tokens, 12),
            "rack_power_kw": round(total_power, 12),
            "fleet_token_efficiency_per_kw": round(total_tokens / total_power, 12) if total_power > 0 else 0.0,
            "ready_gpu_ratio": round(ready_gpus / all_gpus, 12) if all_gpus else 0.0,
            "allocated_tokens_per_second": round(sum(applied.values()), 12),
            "unmet_tokens_per_second": allocation.unmet_tokens_per_second,
        }
        state_doc = self.state.as_dict()
        body = {
            "cycle": self.state.cycle,
            "fleet_decision": allocation.decision.value,
            "target": allocation.target_tokens_per_second,
            "proposed": proposed,
            "applied": applied,
            "rack_actions": {key: value.value for key, value in applied_actions.items()},
            "suppressed": suppressed,
            "metrics": metrics,
            "state": state_doc,
        }
        return LoopReceipt(
            cycle=self.state.cycle,
            fleet_decision=allocation.decision,
            target_tokens_per_second=allocation.target_tokens_per_second,
            proposed_assignments=proposed,
            applied_assignments=applied,
            rack_actions=applied_actions,
            suppressed_actions=suppressed,
            fleet_metrics=metrics,
            state=state_doc,
            digest=_digest(body),
        )
