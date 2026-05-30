#!/usr/bin/env python3
"""Turn results/table2_final.json + results/validation.json into manuscript-ready numbers.
Run after the matrix + validation finish."""
import json
R=json.load(open("results/table2_final.json"))["results"]
ORDER=["EDF","PowerOnly","ThermalCap","CarbonOnly","CICM","HUNTER","SustainSchedMPC"]
LBL={"EDF":"Deadline-First (EDF)","PowerOnly":"Power-Only","ThermalCap":"Thermal-Cap",
     "CarbonOnly":"Carbon-Only","CICM":"CICM~\\cite{ref-radovanovic21}",
     "HUNTER":"HUNTER~\\cite{ref-tuli21}","SustainSchedMPC":"\\textbf{SustainSched-MPC}"}

def f(x,d=0): return f"{x:.{d}f}"
print("="*70,"\nTABLE 2 (energy kWh/d, CO2e kg/d, peakT C, hotspot min/d, SLA%, p95 s, ovh s)\n"+"="*70)
for m in ORDER:
    r=R[m]
    print(f"{LBL[m]:34s} & {f(r['energy_kwh_day'])} & {f(r['co2e_kg_day'])} & "
          f"{f(r['peak_temp'],1)} & {f(r['hotspot_min_day'])} & {f(r['sla_miss_pct'],2)} & "
          f"{f(r['p95_queue_s'])} & {f(r['overhead_s'],1)} \\\\")

edf,ss=R["EDF"],R["SustainSchedMPC"]
def d(a,b): return 100*(1-b/a) if a else 0
print("\n-- SustainSched-MPC vs EDF (deltas) --")
print(f"energy {d(edf['energy_kwh_day'],ss['energy_kwh_day']):+.1f}%  "
      f"CO2e {d(edf['co2e_kg_day'],ss['co2e_kg_day']):+.1f}%  "
      f"hotspot {d(edf['hotspot_min_day'],ss['hotspot_min_day']):+.1f}%  "
      f"peakT {edf['peak_temp']-ss['peak_temp']:+.1f}C  SLA {ss['sla_miss_pct']-edf['sla_miss_pct']:+.2f}pp")
# best per metric
print("\n-- best (lowest) per metric --")
for k,nm in [("energy_kwh_day","energy"),("co2e_kg_day","CO2e"),("peak_temp","peakT"),
             ("hotspot_min_day","hotspot"),("sla_miss_pct","SLA")]:
    b=min(ORDER,key=lambda m:R[m][k]); print(f"  {nm:8s}: {b} ({R[b][k]:.2f})")

print("\n"+"="*70,"\nUTILIZATION (R1.5) from SustainSched-MPC run, mean/peak %\n"+"="*70)
r=R["SustainSchedMPC"]
for ri,nm in [(0,"US-West"),(1,"EU-Central"),(2,"AS-East")]:
    print(f"  {nm:11s} mean={r[f'r{ri}_mean_util']:.1f}  peak={r[f'r{ri}_peak_util']:.1f}")
print(f"  Cluster     mean={r['mean_util_pct']:.1f}  peak={r['peak_util_pct']:.1f}")

try:
    V=json.load(open("results/validation.json"))["results"]
    print("\n"+"="*70,"\nVALIDATION V2/V3\n"+"="*70)
    for tag in ["nominal","hf_plant"]:
        v=V[tag]; print(f"  V2 {tag:9s} peakT={v['peak_temp']:.1f} hotspot={v['hotspot_min_day']:.0f} thv={v['thermal_viol_pct']:.2f} energy={v['energy_kwh_day']:.0f} co2={v['co2e_kg_day']:.0f}")
    for tag in ["heavy_gauss","heavy_cantelli","bimodal_gauss","bimodal_cantelli"]:
        v=V[tag]; print(f"  V3 {tag:17s} sla2={v['sla_miss_pct']:.2f} sla1={v['sla_miss_batch_pct']:.2f}")
except FileNotFoundError:
    print("\n(validation.json not ready yet)")
