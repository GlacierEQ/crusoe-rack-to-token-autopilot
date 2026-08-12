from __future__ import annotations

from rack_to_token_autopilot import Decision, RackToTokenAutopilot, RackToTokenAutopilotRequest


def rack(rack_id: str, *, temp: float = 70.0) -> dict[str, object]:
    return {
        "rack_id": rack_id,
        "gpu_count": 8,
        "ready_gpus": 8,
        "gpu_utilization": 0.72,
        "max_gpu_temp_c": temp,
        "coolant_supply_c": 24.0,
        "coolant_return_c": 31.0,
        "rack_power_kw": 60.0,
        "rack_power_limit_kw": 100.0,
        "network_utilization": 0.45,
        "error_rate": 0.001,
        "tokens_per_second": 1000.0,
        "queue_depth": 4,
    }


def test_compatibility_facade_executes_real_allocator() -> None:
    receipt = RackToTokenAutopilot().evaluate(
        RackToTokenAutopilotRequest(
            subject_id="fleet-a",
            payload={"racks": [rack("r1")], "target_tokens_per_second": 500.0},
        )
    )
    assert receipt.decision is Decision.ALLOW
    assert receipt.metrics["assignments"] == {"r1": 500.0}
    assert receipt.metrics["controller_digest"]
    assert "scaffold" not in receipt.metrics


def test_unsafe_capacity_refuses_target() -> None:
    receipt = RackToTokenAutopilot().evaluate(
        RackToTokenAutopilotRequest(
            subject_id="fleet-hot",
            payload={"racks": [rack("hot", temp=95.0)], "target_tokens_per_second": 100.0},
        )
    )
    assert receipt.decision is Decision.REFUSE
    assert receipt.metrics["assignments"] == {}
    assert receipt.metrics["rack_actions"]["hot"] == "THERMAL_THROTTLE"


def test_missing_subject_and_budget_fail_closed() -> None:
    mech = RackToTokenAutopilot()
    assert mech.evaluate(RackToTokenAutopilotRequest(subject_id="", payload={}, budget=1)).decision is Decision.REFUSE
    assert mech.evaluate(RackToTokenAutopilotRequest(subject_id="x", payload={}, budget=0)).decision is Decision.REFUSE


def test_malformed_real_payload_refuses() -> None:
    receipt = RackToTokenAutopilot().evaluate(
        RackToTokenAutopilotRequest(subject_id="fleet", payload={"racks": []})
    )
    assert receipt.decision is Decision.REFUSE
    assert receipt.reasons[0].startswith("invalid_request:")
