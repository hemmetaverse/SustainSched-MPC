# Experiment specifications — Array revision (ARRAY-D-26-01210)

Implementable specs for the new experiments required by the reviewers:

- **Baselines** (R1.1, R2.4): `B5 = CICM` (Radovanovic et al. 2021) and `B6 = HUNTER` (Tuli et al. 2021).
- **Validation** (R2.3, R1.2): `V1` calibration residuals, `V2` higher-fidelity plant, `V3` runtime-distribution mismatch.

Everything below reuses the **exact** configuration already in the manuscript so the results drop straight into the marked placeholders. Where a symbol is used it matches the paper's notation (§3–§5).

---

## 0. Fixed configuration (do not change — must match all other methods)

| Item | Value (from manuscript) |
|---|---|
| Regions | R1 US-West (PUE 1.10), R2 EU-Central (1.20), R3 AS-East (1.30) |
| Hosts | 8 rack-nodes/region, H=24; 2,560 vCPU & 8.6 kW peak per node |
| Interval / horizon | Δ = 5 min; H_p = 12 slots (SustainSched only) |
| DVFS P-states | {1.2, 1.8, 2.4, 3.0, 3.6} GHz; φ(f)=(f/f_max)³ |
| Power | P_idle∈[3.44,4.48] kW, α∈[2.60,3.92] kW, β∈[0.48,0.88] kW; E=P·Δ |
| Thermal RC | T_{t+1}=T_t+η_h P_t−κ_h(T_t−T^amb); η∈[0.030,0.0775], κ∈[0.041,0.076]; cap T_max=82°C, hotspot 80°C, throttle 85°C |
| Carbon (MEF) | R1 412(180–680), R2 240(90–430), R3 610(480–780) gCO₂e/kWh; 15-min, interp to 5-min |
| Migration | quota M_max=5/interval; latency ℓ 1–3 slots |
| Workload | 18,240 jobs/day (~63/slot); 70% batch (s1: ε1=2%, dl 4–8h, δ=6, runtime LN mean 18m CV 0.15), 30% LC (s2: ε2=0.5%, dl 15–30m, δ=2, runtime LN mean 4m CV 0.06); u_cpu∈[2,16], u_mem∈[4,32] |
| Runs | 30 days = 8,640 intervals × **5 seeds {42,137,271,500,999}** |
| Metrics (7) | daily energy (kWh), daily CO₂e (kg), peak temp (°C), hotspot dur (min/day, any node >80°C @1-min sampling), SLA miss % (s2), p95 queue delay (s, s2), overhead (s/decision) |

**Fairness rule:** B5/B6 see the *same* trace, seeds, carbon signals, calibrated power/thermal params, capacity, and migration quota as EDF and SustainSched-MPC, and are scored through the **identical plant + measurement pipeline**. The only thing that differs is the scheduling policy.

### Assumed simulator interface (adapt names to your codebase)

```python
# Per control step t the harness gives a scheduler:
state = {
  "t": int,                       # slot index
  "hosts": {h: Host(K_cpu, K_mem, util, freq, standby, T, region)},
  "pending": [Job(id, a, d, tau_bar, cv, u_cpu, u_mem, sla_class, delta, region_pref)],
  "running": [...],               # already-dispatched jobs with remaining time
  "I_hat":  {r: [Î_{r,t..t+H}]},  # carbon forecast per region (gCO2e/kWh)
  "T_amb":  {h: [T^amb_{h,t..t+H}]},
}
# A scheduler returns per-step decisions:
decision = {
  "assign":  {job_id: (region, host)},   # placement of (a subset of) pending jobs
  "defer":   [job_id, ...],              # jobs intentionally held to a later slot
  "freq":    {host: f},                  # DVFS P-state per host (else nominal)
  "standby": {host: 0/1},                # 1 = active
  "migrate": [(job_id, r_from, r_to)],   # ≤ M_max total
}
# The PLANT then advances power/thermal/runtime and logs per-interval telemetry.
```

