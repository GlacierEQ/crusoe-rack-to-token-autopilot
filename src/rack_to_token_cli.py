from __future__ import annotations

import argparse
import json
from pathlib import Path

from rack_to_token_autopilot import Decision, RackToTokenAutopilot, RackToTokenAutopilotRequest


def default_payload() -> dict:
    return {
        "rack": {"gpu_count": 8, "power_limit_kw": 8.0, "thermal_limit_c": 82.0, "network_gbps": 400.0},
        "workload": {"required_tokens_per_s": 1000.0, "max_p95_ms": 120.0, "min_success_rate": 0.99},
        "candidates": [
            {"plan_id": "throughput", "gpu_count": 8, "power_kw": 7.4, "temp_c": 76.0, "network_gbps": 240.0, "batch_size": 16, "tokens_per_s": 1800.0, "p95_ms": 98.0, "success_rate": 0.995},
            {"plan_id": "efficient", "gpu_count": 8, "power_kw": 5.1, "temp_c": 70.0, "network_gbps": 190.0, "batch_size": 8, "tokens_per_s": 1600.0, "p95_ms": 86.0, "success_rate": 0.997},
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Select a rack-constrained inference plan")
    parser.add_argument("--input", type=Path, help="JSON payload; defaults to built-in demo")
    parser.add_argument("--subject", default="rack-demo")
    parser.add_argument("--budget", type=float, default=1.0)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text()) if args.input else default_payload()
    receipt = RackToTokenAutopilot().evaluate(RackToTokenAutopilotRequest(args.subject, payload, args.budget))
    print(json.dumps(receipt.as_dict(), sort_keys=True, indent=2))
    return 0 if receipt.decision is Decision.ALLOW else 2


if __name__ == "__main__":
    raise SystemExit(main())
