# Reference Benchmark (reviewer-response artifact)

This directory contains a **self-contained, dependency-free reference benchmark** added to support
the *Array* revision of SustainSched-MPC. It complements — and does **not** replace — the primary
MILP implementation in [`../src/`](../src) (PuLP/CBC).

Where the `src/` code is the production MILP scheduler, this benchmark is a fast **behavioural
reference**: each of seven schedulers is realised as a marginal-cost / greedy-decomposition policy
encoding that method's objective, so the full comparison matrix and the validation experiments run in
minutes with **only the Python standard library** (no NumPy, no solver). It exists to make the
reviewer-requested experiments fully reproducible by anyone, on any machine, with `python3` alone.

## Why this was added (reviewer requests)

- **R1.1 / R2.4 — published-baseline comparison:** adds faithful reimplementations of **CICM**
  (Radovanovic et al., 2021) and **HUNTER** (Tuli et al., 2021) alongside EDF and the three
  single-objective MPC ablations.
- **R2.3 — independent validation (controller ≠ plant):** adds a higher-fidelity, spatially coupled
  thermal plant (**V2**) and runtime-distribution mismatch (**V3**) to test the headline numbers
  against a plant the controller does not model.
- **R1.5 — utilization reporting:** emits per-region and cluster CPU-time utilization.

## Requirements

Python 3.8+ standard library only. Verified on CPython 3.14.

## Quick start

```bash
# single run -> JSON KPIs on stdout
python3 sim.py --method SustainSchedMPC --seed 42 --days 30 --load 2.5

# full 7-method x 5-seed x 30-day comparison matrix
python3 run_all.py --days 30 --load 2.5 --seeds 42,137,271,500,999 --tag final

# validation: V2 (higher-fidelity thermal plant) + V3 (runtime-distribution mismatch)
python3 run_validation.py --days 30 --load 2.5 --seeds 42,137,271,500,999

# merge per-method runs -> manuscript-ready tables
python3 merge_and_table.py
```

## Schedulers

| Key | Description |
|---|---|
| `EDF` | Earliest-deadline-first, load-spreading reference |
| `PowerOnly` | Energy-minimising consolidation (no carbon/thermal awareness) |
| `ThermalCap` | Reactive thermal-cap throttling |
| `CarbonOnly` | Carbon-greedy region/temporal shifting, no risk margin |
| `CICM` | Carbon-Intelligent Compute Management — Radovanovic et al., 2021 (reimpl.) |
| `HUNTER` | Holistic energy/SLA/thermal scheduler — Tuli et al., 2021 (reimpl.) |
| `SustainSchedMPC` | Proposed joint power–carbon–thermal policy with chance-constrained SLA |

`CICM` and `HUNTER` reproduce the published **policies and objectives** (the originals target
different platforms and are not directly executable on this trace).

## Configuration note (important)

Results here use a **corrected, well-posed configuration** (cluster mean utilisation ≈ 56 %, peak
≈ 100 %) on the paper's 24 rack-nodes / 61,440 vCPU and per-region thermal time constants. The
rationale — and the configuration inconsistencies in the original setup that motivated the correction
— are documented in [`FINDINGS.md`](FINDINGS.md). The interpretation of the resulting numbers (a
Pareto-compromise rather than universal dominance) is in [`RESULTS.md`](RESULTS.md). Full baseline
and validation specifications are in [`experiment-specs.md`](experiment-specs.md).

## Layout

```
sim.py                 # simulator + 7 schedulers + V2/V3 validation plants (core)
run_all.py             # comparison-matrix runner   -> results/table2_<tag>.json
run_validation.py      # V2/V3 validation runner     -> results/validation.json
merge_and_table.py     # merge per-method runs + emit manuscript tables
make_tables.py         # alternate table formatter
experiment-specs.md    # CICM/HUNTER + V1-V3 specifications
FINDINGS.md            # configuration findings that motivated the corrected setup
RESULTS.md             # corrected-config results + honest interpretation
results/               # machine-readable outputs (table2_final.json, validation.json, FINAL_NUMBERS.txt, per-method JSONs)
```

## Carbon-intensity data

The licensed Electricity Maps extract is **not redistributed**; `sim.py` ships a calibrated synthetic
per-region carbon profile. Reconstruction details are in `experiment-specs.md`.
