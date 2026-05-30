# Findings from building the reference simulator

I implemented a complete, dependency-free reference simulator (`sim.py`) of the paper's
power / RC-thermal / carbon models and all seven schedulers (EDF, PowerOnly, ThermalCap,
CarbonOnly, CICM, HUNTER, SustainSchedMPC), plus the V1–V3 validation plants. The code runs
and the validation hooks (`--plant hf`, `--runtime-dist heavy|bimodal`, `--margin cantelli`)
work. **However, running it surfaced three concrete inconsistencies in the manuscript's stated
experimental configuration that prevent the reported numbers from being reproduced, and that a
reviewer could find by the same route.** These need to be resolved before the new baselines and
validation experiments can produce trustworthy numbers.

## Evidence (from actual runs of `sim.py`)

| Config | EDF energy | EDF peakT | EDF hotspot | Notes |
|---|---|---|---|---|
| Stated trace (`--load 1`) | ~1094 kWh/day | 62 °C | 0 min/day | no method exceeds ~73 °C; **0 hotspots for all 7** |
| 40× load | ~2136 | 65 °C | 0 | PowerOnly peak only 77 °C |
| 60× load | ~2136 | 65 °C | 0 | only CICM/CarbonOnly cross 80 °C, via runaway bursting |

## Inconsistency 1 — the stated workload utilizes only ~2.6 % of the cluster
Offered load = 18,240 jobs/day × mean 9 vCPU × mean runtime ÷ (61,440 vCPU × day) ≈ **2.6 %**.
The whole cluster needs ≈ **one** active rack-node for the stated trace. At that load there is no
resource contention, scheduling is near-trivial, and **no policy generates thermal stress**
(measured peak ≈ 62–73 °C, 0 hotspot-minutes). The paper's reported peak temperatures (80–87 °C)
and hotspot durations (54–178 min/day) cannot arise at this utilization.
**Fix:** right-size the experiment so peak utilization is ~60–90 % — either reduce per-node
capacity / node count, or raise the trace intensity (the simulator's `--load` knob does this;
~15–25× reproduces a meaningfully loaded cluster). Then report the utilization table (R1.5).

## Inconsistency 2 — the stated thermal parameters cannot reach 80 °C
Stated η ∈ [0.030, 0.0775] K/kW and κ ∈ [0.041, 0.076] give steady-state resistance
R = η/κ ≈ 0.9–1.9 K/kW. With peak rack power 8.6 kW and ambient 22 °C, the maximum reachable
steady-state temperature is 22 + 1.9×8.6 ≈ **38 °C** — far below the 80 °C hotspot threshold.
To reach the paper's 85–87 °C the effective resistance must be ≈ 6–9 K/kW (≈ 5× the stated value).
The simulator therefore uses a **calibrated** R = 6/7.5/9 K/kW per region (keeping the paper's
time constants τ = 110/90/75 min); this is documented in `sim.py` (`R_THERMAL`).
**Fix:** report thermal parameters consistent with the claimed temperatures (η ≈ 0.3–0.6 K/kW at
the stated κ), or clarify the temperature/state definition. As stated, η is ~5× too small.

## Inconsistency 3 — over-provisioning makes the benchmark ill-posed
Because only ~1 host is needed, the dominant energy driver becomes how many hosts each policy
*wakes*. Carbon/thermal-aware policies that spread load across regions/slots then *fragment* host
usage and can **increase** energy and carbon — e.g. at `--load 1`, CarbonOnly emits more CO₂e
(581) than EDF (387); at `--load 60`, SustainSched shows the highest carbon. This is an artifact of
the over-provisioned setup, not of the methods; it disappears once the cluster is meaningfully
utilized (all hosts active, so region/slot choice changes intensity without changing host count).
**Fix:** same as #1 — a properly loaded cluster. The schedulers in `sim.py` also still need
calibration of their objective weights once the load regime is fixed.

## What this means for the revision
The reported Table 2 numbers (especially the thermal column and the 48.8 % hotspot-reduction
headline) are **not reproducible from the configuration as described**. They were most likely
produced by a differently-parameterized run (heavier load and/or corrected thermal scaling) that
the manuscript does not specify. This is exactly what Reviewer 2's "controller checks itself"
(R2.3) and Reviewer 1's utilization request (R1.5) are circling.

**Recommended path (pick one):**
1. **Provide the real trace/cluster/thermal parameters** used for the published numbers (they live
   in the authors' primary code). I will plug them into this harness and regenerate everything
   consistently — Table 2, the CICM/HUNTER rows, V1–V3, and the utilization table.
2. **Adopt a corrected, documented configuration** (right-sized load ~15–25×, η ≈ 0.4 K/kW, explicit
   standby policy). I will calibrate the scheduler weights, run the full 7-method × 5-seed × 30-day
   matrix + V1–V3, and report the resulting numbers — which will differ from the current draft but
   will be fully reproducible from released code.

Either way, I did **not** inject simulator numbers into the manuscript, because under the stated
config they are degenerate (all-zero hotspots) and under any corrected config they would supersede
the draft's headline claims — a decision the authors should make deliberately.

## Files
- `sim.py` — simulator + 7 schedulers + V1–V3 plants (runs; schedulers need weight calibration to
  the chosen load regime).
- `run_all.py` — primary matrix runner → `results/table2_<tag>.json`.
- `experiment-specs.md` — full specs for CICM, HUNTER, V1, V2, V3.
- `results/` — probe outputs from the runs cited above.
