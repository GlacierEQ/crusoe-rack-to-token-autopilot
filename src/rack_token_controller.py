"""Rack-to-Token Autopilot — independent reference implementation.

Convert rack-level power, thermal, network, health, and observed token telemetry
into a bounded operating decision.  The controller optimizes useful token
throughput subject to explicit infrastructure envelopes rather than treating
GPU utilization as the goal.

This module does not integrate or claim access to Crusoe infrastructure.  It is
an open reference controller over caller-supplied telemetry.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


def _finite(value: float, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label}_not_numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label}_not_finite")
    return value


def _ratio(value: float, label: str) -> float:
    value = _finite(value, label)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{label}_out_of_range")
    return value


def _positive(value: float, label: str, *, allow_zero: bool = False) -> float:
    value = _finite(value, label)
    if value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{label}_{'negative' if allow_zero else 'non_positive'}")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RackAction(str, Enum):
    HOLD = "HOLD"
    SCALE_UP = "SCALE_UP"
    SCALE_DOWN = "SCALE_DOWN"
    DRAIN = "DRAIN"
    THERMAL_THROTTLE = "THERMAL_THROTTLE"
    POWER_THROTTLE = "POWER_THROTTLE"
    NETWORK_THROTTLE = "NETWORK_THROTTLE"


class FleetDecision(str, Enum):
    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


@dataclass(frozen=True)
class OperatingEnvelope:
    max_gpu_temp_c: float = 82.0
    max_coolant_delta_c: float = 14.0
    max_power_utilization: float = 0.94
    max_network_utilization: float = 0.92
    max_error_rate: float = 0.02
    min_ready_gpu_ratio: float = 0.90
    min_power_headroom_kw: float = 5.0
    target_gpu_utilization_low: float = 0.68
    target_gpu_utilization_high: float = 0.90
    min_token_efficiency_per_kw: float = 1.0
    reserve_capacity_ratio: float = 0.08

    def validate(self) -> None:
        _finite(self.max_gpu_temp_c, "max_gpu_temp_c")
        _positive(self.max_coolant_delta_c, "max_coolant_delta_c")
        _ratio(self.max_power_utilization, "max_power_utilization")
        _ratio(self.max_network_utilization, "max_network_utilization")
        _ratio(self.max_error_rate, "max_error_rate")
        _ratio(self.min_ready_gpu_ratio, "min_ready_gpu_ratio")
        _positive(self.min_power_headroom_kw, "min_power_headroom_kw", allow_zero=True)
        low = _ratio(self.target_gpu_utilization_low, "target_gpu_utilization_low")
        high = _ratio(self.target_gpu_utilization_high, "target_gpu_utilization_high")
        if low >= high:
            raise ValueError("target_gpu_utilization_bounds_invalid")
        _positive(self.min_token_efficiency_per_kw, "min_token_efficiency_per_kw", allow_zero=True)
        reserve = _ratio(self.reserve_capacity_ratio, "reserve_capacity_ratio")
        if reserve >= 1.0:
            raise ValueError("reserve_capacity_ratio_invalid")


@dataclass(frozen=True)
class RackTelemetry:
    rack_id: str
    gpu_count: int
    ready_gpus: int
    gpu_utilization: float
    max_gpu_temp_c: float
    coolant_supply_c: float
    coolant_return_c: float
    rack_power_kw: float
    rack_power_limit_kw: float
    network_utilization: float
    error_rate: float
    tokens_per_second: float
    queue_depth: int

    def validate(self) -> None:
        if not isinstance(self.rack_id, str) or not self.rack_id.strip():
            raise ValueError("rack_id_missing")
        if not isinstance(self.gpu_count, int) or isinstance(self.gpu_count, bool) or self.gpu_count <= 0:
            raise ValueError("gpu_count_invalid")
        if not isinstance(self.ready_gpus, int) or isinstance(self.ready_gpus, bool) or not 0 <= self.ready_gpus <= self.gpu_count:
            raise ValueError("ready_gpus_invalid")
        _ratio(self.gpu_utilization, "gpu_utilization")
        _finite(self.max_gpu_temp_c, "max_gpu_temp_c")
        supply = _finite(self.coolant_supply_c, "coolant_supply_c")
        returned = _finite(self.coolant_return_c, "coolant_return_c")
        if returned < supply:
            raise ValueError("coolant_return_below_supply")
        power = _positive(self.rack_power_kw, "rack_power_kw", allow_zero=True)
        limit = _positive(self.rack_power_limit_kw, "rack_power_limit_kw")
        if power > limit * 1.20:
            raise ValueError("rack_power_far_above_declared_limit")
        _ratio(self.network_utilization, "network_utilization")
        _ratio(self.error_rate, "error_rate")
        _positive(self.tokens_per_second, "tokens_per_second", allow_zero=True)
        if not isinstance(self.queue_depth, int) or isinstance(self.queue_depth, bool) or self.queue_depth < 0:
            raise ValueError("queue_depth_invalid")

    @property
    def ready_ratio(self) -> float:
        return self.ready_gpus / self.gpu_count

    @property
    def power_utilization(self) -> float:
        return self.rack_power_kw / self.rack_power_limit_kw

    @property
    def power_headroom_kw(self) -> float:
        return max(0.0, self.rack_power_limit_kw - self.rack_power_kw)

    @property
    def coolant_delta_c(self) -> float:
        return self.coolant_return_c - self.coolant_supply_c

    @property
    def token_efficiency_per_kw(self) -> float:
        if self.rack_power_kw <= 0:
            return 0.0
        return self.tokens_per_second / self.rack_power_kw


@dataclass(frozen=True)
class RackDecision:
    rack_id: str
    action: RackAction
    eligible_for_new_work: bool
    safe_token_capacity: float
    token_efficiency_per_kw: float
    reasons: tuple[str, ...]
    metrics: dict[str, float]
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rack_id": self.rack_id,
            "action": self.action.value,
            "eligible_for_new_work": self.eligible_for_new_work,
            "safe_token_capacity": self.safe_token_capacity,
            "token_efficiency_per_kw": self.token_efficiency_per_kw,
            "reasons": list(self.reasons),
            "metrics": self.metrics,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class FleetAllocation:
    decision: FleetDecision
    target_tokens_per_second: float
    allocated_tokens_per_second: float
    unmet_tokens_per_second: float
    assignments: dict[str, float]
    rack_decisions: tuple[RackDecision, ...]
    reasons: tuple[str, ...]
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "target_tokens_per_second": self.target_tokens_per_second,
            "allocated_tokens_per_second": self.allocated_tokens_per_second,
            "unmet_tokens_per_second": self.unmet_tokens_per_second,
            "assignments": dict(sorted(self.assignments.items())),
            "rack_decisions": [item.as_dict() for item in self.rack_decisions],
            "reasons": list(self.reasons),
            "digest": self.digest,
        }


class RackToTokenAutopilot:
    def __init__(self, envelope: OperatingEnvelope = OperatingEnvelope()) -> None:
        envelope.validate()
        self.envelope = envelope

    def evaluate_rack(self, telemetry: RackTelemetry) -> RackDecision:
        telemetry.validate()
        e = self.envelope
        reasons: list[str] = []
        action = RackAction.HOLD
        eligible = True

        if telemetry.ready_ratio < e.min_ready_gpu_ratio or telemetry.error_rate > e.max_error_rate:
            action = RackAction.DRAIN
            eligible = False
            reasons.append("rack_health_envelope_violated")
        elif telemetry.max_gpu_temp_c > e.max_gpu_temp_c or telemetry.coolant_delta_c > e.max_coolant_delta_c:
            action = RackAction.THERMAL_THROTTLE
            eligible = False
            reasons.append("thermal_envelope_violated")
        elif telemetry.power_utilization > e.max_power_utilization or telemetry.power_headroom_kw < e.min_power_headroom_kw:
            action = RackAction.POWER_THROTTLE
            eligible = False
            reasons.append("power_envelope_violated")
        elif telemetry.network_utilization > e.max_network_utilization:
            action = RackAction.NETWORK_THROTTLE
            eligible = False
            reasons.append("network_envelope_violated")
        elif telemetry.token_efficiency_per_kw < e.min_token_efficiency_per_kw and telemetry.gpu_utilization > e.target_gpu_utilization_low:
            action = RackAction.SCALE_DOWN
            reasons.append("token_efficiency_below_floor")
        elif telemetry.gpu_utilization < e.target_gpu_utilization_low and telemetry.queue_depth > 0:
            action = RackAction.SCALE_UP
            reasons.append("queued_work_with_compute_headroom")
        elif telemetry.gpu_utilization > e.target_gpu_utilization_high and telemetry.queue_depth == 0:
            action = RackAction.SCALE_DOWN
            reasons.append("high_utilization_without_queued_demand")
        else:
            reasons.append("operating_envelope_satisfied")

        ready_capacity = telemetry.tokens_per_second * telemetry.ready_ratio
        utilization_headroom = max(0.0, 1.0 - telemetry.gpu_utilization)
        power_headroom_ratio = min(1.0, telemetry.power_headroom_kw / telemetry.rack_power_limit_kw)
        thermal_headroom_ratio = max(
            0.0,
            min(1.0, (e.max_gpu_temp_c - telemetry.max_gpu_temp_c) / max(1.0, e.max_gpu_temp_c - telemetry.coolant_supply_c)),
        )
        growth_ratio = min(utilization_headroom, power_headroom_ratio, thermal_headroom_ratio)
        if eligible:
            estimated_peak = telemetry.tokens_per_second * (1.0 + growth_ratio)
            safe_capacity = estimated_peak * (1.0 - e.reserve_capacity_ratio)
        else:
            safe_capacity = 0.0
        safe_capacity = max(0.0, safe_capacity)

        metrics = {
            "ready_gpu_ratio": round(telemetry.ready_ratio, 12),
            "power_utilization": round(telemetry.power_utilization, 12),
            "power_headroom_kw": round(telemetry.power_headroom_kw, 12),
            "coolant_delta_c": round(telemetry.coolant_delta_c, 12),
            "gpu_utilization": round(telemetry.gpu_utilization, 12),
            "network_utilization": round(telemetry.network_utilization, 12),
            "error_rate": round(telemetry.error_rate, 12),
            "observed_tokens_per_second": round(telemetry.tokens_per_second, 12),
            "ready_observed_token_capacity": round(ready_capacity, 12),
        }
        body = {
            "rack_id": telemetry.rack_id,
            "action": action.value,
            "eligible": eligible,
            "safe_token_capacity": safe_capacity,
            "token_efficiency_per_kw": telemetry.token_efficiency_per_kw,
            "reasons": reasons,
            "metrics": metrics,
        }
        return RackDecision(
            rack_id=telemetry.rack_id,
            action=action,
            eligible_for_new_work=eligible,
            safe_token_capacity=round(safe_capacity, 12),
            token_efficiency_per_kw=round(telemetry.token_efficiency_per_kw, 12),
            reasons=tuple(reasons),
            metrics=metrics,
            digest=_digest(body),
        )

    def allocate_fleet(
        self,
        telemetry: Iterable[RackTelemetry],
        target_tokens_per_second: float,
    ) -> FleetAllocation:
        target = _positive(target_tokens_per_second, "target_tokens_per_second", allow_zero=True)
        rows = list(telemetry)
        if not rows:
            raise ValueError("fleet_empty")
        ids = [row.rack_id for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_rack_id")
        decisions = [self.evaluate_rack(row) for row in rows]
        eligible = [item for item in decisions if item.eligible_for_new_work and item.safe_token_capacity > 0]
        eligible.sort(key=lambda item: (-item.token_efficiency_per_kw, -item.safe_token_capacity, item.rack_id))

        remaining = target
        assignments: dict[str, float] = {}
        for decision in eligible:
            if remaining <= 0:
                break
            amount = min(remaining, decision.safe_token_capacity)
            if amount > 0:
                assignments[decision.rack_id] = round(amount, 12)
                remaining -= amount
        allocated = max(0.0, target - remaining)
        unmet = max(0.0, target - allocated)
        reasons: list[str] = []
        if unmet > 1e-9:
            reasons.append("safe_fleet_capacity_insufficient")
        if not eligible and target > 0:
            reasons.append("no_rack_eligible_for_new_work")
        decision = FleetDecision.REFUSE if reasons else FleetDecision.ALLOW
        if not reasons:
            reasons.append("target_fits_safe_fleet_capacity")

        body = {
            "decision": decision.value,
            "target": target,
            "allocated": allocated,
            "unmet": unmet,
            "assignments": assignments,
            "rack_decision_digests": [item.digest for item in decisions],
            "reasons": reasons,
        }
        return FleetAllocation(
            decision=decision,
            target_tokens_per_second=round(target, 12),
            allocated_tokens_per_second=round(allocated, 12),
            unmet_tokens_per_second=round(unmet, 12),
            assignments=assignments,
            rack_decisions=tuple(decisions),
            reasons=tuple(reasons),
            digest=_digest(body),
        )
