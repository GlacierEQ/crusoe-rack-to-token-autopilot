from __future__ import annotations

from autopilot_loop import AutopilotState, LoopPolicy, RackToTokenControlLoop
from rack_token_controller import RackAction, RackTelemetry


def rack(
    rack_id: str = "r1",
    *,
    util: float = 0.75,
    temp: float = 70.0,
    tokens: float = 1000.0,
    power: float = 70.0,
    queue: int = 1,
) -> RackTelemetry:
    return RackTelemetry(
        rack_id=rack_id,
        gpu_count=8,
        ready_gpus=8,
        gpu_utilization=util,
        max_gpu_temp_c=temp,
        coolant_supply_c=21.0,
        coolant_return_c=29.0,
        rack_power_kw=power,
        rack_power_limit_kw=100.0,
        network_utilization=0.50,
        error_rate=0.0,
        tokens_per_second=tokens,
        queue_depth=queue,
    )


def test_scale_change_requires_consecutive_confirmation() -> None:
    loop = RackToTokenControlLoop(policy=LoopPolicy(confirmation_cycles=2, cooldown_cycles=0))
    first = loop.step([rack(util=0.40, queue=5)], 500.0)
    assert first.rack_actions["r1"] is RackAction.HOLD
    assert first.suppressed_actions["r1"] == "awaiting_confirmation"
    second = loop.step([rack(util=0.40, queue=5)], 500.0)
    assert second.rack_actions["r1"] is RackAction.SCALE_UP


def test_emergency_thermal_action_bypasses_hysteresis() -> None:
    loop = RackToTokenControlLoop(policy=LoopPolicy(confirmation_cycles=5, cooldown_cycles=3))
    receipt = loop.step([rack(temp=90.0)], 500.0)
    assert receipt.rack_actions["r1"] is RackAction.THERMAL_THROTTLE
    assert "r1" not in receipt.suppressed_actions


def test_cooldown_prevents_immediate_flip_after_emergency() -> None:
    loop = RackToTokenControlLoop(policy=LoopPolicy(confirmation_cycles=1, cooldown_cycles=2))
    first = loop.step([rack(temp=90.0)], 500.0)
    assert first.rack_actions["r1"] is RackAction.THERMAL_THROTTLE
    second = loop.step([rack(util=0.40, temp=70.0, queue=5)], 500.0)
    assert second.rack_actions["r1"] is RackAction.THERMAL_THROTTLE
    assert second.suppressed_actions["r1"] == "cooldown_active"


def test_tiny_allocation_change_is_held_to_avoid_churn() -> None:
    loop = RackToTokenControlLoop(
        policy=LoopPolicy(confirmation_cycles=1, cooldown_cycles=0, min_reallocation_ratio=0.10)
    )
    first = loop.step([rack("a", tokens=1000), rack("b", tokens=900)], 1000.0)
    second = loop.step([rack("a", tokens=995), rack("b", tokens=905)], 1000.0)
    assert second.applied_assignments == first.applied_assignments
    assert second.suppressed_actions["__allocation__"] == "reallocation_below_materiality_threshold"


def test_material_allocation_change_is_applied() -> None:
    loop = RackToTokenControlLoop(
        policy=LoopPolicy(confirmation_cycles=1, cooldown_cycles=0, min_reallocation_ratio=0.05)
    )
    first = loop.step([rack("a", tokens=1000, power=50), rack("b", tokens=900, power=80)], 1000.0)
    second = loop.step([rack("a", temp=90.0, tokens=1000, power=50), rack("b", tokens=900, power=80)], 700.0)
    assert second.applied_assignments != first.applied_assignments
    assert "a" not in second.applied_assignments
    assert second.rack_actions["a"] is RackAction.THERMAL_THROTTLE


def test_state_round_trip_preserves_control_memory() -> None:
    loop = RackToTokenControlLoop(policy=LoopPolicy(confirmation_cycles=2, cooldown_cycles=1))
    loop.step([rack(util=0.40, queue=5)], 500.0)
    state = AutopilotState.from_dict(loop.state.as_dict())
    restored = RackToTokenControlLoop(
        policy=LoopPolicy(confirmation_cycles=2, cooldown_cycles=1),
        state=state,
    )
    next_receipt = restored.step([rack(util=0.40, queue=5)], 500.0)
    assert next_receipt.rack_actions["r1"] is RackAction.SCALE_UP
    assert next_receipt.cycle == 2
    assert len(next_receipt.digest) == 64
