from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from prometheus_adapter import PrometheusMetricMap, rack_telemetry_from_prometheus
from prometheus_rack_cli import main as prometheus_main


METRICS = """
# TYPE rack_gpu_count gauge
rack_gpu_count{rack_id="rack-a"} 8
rack_ready_gpus{rack_id="rack-a"} 8
rack_gpu_utilization_ratio{rack_id="rack-a"} 0.72
rack_gpu_temperature_max_celsius{rack_id="rack-a"} 68
rack_coolant_supply_celsius{rack_id="rack-a"} 21
rack_coolant_return_celsius{rack_id="rack-a"} 29
rack_power_kw{rack_id="rack-a"} 55
rack_power_limit_kw{rack_id="rack-a"} 100
rack_network_utilization_ratio{rack_id="rack-a"} 0.45
rack_error_rate_ratio{rack_id="rack-a"} 0.001
rack_tokens_per_second{rack_id="rack-a"} 1100
rack_queue_depth{rack_id="rack-a"} 4
rack_gpu_count{rack_id="rack-hot"} 8
rack_ready_gpus{rack_id="rack-hot"} 8
rack_gpu_utilization_ratio{rack_id="rack-hot"} 0.91
rack_gpu_temperature_max_celsius{rack_id="rack-hot"} 88
rack_coolant_supply_celsius{rack_id="rack-hot"} 22
rack_coolant_return_celsius{rack_id="rack-hot"} 38
rack_power_kw{rack_id="rack-hot"} 88
rack_power_limit_kw{rack_id="rack-hot"} 100
rack_network_utilization_ratio{rack_id="rack-hot"} 0.50
rack_error_rate_ratio{rack_id="rack-hot"} 0.001
rack_tokens_per_second{rack_id="rack-hot"} 1250
rack_queue_depth{rack_id="rack-hot"} 8
"""


def test_maps_prometheus_samples_into_valid_rack_telemetry() -> None:
    racks = rack_telemetry_from_prometheus(METRICS)
    assert [rack.rack_id for rack in racks] == ["rack-a", "rack-hot"]
    assert racks[0].gpu_count == 8
    assert racks[0].tokens_per_second == 1100.0
    assert racks[1].max_gpu_temp_c == 88.0


def test_refuses_missing_material_metric() -> None:
    broken = METRICS.replace('rack_power_limit_kw{rack_id="rack-a"} 100\n', "")
    with pytest.raises(ValueError, match="prometheus_rack_metrics_missing:rack-a:rack_power_limit_kw"):
        rack_telemetry_from_prometheus(broken)


def test_refuses_duplicate_measurement() -> None:
    duplicate = METRICS + 'rack_power_kw{rack_id="rack-a"} 55\n'
    with pytest.raises(ValueError, match="prometheus_duplicate_measurement:rack-a:rack_power_kw"):
        rack_telemetry_from_prometheus(duplicate)


def test_refuses_fractional_count_metric() -> None:
    fractional = METRICS.replace('rack_gpu_count{rack_id="rack-a"} 8', 'rack_gpu_count{rack_id="rack-a"} 7.5')
    with pytest.raises(ValueError, match="prometheus_integer_metric_fractional:rack-a:gpu_count"):
        rack_telemetry_from_prometheus(fractional)


def test_custom_metric_mapping_is_supported() -> None:
    custom = METRICS.replace("rack_tokens_per_second", "useful_tokens_rate")
    mapping = PrometheusMetricMap(tokens_per_second="useful_tokens_rate")
    racks = rack_telemetry_from_prometheus(custom, mapping)
    assert racks[0].tokens_per_second == 1100.0


def test_live_http_scrape_executes_real_allocation(tmp_path, capsys) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            body = METRICS.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "receipt.json"
    try:
        code = prometheus_main(
            [
                f"http://127.0.0.1:{server.server_address[1]}/metrics",
                "--target-tokens-per-second",
                "700",
                "--output",
                str(output),
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert code == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["source"]["rack_count"] == 2
    assert receipt["allocation"]["decision"] == "ALLOW"
    assert "rack-hot" not in receipt["allocation"]["assignments"]
    assert receipt["allocation"]["assignments"]["rack-a"] == 700.0
