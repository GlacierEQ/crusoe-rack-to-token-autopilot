"""Auto-generated tests for Datacenter Compute & GPU Cluster Orchestration."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crusoe_rack_to_token_autopilot.core import GPUType, RackNode, ClusterMetrics

def test_node_memory():
    node = RackNode("n1", GPUType.H100, 8)
    assert node.memory_total_gb == 640.0

def test_node_tdp():
    node = RackNode("n1", GPUType.H100, 8)
    assert node.tdp_total_w == 5600

def test_throttle_detection():
    node = RackNode("n1", GPUType.A100, 4, temp_celsius=85.0)
    assert node.is_throttled

def test_no_throttle():
    node = RackNode("n1", GPUType.A100, 4, temp_celsius=60.0)
    assert not node.is_throttled

def test_cluster_total_gpus():
    cluster = ClusterMetrics(nodes=[
        RackNode("n1", GPUType.H100, 8),
        RackNode("n2", GPUType.H100, 8),
    ])
    assert cluster.total_gpus == 16

def test_cluster_utilization():
    cluster = ClusterMetrics(nodes=[
        RackNode("n1", GPUType.H100, 8, utilization=0.8),
        RackNode("n2", GPUType.H100, 8, utilization=0.6),
    ])
    assert abs(cluster.avg_utilization - 0.7) < 0.001

def test_pue():
    cluster = ClusterMetrics(nodes=[
        RackNode("n1", GPUType.H100, 8, power_draw_w=4000.0),
    ])
    pue = cluster.pue(cooling_overhead_kw=0.4)
    assert pue > 1.0
    assert pue < 2.0

def test_total_memory_tb():
    cluster = ClusterMetrics(nodes=[
        RackNode("n1", GPUType.B200, 8),
        RackNode("n2", GPUType.B200, 8),
    ])
    assert cluster.total_memory_tb == (192 * 16) / 1024.0

