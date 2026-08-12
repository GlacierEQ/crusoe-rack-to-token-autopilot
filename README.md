# Rack-to-Token Autopilot

Independent GlacierEQ rack-aware inference control software. It now preserves **two complementary mechanisms** instead of forcing one implementation to erase the other:

1. **Plan optimizer** — selects a measured inference plan that satisfies GPU, rack-power, thermal, network, throughput, p95-latency, and success-rate contracts while maximizing successful tokens per rack-kW.
2. **Telemetry allocator** — converts per-rack telemetry into safe useful-token capacity, allocates a fleet token target only from eligible capacity, and runs a stateful confirmation/cooldown/emergency loop with optional bounded Prometheus ingestion.

> **Not affiliated.** This repository is not affiliated with, endorsed by, employed by, or deployed at Crusoe. No proprietary access, production deployment, customer impact, company partnership, physical-control authority, or production-scale reliability claim is made.

## Why both belong here

Canonical main independently evolved the original API into a strong rack-constrained **candidate-plan optimizer**. The crystallization branch independently built the next depth step main's own documentation identified: a telemetry-bound rack allocator, state loop, and Prometheus adapter. They solve adjacent layers of the same purpose and do not need to cannibalize each other.

### Plan optimizer

`src/rack_to_token_autopilot.py` accepts:

- rack envelope: GPU count, power limit, thermal ceiling, network capacity;
- workload contract: minimum tokens/s, maximum p95 latency, minimum success rate;
- measured candidate plans with placement/batch plus power, thermal, network, throughput, latency, and success observations.

Unsafe candidates receive explicit refusal reasons. Eligible candidates rank deterministically by successful tokens/kW, then latency, power, and stable plan id.

### Telemetry allocator

`src/rack_token_controller.py` consumes per-rack GPU readiness/utilization, temperature/coolant, power, network, error rate, queue depth, and observed token throughput. It:

- emits HOLD / SCALE_UP / SCALE_DOWN / DRAIN / THERMAL_THROTTLE / POWER_THROTTLE / NETWORK_THROTTLE decisions;
- derives safe useful-token capacity from observed headroom and reserve policy;
- refuses a fleet target when safe aggregate capacity cannot satisfy it;
- ranks eligible rack capacity by observed token efficiency;
- produces deterministic allocation receipts.

`src/autopilot_loop.py` adds confirmation hysteresis, cooldown, emergency override, allocation materiality, and deterministic state persistence. `src/prometheus_adapter.py` and `src/prometheus_rack_cli.py` add a bounded open-Prometheus ingestion path with completeness and ambiguity checks.

## Install and run

```bash
python -m pip install .

# Stable plan-selection API/CLI
rack-to-token-autopilot
rack-to-token-autopilot --input rack-observations.json

# Telemetry-driven fleet allocation
rack-to-token examples/rack_fleet.json
rack-to-token-fleet examples/rack_fleet.json

# Bounded Prometheus source
rack-to-token-prometheus http://127.0.0.1:9090/metrics --target-tokens-per-second 12000
```

Direct combined operability probe:

```bash
python scripts/operate.py
```

## Proof surface

- `tests/test_rack_to_token_autopilot.py` — plan-selection, SLO, thermal/power/network, duplicate, tie-break, and digest behavior
- `tests/test_rack_token_controller.py` — telemetry decisions and fleet allocation/refusal
- `tests/test_autopilot_loop.py` — stateful confirmation/cooldown/emergency/persistence behavior
- `tests/test_prometheus_adapter.py` — parser and ingestion boundary
- `tests/test_adversarial.py` — fail-closed adversarial surface
- `.github/workflows/` — build/install, installed CLIs, direct runtime, state-loop, and Prometheus proof
- `machine/crystallization/` — explicit purpose, capabilities, gaps, execution plan, and source-bound completion receipts

## Completion boundary

The repository is complete as an **independent local/reference rack-inference control system** when both mechanisms build, install, execute, and pass their behavior/failure proofs with no material local-purpose gaps. Production attachment to a real rack or workload authority is a separate environment-specific integration and cannot be inferred from local completion.
