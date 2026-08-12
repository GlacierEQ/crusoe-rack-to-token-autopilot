# Rack-to-Token Autopilot

Independent GlacierEQ portfolio implementation aligned to **Crusoe** operating themes.

> **Not affiliated.** This repository is not affiliated with, endorsed by, employed by, or deployed at Crusoe. No proprietary access, production deployment, customer impact, or company partnership is claimed.

## Purpose

Optimize inference at the **rack constraint boundary**, not at an isolated model benchmark. Candidate execution plans are evaluated against GPU capacity, rack power, thermals, network capacity, throughput, p95 latency, and successful-request rate.

The selected plan maximizes **successful tokens per rack-kW** while satisfying every hard infrastructure and workload SLO. A faster plan that overheats the rack, overruns network capacity, misses latency, or burns too much power is rejected instead of being celebrated by a vanity benchmark.

## Implemented mechanism

`RackToTokenAutopilot` accepts:

- rack envelope: GPU count, power limit, thermal ceiling, network capacity;
- workload contract: minimum tokens/s, maximum p95 latency, minimum success rate;
- measured candidate plans: placement/batch configuration plus power, thermal, network, throughput, latency, and success observations.

For every candidate it emits explicit refusal reasons such as:

- `gpu_capacity_exceeded`
- `power_limit_exceeded`
- `thermal_limit_exceeded`
- `network_capacity_exceeded`
- `throughput_slo_missed`
- `latency_slo_missed`
- `success_rate_slo_missed`

Eligible plans are ranked deterministically by successful tokens/kW, then latency, power, and stable plan id. The receipt includes the selected plan, rejected-plan reasons, headroom metrics, and a SHA-256 decision digest.

## Run

```bash
python -m pytest -q
python scripts/operate.py
```

Build and install the CLI:

```bash
python -m pip install build
python -m build
python -m pip install dist/*.whl
rack-to-token-autopilot
```

Provide your own JSON payload:

```bash
rack-to-token-autopilot --input rack-observations.json
```

## Proof surface

- `src/rack_to_token_autopilot.py` — constrained optimizer
- `src/rack_to_token_cli.py` — installable execution surface
- `tests/test_rack_to_token_autopilot.py` — rack/SLO/thermal/power/network/tie-break behavior
- `tests/test_adversarial.py` — fail-closed adversarial surface
- `.github/workflows/tests.yml` — tests + cold-start + wheel build/install + installed CLI execution
- `machine/` — existing Helix target, proof, authority, and promotion surfaces remain preserved

## Current boundary

This operates on supplied or measured observations; it does not control real Crusoe infrastructure and does not claim production measurements. The next infrastructure depth step is an adapter that ingests telemetry from a disposable GPU/rack simulator or permitted test cluster and closes the loop across repeated observations.
