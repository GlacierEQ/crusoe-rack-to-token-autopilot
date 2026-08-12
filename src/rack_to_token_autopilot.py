"""Rack-to-Token Autopilot.

Deterministically selects an inference plan from measured rack candidates while
respecting hard power, thermal, network, latency, and success-rate constraints.
The objective is successful tokens per constrained rack-kW, not raw throughput.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _digest(obj: object) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
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


class AutopilotError(ValueError):
    pass


class RackToTokenAutopilot:
    MIN_BUDGET = 0.0

    @staticmethod
    def _number(value: Any, label: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AutopilotError(f"{label}_invalid")
        number = float(value)
        if not math.isfinite(number):
            raise AutopilotError(f"{label}_not_finite")
        if minimum is not None and number < minimum:
            raise AutopilotError(f"{label}_below_minimum")
        if maximum is not None and number > maximum:
            raise AutopilotError(f"{label}_above_maximum")
        return number

    @classmethod
    def _normalize_rack(cls, raw: Any) -> dict[str, float]:
        if not isinstance(raw, dict):
            raise AutopilotError("rack_missing")
        return {
            "gpu_count": cls._number(raw.get("gpu_count"), "rack_gpu_count", minimum=1),
            "power_limit_kw": cls._number(raw.get("power_limit_kw"), "rack_power_limit_kw", minimum=0.001),
            "thermal_limit_c": cls._number(raw.get("thermal_limit_c"), "rack_thermal_limit_c", minimum=-50),
            "network_gbps": cls._number(raw.get("network_gbps"), "rack_network_gbps", minimum=0.001),
        }

    @classmethod
    def _normalize_workload(cls, raw: Any) -> dict[str, float]:
        if not isinstance(raw, dict):
            raise AutopilotError("workload_missing")
        return {
            "required_tokens_per_s": cls._number(raw.get("required_tokens_per_s"), "required_tokens_per_s", minimum=0),
            "max_p95_ms": cls._number(raw.get("max_p95_ms"), "max_p95_ms", minimum=0.001),
            "min_success_rate": cls._number(raw.get("min_success_rate"), "min_success_rate", minimum=0, maximum=1),
        }

    @classmethod
    def _normalize_candidate(cls, raw: Any, index: int) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AutopilotError(f"candidate_{index}_not_object")
        plan_id = str(raw.get("plan_id", "")).strip()
        if not plan_id:
            raise AutopilotError(f"candidate_{index}_plan_id_missing")
        return {
            "plan_id": plan_id,
            "gpu_count": cls._number(raw.get("gpu_count"), f"candidate_{index}_gpu_count", minimum=1),
            "power_kw": cls._number(raw.get("power_kw"), f"candidate_{index}_power_kw", minimum=0.001),
            "temp_c": cls._number(raw.get("temp_c"), f"candidate_{index}_temp_c", minimum=-50),
            "network_gbps": cls._number(raw.get("network_gbps"), f"candidate_{index}_network_gbps", minimum=0),
            "batch_size": cls._number(raw.get("batch_size", 1), f"candidate_{index}_batch_size", minimum=1),
            "tokens_per_s": cls._number(raw.get("tokens_per_s"), f"candidate_{index}_tokens_per_s", minimum=0),
            "p95_ms": cls._number(raw.get("p95_ms"), f"candidate_{index}_p95_ms", minimum=0),
            "success_rate": cls._number(raw.get("success_rate"), f"candidate_{index}_success_rate", minimum=0, maximum=1),
        }

    @staticmethod
    def _candidate_reasons(candidate: dict[str, Any], rack: dict[str, float], workload: dict[str, float]) -> list[str]:
        reasons: list[str] = []
        if candidate["gpu_count"] > rack["gpu_count"]:
            reasons.append("gpu_capacity_exceeded")
        if candidate["power_kw"] > rack["power_limit_kw"]:
            reasons.append("power_limit_exceeded")
        if candidate["temp_c"] > rack["thermal_limit_c"]:
            reasons.append("thermal_limit_exceeded")
        if candidate["network_gbps"] > rack["network_gbps"]:
            reasons.append("network_capacity_exceeded")
        if candidate["tokens_per_s"] < workload["required_tokens_per_s"]:
            reasons.append("throughput_slo_missed")
        if candidate["p95_ms"] > workload["max_p95_ms"]:
            reasons.append("latency_slo_missed")
        if candidate["success_rate"] < workload["min_success_rate"]:
            reasons.append("success_rate_slo_missed")
        return reasons

    @staticmethod
    def _score(candidate: dict[str, Any], rack: dict[str, float]) -> dict[str, float]:
        successful_tokens = candidate["tokens_per_s"] * candidate["success_rate"]
        tokens_per_kw = successful_tokens / candidate["power_kw"]
        power_headroom = max(0.0, rack["power_limit_kw"] - candidate["power_kw"])
        thermal_headroom = max(0.0, rack["thermal_limit_c"] - candidate["temp_c"])
        network_headroom = max(0.0, rack["network_gbps"] - candidate["network_gbps"])
        return {
            "successful_tokens_per_s": round(successful_tokens, 9),
            "successful_tokens_per_kw": round(tokens_per_kw, 9),
            "power_headroom_kw": round(power_headroom, 9),
            "thermal_headroom_c": round(thermal_headroom, 9),
            "network_headroom_gbps": round(network_headroom, 9),
        }

    def evaluate(self, req: RackToTokenAutopilotRequest) -> RackToTokenAutopilotReceipt:
        reasons: list[str] = []
        if not str(req.subject_id or "").strip():
            reasons.append("subject_id_missing")
        try:
            budget = self._number(req.budget, "budget", minimum=0)
        except AutopilotError as exc:
            budget = 0.0
            reasons.append(str(exc))
        if budget <= self.MIN_BUDGET:
            reasons.append("budget_non_positive")

        payload = req.payload if isinstance(req.payload, dict) else {}
        if not isinstance(req.payload, dict):
            reasons.append("payload_not_object")

        eligible: list[tuple[dict[str, Any], dict[str, float]]] = []
        rejected: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        selected_metrics: dict[str, float] | None = None
        try:
            rack = self._normalize_rack(payload.get("rack"))
            workload = self._normalize_workload(payload.get("workload"))
            raw_candidates = payload.get("candidates")
            if not isinstance(raw_candidates, list) or not raw_candidates:
                raise AutopilotError("candidates_missing")
            seen: set[str] = set()
            for index, raw in enumerate(raw_candidates):
                candidate = self._normalize_candidate(raw, index)
                if candidate["plan_id"] in seen:
                    raise AutopilotError(f"duplicate_plan_id:{candidate['plan_id']}")
                seen.add(candidate["plan_id"])
                candidate_reasons = self._candidate_reasons(candidate, rack, workload)
                if candidate_reasons:
                    rejected.append({"plan_id": candidate["plan_id"], "reasons": candidate_reasons})
                    continue
                score = self._score(candidate, rack)
                eligible.append((candidate, score))
            if not eligible:
                raise AutopilotError("no_plan_satisfies_rack_and_workload_contract")
            eligible.sort(
                key=lambda pair: (
                    -pair[1]["successful_tokens_per_kw"],
                    pair[0]["p95_ms"],
                    pair[0]["power_kw"],
                    pair[0]["plan_id"],
                )
            )
            selected, selected_metrics = eligible[0]
        except AutopilotError as exc:
            reasons.append(str(exc))

        decision = Decision.REFUSE if reasons else Decision.ALLOW
        metrics: dict[str, Any] = {
            "objective": "successful_tokens_per_kw",
            "eligible_plan_count": len(eligible),
            "rejected": rejected,
            "selected_plan_id": selected.get("plan_id") if selected else None,
            "selected": selected,
            "selected_metrics": selected_metrics,
        }
        body = {
            "subject_id": req.subject_id,
            "decision": decision.value,
            "reasons": reasons,
            "metrics": metrics,
        }
        return RackToTokenAutopilotReceipt(
            decision=decision,
            reasons=tuple(reasons or ["rack_to_token_plan_selected"]),
            digest=_digest(body),
            metrics=metrics,
        )


Mechanism = RackToTokenAutopilot
