from __future__ import annotations

from rack_to_token_autopilot import Decision, RackToTokenAutopilot, RackToTokenAutopilotRequest


def evaluate(candidates: list[dict], *, budget: float = 1.0):
    return RackToTokenAutopilot().evaluate(
        RackToTokenAutopilotRequest(
            subject_id="rack-1",
            budget=budget,
            payload={
                "rack": {
                    "gpu_count": 8,
                    "power_limit_kw": 8.0,
                    "thermal_limit_c": 82.0,
                    "network_gbps": 400.0,
                },
                "workload": {
                    "required_tokens_per_s": 1000.0,
                    "max_p95_ms": 120.0,
                    "min_success_rate": 0.99,
                },
                "candidates": candidates,
            },
        )
    )


def plan(plan_id: str, *, tokens: float, power: float, temp: float = 70.0, latency: float = 90.0, success: float = 0.995, network: float = 200.0) -> dict:
    return {
        "plan_id": plan_id,
        "gpu_count": 8,
        "power_kw": power,
        "temp_c": temp,
        "network_gbps": network,
        "batch_size": 8,
        "tokens_per_s": tokens,
        "p95_ms": latency,
        "success_rate": success,
    }


def test_selects_best_successful_tokens_per_kw() -> None:
    receipt = evaluate([
        plan("fast-hot", tokens=1800, power=7.5),
        plan("efficient", tokens=1600, power=5.0),
    ])
    assert receipt.decision is Decision.ALLOW
    assert receipt.metrics["selected_plan_id"] == "efficient"
    assert receipt.metrics["selected_metrics"]["successful_tokens_per_kw"] > 300
    assert len(receipt.digest) == 64


def test_rejects_thermal_violation_and_selects_safe_alternative() -> None:
    receipt = evaluate([
        plan("too-hot", tokens=2200, power=6.0, temp=90.0),
        plan("safe", tokens=1400, power=5.5, temp=74.0),
    ])
    assert receipt.decision is Decision.ALLOW
    assert receipt.metrics["selected_plan_id"] == "safe"
    assert receipt.metrics["rejected"][0]["reasons"] == ["thermal_limit_exceeded"]


def test_refuses_when_every_plan_misses_slo() -> None:
    receipt = evaluate([
        plan("slow", tokens=900, power=4.0),
        plan("latent", tokens=1500, power=5.0, latency=180.0),
    ])
    assert receipt.decision is Decision.REFUSE
    assert "no_plan_satisfies_rack_and_workload_contract" in receipt.reasons


def test_power_and_network_limits_are_hard_constraints() -> None:
    receipt = evaluate([
        plan("power", tokens=1800, power=9.0),
        plan("network", tokens=1800, power=6.0, network=500.0),
    ])
    assert receipt.decision is Decision.REFUSE
    rejected = {row["plan_id"]: row["reasons"] for row in receipt.metrics["rejected"]}
    assert "power_limit_exceeded" in rejected["power"]
    assert "network_capacity_exceeded" in rejected["network"]


def test_tie_break_is_deterministic() -> None:
    a = plan("b-plan", tokens=1500, power=5.0, latency=80.0)
    b = plan("a-plan", tokens=1500, power=5.0, latency=80.0)
    receipt = evaluate([a, b])
    assert receipt.decision is Decision.ALLOW
    assert receipt.metrics["selected_plan_id"] == "a-plan"


def test_refuses_duplicate_plan_ids() -> None:
    receipt = evaluate([
        plan("same", tokens=1500, power=5.0),
        plan("same", tokens=1600, power=5.5),
    ])
    assert receipt.decision is Decision.REFUSE
    assert "duplicate_plan_id:same" in receipt.reasons


def test_refuses_missing_subject_and_non_positive_budget() -> None:
    receipt = RackToTokenAutopilot().evaluate(
        RackToTokenAutopilotRequest(subject_id=" ", payload={}, budget=0.0)
    )
    assert receipt.decision is Decision.REFUSE
    assert "subject_id_missing" in receipt.reasons
    assert "budget_non_positive" in receipt.reasons


def test_different_candidate_measurements_change_receipt_digest() -> None:
    first = evaluate([plan("p", tokens=1400, power=5.0)])
    second = evaluate([plan("p", tokens=1500, power=5.0)])
    assert first.digest != second.digest
