"""CLI for Rack-to-Token Autopilot decisions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rack_token_controller import OperatingEnvelope, RackTelemetry, RackToTokenAutopilot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Allocate useful token throughput across racks under power/thermal/network/health envelopes")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input_must_be_object")
        envelope = OperatingEnvelope(**(payload.get("envelope") or {}))
        rows = payload.get("racks")
        if not isinstance(rows, list):
            raise ValueError("racks_missing")
        racks = [RackTelemetry(**row) for row in rows]
        controller = RackToTokenAutopilot(envelope)
        receipt = controller.allocate_fleet(racks, float(payload.get("target_tokens_per_second", 0.0)))
        rendered = json.dumps(receipt.as_dict(), indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        sys.stdout.write(rendered)
        return 0 if receipt.decision.value == "ALLOW" else 2
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(json.dumps({"decision": "ERROR", "reason": str(exc)}, sort_keys=True) + "\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
