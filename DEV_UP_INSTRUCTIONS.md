# DEV_UP_INSTRUCTIONS — implementation record

**Repository:** `GlacierEQ/crusoe-rack-to-token-autopilot`  
**Independent company lens:** Crusoe  
**Innovation:** Rack-to-Token Autopilot

## Mission

Close the loop between inference behavior and physical rack constraints so throughput gains are accepted only when power, thermal, network, latency, and success-rate contracts remain satisfied.

## Implemented

The former generic allow/refuse scaffold has been replaced by a deterministic rack optimization engine.

`src/rack_to_token_autopilot.py` now:

- validates rack capacity and workload SLOs;
- evaluates multiple measured candidate inference plans;
- rejects GPU, power, thermal, network, throughput, latency, and success-rate violations with explicit reason codes;
- ranks safe candidates by successful tokens per kW with deterministic tie-breaking;
- reports power, thermal, and network headroom;
- emits structured SHA-256 decision receipts.

`src/rack_to_token_cli.py` and `scripts/operate.py` execute the mechanism directly. The project is packaged as a wheel with the `rack-to-token-autopilot` console command.

## Verification contract

`tests/test_rack_to_token_autopilot.py` covers plan selection, thermal refusal, all-plan SLO failure, power/network limits, deterministic tie-breaking, duplicate ids, malformed authority/budget input, and digest sensitivity. Existing adversarial tests remain part of the suite.

CI must pass the native tests, cold-start operation, wheel build/install, and installed CLI execution before any source-bound promotion receipt is minted.

## Truth boundary

No Crusoe affiliation, proprietary access, production deployment, customer impact, or company partnership is claimed. The engine currently consumes supplied observations. A future telemetry adapter may bind it to a permitted simulator or test cluster without weakening the existing constraints.
