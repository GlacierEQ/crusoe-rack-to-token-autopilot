"""Prometheus exposition adapter for Rack-to-Token Autopilot.

The adapter is deliberately vendor-neutral. Operators map their metric names to
RackTelemetry fields; each sample must carry a rack identity label. The parser
supports Prometheus text exposition metric lines and refuses missing, duplicate,
non-finite, or non-integral measurements required by the controller.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from rack_token_controller import RackTelemetry

_SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?:\s+\d+)?$"
)
_LABEL_RE = re.compile(r'(?:^|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"((?:\\.|[^"\\])*)"\s*')


@dataclass(frozen=True)
class PrometheusMetricMap:
    rack_label: str = "rack_id"
    gpu_count: str = "rack_gpu_count"
    ready_gpus: str = "rack_ready_gpus"
    gpu_utilization: str = "rack_gpu_utilization_ratio"
    max_gpu_temp_c: str = "rack_gpu_temperature_max_celsius"
    coolant_supply_c: str = "rack_coolant_supply_celsius"
    coolant_return_c: str = "rack_coolant_return_celsius"
    rack_power_kw: str = "rack_power_kw"
    rack_power_limit_kw: str = "rack_power_limit_kw"
    network_utilization: str = "rack_network_utilization_ratio"
    error_rate: str = "rack_error_rate_ratio"
    tokens_per_second: str = "rack_tokens_per_second"
    queue_depth: str = "rack_queue_depth"

    def fields(self) -> dict[str, str]:
        return {
            "gpu_count": self.gpu_count,
            "ready_gpus": self.ready_gpus,
            "gpu_utilization": self.gpu_utilization,
            "max_gpu_temp_c": self.max_gpu_temp_c,
            "coolant_supply_c": self.coolant_supply_c,
            "coolant_return_c": self.coolant_return_c,
            "rack_power_kw": self.rack_power_kw,
            "rack_power_limit_kw": self.rack_power_limit_kw,
            "network_utilization": self.network_utilization,
            "error_rate": self.error_rate,
            "tokens_per_second": self.tokens_per_second,
            "queue_depth": self.queue_depth,
        }

    def validate(self) -> None:
        if not isinstance(self.rack_label, str) or not self.rack_label:
            raise ValueError("prometheus_rack_label_invalid")
        values = list(self.fields().values())
        if not all(isinstance(value, str) and value for value in values):
            raise ValueError("prometheus_metric_name_invalid")
        if len(values) != len(set(values)):
            raise ValueError("prometheus_metric_names_duplicate")


def _unescape_label(value: str) -> str:
    return value.replace(r"\n", "\n").replace(r'\"', '"').replace(r"\\", "\\")


def _labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    labels: dict[str, str] = {}
    position = 0
    while position < len(raw):
        match = _LABEL_RE.match(raw, position)
        if match is None:
            raise ValueError("prometheus_labels_invalid")
        key = match.group(1)
        if key in labels:
            raise ValueError("prometheus_duplicate_label")
        labels[key] = _unescape_label(match.group(2))
        position = match.end()
        if position < len(raw) and raw[position] == ",":
            position += 1
    return labels


def parse_prometheus_samples(text: str) -> list[tuple[str, dict[str, str], float]]:
    if not isinstance(text, str):
        raise ValueError("prometheus_text_invalid")
    samples: list[tuple[str, dict[str, str], float]] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_RE.match(line)
        if match is None:
            raise ValueError(f"prometheus_sample_invalid:line={line_number}")
        value = float(match.group("value"))
        if not math.isfinite(value):
            raise ValueError(f"prometheus_sample_non_finite:line={line_number}")
        samples.append((match.group("name"), _labels(match.group("labels")), value))
    return samples


def rack_telemetry_from_prometheus(
    text: str,
    metric_map: PrometheusMetricMap = PrometheusMetricMap(),
) -> tuple[RackTelemetry, ...]:
    metric_map.validate()
    reverse = {metric_name: field for field, metric_name in metric_map.fields().items()}
    racks: dict[str, dict[str, float]] = {}
    observed: set[tuple[str, str]] = set()
    for metric_name, labels, value in parse_prometheus_samples(text):
        field = reverse.get(metric_name)
        if field is None:
            continue
        rack_id = labels.get(metric_map.rack_label)
        if not rack_id or not rack_id.strip():
            raise ValueError(f"prometheus_rack_label_missing:{metric_name}")
        rack_id = rack_id.strip()
        identity = (rack_id, field)
        if identity in observed:
            raise ValueError(f"prometheus_duplicate_measurement:{rack_id}:{field}")
        observed.add(identity)
        racks.setdefault(rack_id, {})[field] = value
    if not racks:
        raise ValueError("prometheus_no_rack_measurements")

    required = set(metric_map.fields())
    result: list[RackTelemetry] = []
    for rack_id in sorted(racks):
        row = racks[rack_id]
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"prometheus_rack_metrics_missing:{rack_id}:{','.join(missing)}")
        integer_fields = ("gpu_count", "ready_gpus", "queue_depth")
        converted: dict[str, object] = {}
        for field, value in row.items():
            if field in integer_fields:
                if not float(value).is_integer():
                    raise ValueError(f"prometheus_integer_metric_fractional:{rack_id}:{field}")
                converted[field] = int(value)
            else:
                converted[field] = float(value)
        telemetry = RackTelemetry(rack_id=rack_id, **converted)  # type: ignore[arg-type]
        telemetry.validate()
        result.append(telemetry)
    return tuple(result)
