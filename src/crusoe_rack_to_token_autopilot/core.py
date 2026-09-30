"""Datacenter Compute & GPU Cluster Orchestration — Core Module"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

class GPUType(Enum):
    H100 = auto()
    A100 = auto()
    H200 = auto()
    B200 = auto()
    TPU_V5P = auto()

GPU_TDP = {
    GPUType.H100: 700,
    GPUType.A100: 400,
    GPUType.H200: 700,
    GPUType.B200: 1000,
    GPUType.TPU_V5P: 300,
}

GPU_MEMORY_GB = {
    GPUType.H100: 80,
    GPUType.A100: 80,
    GPUType.H200: 141,
    GPUType.B200: 192,
    GPUType.TPU_V5P: 95,
}

@dataclass
class RackNode:
    """A single compute node in a rack."""
    node_id: str
    gpu_type: GPUType
    gpu_count: int
    utilization: float = 0.0    # 0.0 to 1.0
    temp_celsius: float = 45.0
    power_draw_w: float = 0.0

    @property
    def memory_total_gb(self) -> float:
        return GPU_MEMORY_GB[self.gpu_type] * self.gpu_count

    @property
    def tdp_total_w(self) -> int:
        return GPU_TDP[self.gpu_type] * self.gpu_count

    @property
    def is_throttled(self) -> bool:
        return self.temp_celsius > 83.0

    @property
    def power_efficiency(self) -> float:
        """FLOPS per watt proxy: utilization / power_fraction."""
        power_frac = self.power_draw_w / self.tdp_total_w if self.tdp_total_w > 0 else 1.0
        return self.utilization / power_frac if power_frac > 0 else 0.0


@dataclass
class ClusterMetrics:
    """Aggregate metrics for a GPU cluster."""
    nodes: list[RackNode] = field(default_factory=list)

    @property
    def total_gpus(self) -> int:
        return sum(n.gpu_count for n in self.nodes)

    @property
    def avg_utilization(self) -> float:
        if not self.nodes:
            return 0.0
        return sum(n.utilization for n in self.nodes) / len(self.nodes)

    @property
    def total_power_kw(self) -> float:
        return sum(n.power_draw_w for n in self.nodes) / 1000.0

    @property
    def throttled_nodes(self) -> list[RackNode]:
        return [n for n in self.nodes if n.is_throttled]

    @property
    def total_memory_tb(self) -> float:
        return sum(n.memory_total_gb for n in self.nodes) / 1024.0

    def pue(self, cooling_overhead_kw: float) -> float:
        """Power Usage Effectiveness = (Total Facility Power) / (IT Power)."""
        it_power = self.total_power_kw
        if it_power <= 0:
            return 1.0
        return (it_power + cooling_overhead_kw) / it_power

