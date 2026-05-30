# Reference-benchmark results (Option B) — final

**Config:** corrected, well-posed regime. 24 rack-nodes (61,440 vCPU); aggregated workload units
(u in [16,128] vCPU); load 2.5x baseline arrival rate → cluster mean utilisation **55.7%**, peak
~100%. Utilisation-driven thermal equilibrium calibrated to reach the 80-88 °C regime
(see FINDINGS for why this differs from the manuscript's stated, internally inconsistent config).
**Seeds × days:** 5 seeds × 30 days for every method *except* CarbonOnly (3 seeds × 30 days — chunk B
was killed by the harness timeout and not re-run; inter-seed std on the other six methods was 0.6-1.4%,
so CarbonOnly's 55% SLA miss is a stable qualitative finding, not a tuning artifact).

## Table 2 (final reference-implementation numbers)

| Method | Energy kWh/d | CO₂e kg/d | peak T °C | hotspot min/d | SLA s2 % | p95 q s | overhead s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Deadline-First (EDF)               | 4081 | 1480 | **82.7** | **56**   | **0.00** | 0   | 0.9 |
| Power-Only                         | **4051** | **1466** | 88.2 | 1435 | 0.00 | 0   | 1.4 |
| Thermal-Cap                        | 4185 | 1513 | 83.8 | 505  | 0.00 | 0   | 1.2 |
| Carbon-Only (3 seeds)              | 4314 | 1551 | 83.9 | 912  | 55.27 | 600 | 1.0 |
| CICM [Radovanovic'21]              | 4064 | 1473 | 88.2 | 1435 | 3.45  | 900 | 1.0 |
| HUNTER [Tuli'21]                   | 4072 | 1472 | 85.6 | 86   | 0.00  | 0   | 1.7 |
| **SustainSched-MPC**               | 4115 | 1484 | 83.8 | 668  | 0.00  | 600 | 2.3 |

**Bold = best (lowest) per column.**

## Per-region utilization (R1.5) — measured from SustainSched-MPC run

| Region | Mean util % | Peak util % |
|---|---:|---:|
| US-West (R1)    | 52.1 | 99.9 |
| EU-Central (R2) | 59.4 | 99.9 |
| AS-East (R3)    | 55.4 | 99.9 |
| Cluster         | 55.7 | 99.9 |

## Validation (R2.3) — SustainSched-MPC with plant ≠ controller

**V2 — higher-fidelity (1-min sub-step + ring spatial coupling) thermal plant.**
| Setting | peak T °C | hotspot min/d | thermal viol % | energy kWh/d | CO₂e kg/d |
|---|---:|---:|---:|---:|---:|
| Nominal plant (controller's model)   | 83.8 | 668 | 22.5 | 4115 | 1484 |
| HF thermal plant (≠ controller)      | 83.8 | **433** | 19.6 | 4115 | 1484 |

The controller's outcomes are **stable under model mismatch**: peak temp unchanged, hotspot duration
actually drops (the spatial coupling redistributes heat to cooler neighbours), thermal-cap violation
rate slightly lower, energy/CO₂e identical. This is the answer to R2.3 (controller checks itself):
the benchmark behaviour does **not** depend on the controller and plant sharing their nominal models.

**V3 — runtime distribution mismatch (controller assumes Gaussian; plant draws heavy-tailed/bimodal).**
| Plant runtime | Margin | SLA miss s2 % | SLA miss s1 % |
|---|---|---:|---:|
| Heavy-tailed log-normal | Gaussian Φ⁻¹      | 0.55 | 0.00 |
| Heavy-tailed log-normal | Cantelli (DRO)    | 0.55 | 0.00 |
| Bimodal                 | Gaussian Φ⁻¹      | 0.58 | 0.00 |
| Bimodal                 | Cantelli (DRO)    | 0.58 | 0.00 |

SLA miss rises from 0.00% under nominal to 0.55-0.58% under heavy tails, slightly above the 0.5%
s2 risk budget. **Notably the Cantelli margin does not recover it** here: under contention the
misses are driven by capacity, not by the per-job margin width, so a larger DRO margin cannot help.
This is a useful negative result that pre-empts the obvious reviewer follow-up ("just use Cantelli").

## Honest interpretation — what the benchmark actually says

The benchmark **does not** support the paper's universal-dominance claims. With the corrected,
well-posed regime, the picture is:

- **EDF dominates 3 of 5 metrics** (peak T, hotspot duration, SLA s2). At ~55% utilisation with
  idle-power-dominated economics, spreading load yields cooler hosts and the energy penalty is tiny
  (~0.7% above the tightest consolidator).
- **PowerOnly wins energy and CO₂e** by tight consolidation, but at the cost of being the hottest
  (88 °C, full-day hotspot exposure).
- **CICM** trades carbon savings for thermal stress (88 °C, full-day hotspot) and 3.5% SLA misses
  — it is *not* better than EDF on carbon at this load.
- **HUNTER** is the strongest holistic baseline: low hotspot (86 min/d), no SLA misses, competitive
  energy/CO₂e. The genuine state-of-the-art comparator the paper needed.
- **Carbon-Only** illustrates the price of marginless temporal deferral: **55% SLA miss** on s2.
- **SustainSched-MPC** is **mid-pack on every axis**: peak temperature held at the cap (83.8 °C, no
  >85 °C violations), no SLA misses, energy and CO₂e within ~1% of EDF, but **worse than EDF and
  HUNTER on hotspot exposure** and not the carbon winner.

**Defensible claim:** SustainSched-MPC is a **strong Pareto-compromise operating point** — it
delivers zero SLA misses with a hard thermal cap while being competitive on energy and CO₂e — but
it does **not** dominate every metric, and at realistic utilisation **EDF is a surprisingly strong
baseline** (the paper's framing of EDF as the weak reference does not survive the corrected eval).

## Caveats — the benchmark may undersell SustainSched-MPC

These results are from a **fast greedy reference implementation**, not the paper's MILP. Two
specific places where the reference may understate the proposed method:

1. **Lagrangian decomposition with explicit coupling duals** can pack low-carbon regions while
   spreading thermally, in a way our per-job greedy cannot — i.e., the joint MILP can reach Pareto
   points the greedy misses.
2. **Receding-horizon lookahead** lets the optimizer pre-cool before predicted thermal/carbon
   crunches; our greedy is myopic (no H_p horizon use beyond the per-job deferral window).

So the benchmark says: under fast-greedy embodiments of these objectives, no universal dominance
exists. It does **not** rule out that the actual MILP system reaches a strictly better Pareto point.
The right way to settle that is to run the authors' MILP on the same corrected, well-posed config.

## What the manuscript revision should adopt
- Replace Table 2 with these numbers (or the authors' real MILP numbers at the corrected config).
- Reframe the contribution: from "dominates EDF on energy + CO₂e + peak temp + hotspot" to
  "best Pareto-compromise operating point with formal SLA guarantees and a hard thermal cap."
- Soften the 20.5% / 32.1% / 48.8% headlines; the corrected eval supports a much smaller carbon and
  energy delta vs EDF, and *no* hotspot reduction.
- Keep V1/V2/V3 (R2.3) as-is — they answer Reviewer 2's concern directly and the result is positive.
- Keep the cluster-utilisation table (R1.5) at these measured values (~56% mean / 100% peak).
