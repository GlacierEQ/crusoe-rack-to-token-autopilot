from __future__ import annotations

import pytest

from rack_token_controller import (
    FleetDecision,
    OperatingEnvelope,
    RackAction,
    RackTelemetry,
    RackToTokenAutopilot,
)


def rack(
    rack_id: str,
    *,
    gpu_utilization: float = 0.75,
    max_gpu_temp_c: float = 70.0,
    coolant_supply_c: float = 22.0,
    coolant_return_c: float = 30.0,
    rack_power_kw: float = 70.0,
    rack_power_limit_kw: float = 100.0,
    network_utilization: float = 0.50,
    error_rate: float = 0.0,
    tokens_per_second: float = 1000.0,
    queue_depth: int = 1,
    gpu_count: int = 8,
    ready_gpus: int = 8,
) -> RackTelemetry:
    return RackTelemetry(
        rack_id=rack_id,
        gpu_count=gpu_count,
        ready_gpus=ready_gpus,
        gpu_utilization=gpu_utilization,
        max_gpu_temp_c=max_gpu_temp_c,
        coolant_supply_c=coolant_supply_c,
        coolant_return_c=coolant_return_c,
        rack_power_kw=rack_power_kw,
        rack_power_limit_kw=rack_power_limit_kw,
        network_utilization=network_utilization,
        error_rate=error_rate,
        tokens_per_second=tokens_per_second,
        queue_depth=queue_depth,
    )


def test_healthy_rack_is_eligible_with_content_addressed_decision() -> None:
    result = RackToTokenAutopilot().evaluate_rack(rack("r1"))
    assert result.eligible_for_new_work is True
    assert result.safe_token_capacity > 0
    assert result.token_efficiency_per_kw > 0
    assert len(result.digest) == 64


def test_thermal_violation_throttles_and_refuses_new_work() -> None:
    result = RackToTokenAutopilot().evaluate_rack(rack("hot", max_gpu_temp_c=90.0))
    assert result.action is RackAction.THERMAL_THROTTLE
    assert result.eligible_for_new_work is False
    assert result.safe_token_capacity == 0.0
    assert "thermal_envelope_violated" in result.reasons


def test_coolant_delta_violation_is_thermal_failure_even_when_gpu_sensor_is_cool() -> None:
    result = RackToTokenAutopilot().evaluate_rack(
        rack("coolant", max_gpu_temp_c=68.0, coolant_supply_c=20.0, coolant_return_c=38.0)
    )
    assert result.action is RackAction.THERMAL_THROTTLE
    assert result.eligible_for_new_work is False


def test_power_envelope_violation_throttles_before_scheduling_more_tokens() -> None:
    result = RackToTokenAutopilot().evaluate_rack(
        rack("power", rack_power_kw=96.0, rack_power_limit_kw=100.0)
    )
    assert result.action is RackAction.POWER_THROTTLE
    assert result.eligible_for_new_work is False


def test_network_saturation_is_a_distinct_control_reason() -> None:
    result = RackToTokenAutopilot().evaluate_rack(rack("net", network_utilization=0.97))
    assert result.action is RackAction.NETWORK_THROTTLE
    assert result.eligible_for_new_work is False


def test_degraded_ready_gpu_ratio_drains_rack() -> None:
    result = RackToTokenAutopilot().evaluate_rack(rack("degraded", gpu_count=8, ready_gpus=6))
    assert result.action is RackAction.DRAIN
    assert result.eligible_for_new_work is False


def test_low_utilization_with_queue_requests_scale_up() -> None:
    result = RackToTokenAutopilot().evaluate_rack(rack("headroom", gpu_utilization=0.40, queue_depth=9))
    assert result.action is RackAction.SCALE_UP
    assert result.eligible_for_new_work is True


def test_low_token_efficiency_can_scale_down_even_when_rack_is_safe() -> None:
    envelope = OperatingEnvelope(min_token_efficiency_per_kw=20.0)
    result = RackToTokenAutopilot(envelope).evaluate_rack(
        rack("inefficient", rack_power_kw=80.0, tokens_per_second=800.0, gpu_utilization=0.80)
    )
    assert result.action is RackAction.SCALE_DOWN
    assert "token_efficiency_below_floor" in result.reasons


def test_fleet_allocates_most_efficient_safe_rack_first() -> None:
    result = RackToTokenAutopilot().allocate_fleet(
        [
            rack("efficient", rack_power_kw=50.0, tokens_per_second=1000.0),
            rack("less-efficient", rack_power_kw=80.0, tokens_per_second=1000.0),
        ],
        target_tokens_per_second=900.0,
    )
    assert result.decision is FleetDecision.ALLOW
    assert result.assignments == {"efficient": 900.0}
    assert result.unmet_tokens_per_second == 0.0


def test_fleet_never_allocates_to_unsafe_rack() -> None:
    result = RackToTokenAutopilot().allocate_fleet(
        [rack("hot", max_gpu_temp_c=90.0), rack("safe", tokens_per_second=800.0)],
        target_tokens_per_second=500.0,
    )
    assert result.decision is FleetDecision.ALLOW
    assert "hot" not in result.assignments
    assert result.assignments["safe"] == 500.0


def test_fleet_refuses_when_safe_capacity_cannot_meet_target() -> None:
    result = RackToTokenAutopilot().allocate_fleet(
        [rack("only", tokens_per_second=100.0, rack_power_kw=50.0)],
        target_tokens_per_second=5000.0,
    )
    assert result.decision is FleetDecision.REFUSE
    assert result.unmet_tokens_per_second > 0
    assert "safe_fleet_capacity_insufficient" in result.reasons


def test_invalid_non_finite_telemetry_fails_closed() -> None:
    with pytest.raises(ValueError, match="gpu_utilization_not_finite"):
        RackToTokenAutopilot().evaluate_rack(rack("bad", gpu_utilization=float("nan")))


def test_duplicate_rack_identity_is_refused() -> None:
    controller = RackToTokenAutopilot()
    with pytest.raises(ValueError, match="duplicate_rack_id"):
        controller.allocate_fleet([rack("same"), rack("same")], 100.0)


def test_decision_digest_changes_when_operating_state_changes() -> None:
    controller = RackToTokenAutopilot()
    first = controller.evaluate_rack(rack("r", gpu_utilization=0.70))
    second = controller.evaluate_rack(rack("r", gpu_utilization=0.50))
    assert first.digest != second.digest
