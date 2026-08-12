"""Scrape a Prometheus endpoint and run Rack-to-Token allocation."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from prometheus_adapter import PrometheusMetricMap, rack_telemetry_from_prometheus
from rack_token_controller import OperatingEnvelope, RackToTokenAutopilot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape open Prometheus rack metrics and allocate safe useful-token throughput")
    parser.add_argument("url")
    parser.add_argument("--target-tokens-per-second", type=float, required=True)
    parser.add_argument("--config", type=Path, help="optional JSON with metric_map and envelope")
    parser.add_argument("--bearer-token-env")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = {}
        if args.config:
            config = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("config_must_be_object")
        metric_map = PrometheusMetricMap(**(config.get("metric_map") or {}))
        envelope = OperatingEnvelope(**(config.get("envelope") or {}))
        headers = {"Accept": "text/plain; version=0.0.4"}
        if args.bearer_token_env:
            token = os.environ.get(args.bearer_token_env)
            if not token:
                raise ValueError("bearer_token_missing")
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(args.url, headers=headers)
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            if response.status != 200:
                raise ValueError(f"prometheus_http_status:{response.status}")
            text = response.read(8 * 1024 * 1024 + 1).decode("utf-8")
        if len(text.encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("prometheus_response_too_large")
        racks = rack_telemetry_from_prometheus(text, metric_map)
        receipt = RackToTokenAutopilot(envelope).allocate_fleet(racks, args.target_tokens_per_second)
        output = {
            "source": {"url": args.url, "rack_count": len(racks)},
            "allocation": receipt.as_dict(),
        }
        rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        sys.stdout.write(rendered)
        return 0 if receipt.decision.value == "ALLOW" else 2
    except Exception as exc:
        sys.stderr.write(json.dumps({"decision": "ERROR", "reason": f"{type(exc).__name__}:{exc}"}, sort_keys=True) + "\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
