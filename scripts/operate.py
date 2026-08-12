#!/usr/bin/env python3
"""Exercise both canonical Rack-to-Token mechanisms directly."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rack_to_token_autopilot import Decision, RackToTokenAutopilot, RackToTokenAutopilotRequest  # noqa: E402
from rack_to_token_cli import default_payload  # noqa: E402
from rack_token_controller import FleetDecision, OperatingEnvelope, RackTelemetry, RackToTokenAutopilot as FleetAllocator  # noqa: E402


def main() -> int:
    plan = RackToTokenAutopilot().evaluate(
        RackToTokenAutopilotRequest("rack-demo", default_payload(), 1.0)
    )

    payload = json.loads((ROOT / "examples" / "rack_fleet.json").read_text(encoding="utf-8"))
    fleet = FleetAllocator(OperatingEnvelope(**(payload.get("envelope") or {}))).allocate_fleet(
        [RackTelemetry(**row) for row in payload["racks"]],
        float(payload["target_tokens_per_second"]),
    )

    result = {
        "schema": "glaciereq.rack-to-token-operability.v3",
        "repository": "GlacierEQ/crusoe-rack-to-token-autopilot",
        "plan_optimizer": plan.as_dict(),
        "fleet_allocator": fleet.as_dict(),
        "external_actions_executed": 0,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if plan.decision is Decision.ALLOW and fleet.decision is FleetDecision.ALLOW else 2


if __name__ == "__main__":
    raise SystemExit(main())
