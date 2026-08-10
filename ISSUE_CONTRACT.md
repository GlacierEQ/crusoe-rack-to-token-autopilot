# Issue contract — Rack-to-Token Autopilot

## Problem
co-optimizing rack-to-model performance as inference becomes a major workload and energy/network constraints shape economics

## Desired outcome
A bounded, open, testable implementation of **Rack-to-Token Autopilot** that demonstrates Close the loop from model latency/throughput back through GPU placement, network topology, power caps, thermals, and batching to maximize successful tokens/tasks per constrained rack.

## Non-goals
- Crusoe affiliation or proprietary integration
- Portfolio-wide scale/performance claims
- UI marketing site

## Acceptance
1. Mechanism module implements allow + refuse with structured receipts
2. pytest behavioral suite green
3. operate.py cold-start produces JSON receipt
4. Non-affiliation disclaimer preserved
