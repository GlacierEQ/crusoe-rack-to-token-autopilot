#!/usr/bin/env python3
"""Execute the canonical Rack-to-Token mechanism against the repository example."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rack_token_controller import OperatingEnvelope, RackTelemetry, RackToTokenAutopilot  # noqa: E402


def main() -> int:
    payload = json.loads((ROOT / "examples" / "rack_fleet.json").read_text(encoding="utf-8"))
    racks = [RackTelemetry(**row) for row in payload["racks"]]
    receipt = RackToTokenAutopilot(OperatingEnvelope(**(payload.get("envelope") or {}))).allocate_fleet(
        racks, float(payload["target_tokens_per_second"])
    )
    output = {
        "schema": "glaciereq.rack-to-token-operability.v2",
        "repository": "GlacierEQ/crusoe-rack-to-token-autopilot",
        "mechanism": "rack_token_controller.RackToTokenAutopilot.allocate_fleet",
        "result": "PASS" if receipt.decision.value == "ALLOW" else "REFUSE",
        "receipt": receipt.as_dict(),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if receipt.decision.value == "ALLOW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