If your existing `Carbon-Only`/`Power-Only` MPC classes already subclass a common scheduler, implement B5/B6 as two more subclasses with the same I/O.

---

## 1. Baseline B5 — CICM (Carbon-Intelligent Compute Management)

> Radovanovic et al., "Carbon-Aware Computing for Datacenters," IEEE TPS 2021 (`ref-radovanovic21`).
> Faithful reimplementation of the **policy**: day-ahead carbon-aware **temporal shifting** of flexible
> load under **Virtual Capacity Curves (VCCs)** with risk-aware sizing. **No** DVFS energy
> optimization, **no** thermal model, **no** per-job chance constraint. This is the carbon-aware SOTA.

### 1.1 Scope decisions (state these in the paper)
- **Temporal only**, per region (Google's CICM shapes load *within* a cluster over time). Inflexible
  (latency-critical, s2) jobs run on arrival in their region; flexible (batch, s1) jobs are deferred in
  time within their region up to δ_j. (Do **not** give it geo-migration — that would exceed the
  documented method; SustainSched-MPC's migration is part of *its* contribution.)
- Frequency fixed at **nominal 2.4 GHz**; idle hosts may gate to standby (consolidation) but no DVFS
  scaling. (CICM does not do DVFS — this isolates its carbon-shifting effect.)

### 1.2 Day-ahead VCC construction (run once per simulated day, per region)
For region r with day slots S (288 five-min slots/day):

```
Inputs:  Î[r,s]            # day-ahead carbon forecast (gCO2e/kWh) for each slot s
         D_flex[r,s]       # forecast FLEXIBLE cpu-demand arriving in slot s (vCPU)
         D_infl[r,s]       # forecast INFLEXIBLE (s2) demand per slot (vCPU)
         Kcap[r]           # total schedulable vCPU in region (8 nodes * 2560)
         rho_risk = 0.9    # fill fraction (<1) -> risk-aware slack that preserves throughput

W = sum_s D_flex[r,s]                          # total flexible work for the day (vCPU-slots)
head[s] = max(0, rho_risk*Kcap[r] - D_infl[r,s])   # room for flexible load each slot
# Water-fill the day's flexible work into the LOWEST-carbon slots first:
VCC[r,s] = 0 for all s
for s in argsort(Î[r, :]):          # ascending carbon
    take = min(head[s], W_remaining)
    VCC[r,s] = take                  # per-slot flexible capacity cap
    W_remaining -= take
    if W_remaining <= 0: break
```
`VCC[r,s]` is the per-slot ceiling on flexible vCPU the real-time loop may run. The `rho_risk<1`
margin is the "risk-aware sizing" that prevents under-provisioning under forecast error (preserves
daily throughput). *(Faithful alternative: replace the greedy water-fill with an LP minimizing
Σ_s Î[r,s]·x[s] s.t. Σ x = W, x[s] ≤ head[s]; the greedy is its closed-form optimum for a single
resource and is what to ship unless a reviewer asks for the LP.)*

### 1.3 Real-time dispatch (every interval t)
```
for job j in pending(region r), sorted by deadline d_j ascending:
    if j.sla_class == s2:                       # inflexible -> run now
        place_least_loaded(r, j); continue
    # flexible (s1): find the lowest-carbon slot in its window with VCC headroom
    window = [t .. min(t+delta_j, d_j - ceil(tau_bar_j))]
    cand = [s in window if used_flex[r,s] + u_cpu_j <= VCC[r,s]]
    if cand:
        s* = argmin_{s in cand} Î[r,s]
        if s* == t: place_least_loaded(r, j); used_flex[r,s*] += u_cpu_j
        else:       defer(j)                    # hold; re-evaluated next interval
    else:
        # no VCC room anywhere in window -> deadline pressure: run ASAP to protect throughput
        place_least_loaded(r, j); used_flex[r,t] += u_cpu_j
gate_idle_hosts_to_standby(r); set_freq(all active hosts, 2.4 GHz)
```
Placement = first-fit/least-loaded on capacity (no thermal awareness — that's the point).

### 1.4 Expected behaviour (sanity, before you trust the run)
- CO₂e: **close to or slightly above Carbon-Only**; clearly below EDF.
- Energy: **near EDF / Carbon-Only** (no DVFS optimization) → notably above SustainSched-MPC.
- Hotspot/peak temp: **high** (no thermal model), similar regime to Carbon-Only.
- SLA (s2): better than Carbon-Only (LC runs on arrival) but **no formal guarantee**; expect higher
  than SustainSched-MPC under demand spikes because there is no chance-constraint reserve.
- Overhead: low (greedy + one daily LP/water-fill).

If results contradict these, debug before reporting.

---

## 2. Baseline B6 — HUNTER

> Tuli et al., "HUNTER: AI-based holistic resource management for sustainable cloud computing," JSS 2021
> (`ref-tuli21`). Faithful reimplementation of the **multi-objective score + search**; we use our own
> analytic power/thermal/runtime models as the surrogate in place of the original Gated-Graph-CNN. Key
> differences vs SustainSched-MPC to preserve: **no formal probabilistic SLA**, **no receding-horizon
> lookahead** (myopic, single-step), heuristic search instead of exact MILP.

### 2.1 Objective (per candidate placement P at interval t)
Normalize each term to [0,1] using the cluster ranges, then:
```
score(P) = w_E * Ê(P) + w_S * SLÂ(P) + w_T * T̂(P)
   Ê(P)   = predicted facility energy this interval / E_max        (power model + PUE)
   T̂(P)   = max_h predicted T_{h,t+1}(P) / 85°C                    (one-step RC)
   SLÂ(P) = fraction of pending jobs whose predicted completion > d_j  (soft penalty)
```
Weights: set `w_E, w_S, w_T` by the **same tuning protocol used for γ₀** (grid-search on the held-out
7-day trace to minimize a 50/50 energy–SLA validation loss); report the chosen triple. A reasonable
start mirroring the paper's emphasis is `(w_E, w_S, w_T) = (0.4, 0.4, 0.2)`. *(Document that HUNTER has
no carbon term — matching the original, which is energy/SLA/thermal-centric; this is exactly why a
holistic-but-carbon-agnostic SOTA is a meaningful comparator.)*

### 2.2 Search (myopic, per interval — NO H_p lookahead)
Simulated annealing over the assignment of pending jobs to (region, host, frequency), evaluated with
the one-step surrogate above:
```
P = greedy_init(pending)                 # least-loaded placement
T_sa, best = 1.0, P
for k in range(N_iter=200):              # cap N_iter so overhead ~ comparable to the MPC methods
    P' = random_move(P)                  # reassign one job / toggle a host freq / migrate (<=M_max)
    dE = score(P') - score(P)
    if dE < 0 or rand() < exp(-dE / T_sa): P = P'
    if score(P) < score(best): best = P
    T_sa *= 0.97
apply(best)
```
Migration capped at M_max; standby/DVFS allowed as actuators (driven by the score, not a thermal cap).

### 2.3 Expected behaviour
- Strong **all-round** baseline: good energy and temperature (it optimizes both), unlike the
  single-objective variants. **This is the one to beat.**
- CO₂e: **worse than carbon-aware methods** (no carbon term) — likely between Power-Only and EDF.
- SLA (s2): better than Carbon-Only but **no probabilistic guarantee**; under forecast error/ spikes
  expect more tail misses than SustainSched-MPC (no reserve, no lookahead).
- The paper's claim to defend: SustainSched-MPC **matches/beats HUNTER on energy+thermal while adding**
  the formal SLA guarantee, carbon optimization, and bounded-latency receding-horizon control.

### 2.4 Honesty note
Report every metric for HUNTER, including any on which it ties or beats SustainSched-MPC (e.g., it may
win on raw overhead or even peak temp). Say so explicitly in §9.2 — a clean loss on one metric with
wins elsewhere is far more credible than total domination.

---

## 3. Filling the manuscript (baselines)

| Output | Goes to |
|---|---|
| B5, B6 × 7 metrics (mean over 5 seeds) | **Table 2** (`tab:results`) — replace the blue `$\ast$` in the CICM/HUNTER rows |
| inter-seed std (<2% check) | text near Table 2 / stats |
| head-to-head deltas + win/tie/loss | **§9.2** "SustainSched-MPC vs. published state-of-the-art" (replace the bracketed author note) |
| per-region load split (optional) | ties into `tab:utilization` |

---

## 4. Validation experiments (V1–V3) — break the self-consistency loop

These exist specifically to answer R2.3 ("the controller checking itself"). Controller is **unchanged**
throughout (1-node RC, 5-min, Gaussian margins); only the **plant** or the **measurement** changes.

### V1 — Calibration residuals vs measured telemetry  *(bounds the bare RC model, no controller)*
**Goal:** how well does the calibrated RC equation reproduce *measured* `coretemp`?
```
1. Split the real per-server thermal logs: calibration window (the 48 h already used) vs a
   DISJOINT hold-out window (e.g., a different 24 h, or last 12 h not used in the fit).
2. On the hold-out, drive the RC model with the MEASURED power P_{h,t} and measured T^amb:
       T̂_{h,t+1} = T_{h,t} + η_h P_{h,t} − κ_h (T_{h,t} − T^amb_{h,t})    # 1-step (teacher-forced)
       also roll out H_p=12 steps from a single start (free-running) for the multi-step error.
3. Residual e = T̂ − T_measured. Report, aggregated over hosts (mean ± std across the 24):
       RMSE_1step, MAE_1step, p95|e|_1step,  and  RMSE_12step, p95|e|_12step   (all °C)
```
**Fill:** the V1 sentence in `sec:validation` (one line of numbers; a 2-row mini-table is optional).
**Expected/interpret:** 1-step RMSE small (≈0.3–1.5 °C if RC is adequate); 12-step error grows. State
the number honestly; if p95 multi-step error approaches the 3 °C guard band, say the band is sized for it.

### V2 — Higher-fidelity reference plant (plant ≠ controller)  *(the key anti-circularity run)*
**Goal:** re-run the whole study with a *more faithful* thermal plant the controller does not model.
Two upgrades over the controller's 1-node 5-min Euler step:

```
(a) Finer integration: within each 5-min control interval, integrate the thermal ODE in
    n_sub = 5 substeps of 1 min (or 30 substeps of 10 s) using the committed power/freq,
    instead of one Δ=5min forward-Euler step. (Reduces Euler discretization error.)

(b) Spatial coupling: per region, arrange the 8 nodes on an adjacency (ring or 1-D line) and add
    rack-to-rack conduction:
      T_h^{+}=T_h + η_h P_h·dt' − κ_h(T_h−T^amb)·dt' − Σ_{h'∈N(h)} g·(T_h−T_{h'})·dt'
    Calibrate g so that coordinated heavy load on adjacent racks adds ~1–2 °C vs the single-node
    prediction (matches the 0.5–2 °C figure cited in §4.2 from ref-banerjee11). Suggested start:
    g ≈ 0.10–0.20 × mean(κ_h); tune g on a 1-day probe so peak neighbor coupling ≈ 1.5 °C.
```
- Closed loop: at each step the controller observes the plant's *realized* T (with its mismatch) and
  re-decides. Run all **5 seeds × 30 days**.
- **Measure:** realized peak temp, hotspot duration (min/day), thermal-cap **violation rate**
  (realized T>82 °C, and the safety-critical >85 °C), reactive-guardrail activation rate; also energy/
  CO₂e/SLA (these barely move — power/carbon don't depend on thermal fidelity — which is itself a useful
  point to make).
- **Fill:** `tab:validation` row **"HF thermal plant (V2)"** + the V2 bracketed text.
- **Interpret honestly:** expect hotspot duration and peak to rise modestly vs Primary (62 min/day,
  0.6%). The defensible story: gains persist, degradation is bounded, the 82→85 °C guard band + 81 °C
  reactive guardrail absorb the residual. If >85 °C ever occurs, report it and discuss (e.g., tighten
  the optimizer cap to 81 °C).

### V3 — Runtime-distribution mismatch  *(stresses the Gaussian chance constraint)*
**Goal:** controller assumes Gaussian runtime (uses Φ⁻¹(1−ε) margins); make the plant draw realized
runtimes from a heavier tail with the **same mean** τ̄_j.
```
Plant runtime draws (mean preserved = τ̄_j):
  V3a heavy-tail : log-normal with larger σ_ln (e.g., CV 0.5 for batch, 0.3 for LC) — same mean
  V3b bimodal    : 95% ~ N(τ̄_j, small),  5% ~ at 3–5× τ̄_j  (rescale so E=τ̄_j)
Controller margin unchanged: Δσ_j = τ̄_j · Φ⁻¹(1−ε_s) · σ_τ.
Run 5 seeds × 30 days; measure realized SLA miss (s1 and s2) vs budgets (2%, 0.5%) and vs 0.49% nominal.

Then the MITIGATION (one-line margin swap, controller side):
  Cantelli (distribution-free): replace Φ⁻¹(1−ε_s)  ->  sqrt((1−ε_s)/ε_s)
  re-run; report whether realized SLA returns under budget, and the carbon cost of the larger margin.
```
- **Fill:** `tab:validation` row **"Heavy-tail runtime (V3)"** + the V3 bracketed text (report both the
  unmitigated Gaussian-margin result and the Cantelli-restored result).
- **Interpret:** expect Gaussian-margin SLA to **exceed budget** under heavy tails (this is the honest
  admission the reviewer wants); the Cantelli/DRO margin should restore it at a small CO₂e cost —
  exactly the robustness–sustainability tradeoff already foreshadowed in §7.2.

---

## 5. Run matrix & repro

```
methods   = [EDF, PowerOnly, ThermalCap, CarbonOnly, CICM, HUNTER, SustainSchedMPC]   # 7
seeds     = [42, 137, 271, 500, 999]
primary   : methods × seeds                         # fills Table 2 (CICM/HUNTER rows)
V1        : offline analysis on held-out telemetry  # no scheduler loop
V2        : {SustainSchedMPC} × seeds on HF plant   # fills tab:validation V2 row
V3        : {SustainSchedMPC} × seeds × {Gaussian, Cantelli} × {V3a,V3b}  # fills V3 row
```
- Keep the released repo's CLI uniform, e.g. `python run.py --method CICM --seed 42 --plant nominal`
  and `--plant hf --tsub 60s --coupling 0.15`, `--runtime-dist lognormal_cv0.5`, `--margin cantelli`.
- Log per-interval telemetry for every run so all 7 metrics are recomputable by the §8.4 procedure;
  commit logs + a `make figures` that regenerates Table 2 / `tab:validation` / `tab:utilization`.
- Also emit the **cluster-utilization** numbers (R1.5 / `tab:utilization`) from the same logs:
  mean/peak/IQR of (Σ_j running u_cpu_j)/Kcap per region and cluster-wide.

## 6. Reporting discipline (so the new results survive re-review)
- Report **all** metrics for B5/B6 and **all** mismatch rows, including losses/degradations.
- State the **weights/params you chose** (CICM ρ_risk; HUNTER w_E,w_S,w_T,N_iter; V2 g, n_sub; V3 dist).
- Keep inter-seed std and note it (<2% claim) — or correct the claim if a new method is noisier.
- Update §9.2 / Conclusion deltas to whatever the data say; don't leave "32.1%/12.9%"-style numbers
  that pre-date the new baselines if the framing changes.
