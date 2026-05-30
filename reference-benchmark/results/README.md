# Results directory

Machine-readable outputs of the reference benchmark.

## Reported in the paper
- `table2_final.json` — the 7-method × 5-seed × 30-day comparison (manuscript Table 2)
- `table2_m_<METHOD>.json` — per-method runs that merge into Table 2
  (`EDF`, `PowerOnly`, `ThermalCap`, `CarbonOnly`, `CICM`, `HUNTER`, `SustainSchedMPC`;
  `CarbonOnly_a` is the 3-seed subset, see paper note)
- `validation.json` — V2 (higher-fidelity thermal plant) and V3 (heavy-tailed / bimodal
  runtimes, Gaussian vs Cantelli margin) robustness results
- `ablation.json` — component-removal ablation (manuscript ablation table)
- `alpha_sweep.json` — risk-budget multiplier α sweep (manuscript Fig. risk-tradeoff)
- `FINAL_NUMBERS.txt` — human-readable consolidation produced by `merge_and_table.py`

## Load-calibration probes (exploratory, not cited in the paper)
The `table2_p*.json` and `table2_probe*.json` files are short single-seed runs at
different offered-load multipliers (`--load 1, 2, 2.5, 3, 3.5, 40, 60`, plus early
probes) used to select the corrected, well-posed operating point (~56% cluster
utilisation, load 2.5×) documented in `../FINDINGS.md`. They are included for full
transparency of the calibration process but are superseded by `table2_final.json`.

Regenerate everything with:
```bash
python3 ../run_all.py --days 30 --load 2.5 --seeds 42,137,271,500,999 --tag final
python3 ../run_validation.py --days 30 --load 2.5 --seeds 42,137,271,500,999
python3 ../merge_and_table.py
```
