# Rack-to-Token Autopilot

An independent, local-first rack control reference that converts rack telemetry into **bounded useful-token allocation decisions** under explicit thermal, coolant, power, network, health, and reserve-capacity envelopes.

> **Independent portfolio project.** No Crusoe affiliation, endorsement, proprietary access, production deployment, customer impact, or company-internal performance claim is made.

## What works

The repository now has one real operating center:

- `src/rack_token_controller.py` validates rack telemetry, evaluates per-rack safety, estimates safe token capacity, and allocates a fleet target without consuming unsafe capacity.
- `src/autopilot_loop.py` adds stateful confirmation hysteresis, cooldown, emergency override, allocation materiality, and deterministic state persistence.
- `src/prometheus_adapter.py` maps open Prometheus text exposition into the rack telemetry contract with fail-closed completeness and ambiguity checks.
- `src/prometheus_rack_cli.py` performs a bounded HTTP scrape and runs the allocator against the observed metrics.
- `src/rack_token_cli.py` runs the same controller against a JSON fleet snapshot.
- `src/rack_to_token_autopilot.py` is a compatibility facade over the real controller. It no longer contains a scaffold mechanism.

The optimization target is not GPU utilization by itself. The controller allocates requested useful-token throughput only from racks that remain inside the configured operating envelope, ranking eligible capacity by observed token efficiency.

## Install and run

```bash
python -m pip install .
rack-to-token examples/rack_fleet.json
```

The example emits a deterministic JSON receipt. An impossible fleet target or unsafe fleet returns `REFUSE` rather than pretending the requested throughput was achieved.

For a Prometheus source:

```bash
rack-to-token-prometheus http://127.0.0.1:9090/metrics \
  --target-tokens-per-second 12000
```

Bearer authentication, when needed, is read only from an explicitly named environment variable via `--bearer-token-env`; token values are not written into receipts.

## Control semantics

A rack can be held, scaled up/down, drained, or throttled for thermal, power, or network reasons. New work is excluded when rack health, readiness, thermal, power, network, or error-rate boundaries fail. Fleet allocation refuses when safe aggregate capacity cannot satisfy the requested token target.

The stateful loop prevents noisy telemetry from turning into action thrash: ordinary changes require confirmation, cooldown suppresses rapid reversals, materiality suppresses meaningless allocation churn, and emergency actions bypass those delays.

## Evidence

Repository-owned CI exercises:

- rack and fleet behavioral/refusal tests;
- stateful hysteresis, cooldown, emergency, persistence, and reallocation tests;
- Prometheus parsing failures and a real local HTTP scrape path;
- package build/install and installed CLI execution;
- compatibility-facade behavior;
- machine crystallization manifests and empty-gap consistency.

`machine/crystallization/` is the machine-readable purpose/capability/proof surface. A terminal `CRYSTALLIZED` receipt is issued only after the exact canonicalized head passes those gates.

## Evidence boundary

This is a reference control system over caller-supplied or operator-authorized telemetry. It does **not** establish production fleet safety, production workload authority, physical hardware control, real Crusoe deployment, proprietary telemetry, measured customer benefit, or production-scale reliability. Those claims would require separate environment-specific authority and receipts.
