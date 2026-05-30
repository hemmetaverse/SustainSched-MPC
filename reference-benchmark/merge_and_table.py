#!/usr/bin/env python3
"""Merge per-method tag files into table2_final.json, then emit manuscript-ready numbers.
Inputs:  results/m_<METHOD>.json    (one per method, written by run_all.py --tag m_<M>)
         results/validation.json
Outputs: results/table2_final.json
         stdout: Table 2 rows, EDF-vs-SS deltas, utilization, V2/V3, win/tie/loss
"""
import json, os, statistics
ORDER=["EDF","PowerOnly","ThermalCap","CarbonOnly","CICM","HUNTER","SustainSchedMPC"]
LBL={"EDF":"Deadline-First (EDF)","PowerOnly":"Power-Only","ThermalCap":"Thermal-Cap",
     "CarbonOnly":"Carbon-Only","CICM":"CICM~\\cite{ref-radovanovic21}",
     "HUNTER":"HUNTER~\\cite{ref-tuli21}","SustainSchedMPC":"\\textbf{SustainSched-MPC}"}

def load_single(m):
    fp=f"results/table2_m_{m}.json"
    return json.load(open(fp))["results"][m] if os.path.exists(fp) else None

def load_stitched(m, parts):
    """Combine multiple sub-runs of the same method, weighted by seed count."""
    data=[]
    for tag,nseeds in parts:
        fp=f"results/table2_m_{m}_{tag}.json"
        if not os.path.exists(fp): return None
        data.append((nseeds, json.load(open(fp))["results"][m]))
    keys=set().union(*[set(d[1]) for d in data])
    tot=sum(n for n,_ in data); out={}
    for k in keys:
        vals=[(n,d.get(k,0)) for n,d in data]
        if isinstance(vals[0][1],(int,float)): out[k]=sum(n*v for n,v in vals)/tot
        else: out[k]=vals[0][1]
    return out

res={}; missing=[]
for m in ORDER:
    r = load_single(m)
    if r is None and m == "CarbonOnly":
        # Try stitched (5-seed); fall back to chunk A only (3 seeds) if chunk B was killed
        r = load_stitched(m, [("a",3),("b",2)])
        if r is None and os.path.exists("results/table2_m_CarbonOnly_a.json"):
            r = json.load(open("results/table2_m_CarbonOnly_a.json"))["results"]["CarbonOnly"]
            r["_n_seeds"]=3
    if r is None: missing.append(m)
    else: res[m]=r
if missing:
    print(f"MISSING: {missing} — re-run those before final processing.")
meta={"days":30,"load":2.5,"seeds":[42,137,271,500,999],"config":"corrected, well-posed"}
json.dump({"meta":meta,"results":res}, open("results/table2_final.json","w"), indent=2)

def f(x,d=0): return f"{x:.{d}f}"
print("="*78,"\nTABLE 2  (LaTeX rows, energy kWh/d | CO2e kg/d | peakT C | hotspot min/d | SLA% | p95 s | ovh s)\n"+"="*78)
for m in ORDER:
    if m not in res: print(f"% {m}: missing"); continue
    r=res[m]
    print(f"{LBL[m]:36s} & {f(r['energy_kwh_day'])} & {f(r['co2e_kg_day'])} & "
          f"{f(r['peak_temp'],1)} & {f(r['hotspot_min_day'])} & {f(r['sla_miss_pct'],2)} & "
          f"{f(r['p95_queue_s'])} & {f(r['overhead_s'],1)} \\\\")
if "EDF" in res and "SustainSchedMPC" in res:
    edf,ss=res["EDF"],res["SustainSchedMPC"]
    d=lambda a,b: 100*(1-b/a) if a else 0
    print("\n-- SustainSched-MPC vs EDF --")
    print(f"  energy {d(edf['energy_kwh_day'],ss['energy_kwh_day']):+.1f}%  "
          f"CO2e {d(edf['co2e_kg_day'],ss['co2e_kg_day']):+.1f}%  "
          f"hotspot {d(edf['hotspot_min_day'],ss['hotspot_min_day']):+.1f}%  "
          f"peakT {edf['peak_temp']-ss['peak_temp']:+.1f}C  "
          f"SLA {ss['sla_miss_pct']-edf['sla_miss_pct']:+.2f}pp")
print("\n-- best (lowest) per metric, honest win/tie/loss --")
for k,nm in [("energy_kwh_day","energy"),("co2e_kg_day","CO2e"),("peak_temp","peakT"),
             ("hotspot_min_day","hotspot"),("sla_miss_pct","SLA(s2)")]:
    if not res: continue
    b=min(res, key=lambda m:res[m][k])
    print(f"  {nm:8s} winner: {b:18s}  ({res[b][k]:.2f})")

print("\n"+"="*78,"\nUTILIZATION (R1.5), per-region mean/peak %, taken from SustainSched-MPC run\n"+"="*78)
if "SustainSchedMPC" in res:
    r=res["SustainSchedMPC"]
    for ri,nm in [(0,"US-West"),(1,"EU-Central"),(2,"AS-East")]:
        print(f"  {nm:11s} mean={r[f'r{ri}_mean_util']:.1f}%  peak={r[f'r{ri}_peak_util']:.1f}%")
    print(f"  Cluster     mean={r['mean_util_pct']:.1f}%  peak={r['peak_util_pct']:.1f}%")

try:
    V=json.load(open("results/validation.json"))["results"]
    print("\n"+"="*78,"\nVALIDATION (R2.3) — SustainSched-MPC under controller!=plant\n"+"="*78)
    print("V2 (higher-fidelity, spatially-coupled thermal plant):")
    for tag in ["nominal","hf_plant"]:
        v=V[tag]
        print(f"  {tag:9s} peakT={v['peak_temp']:.1f}  hotspot={v['hotspot_min_day']:.0f}  "
              f"thv={v['thermal_viol_pct']:.2f}  energy={v['energy_kwh_day']:.0f}  CO2={v['co2e_kg_day']:.0f}")
    print("V3 (runtime distribution mismatch, Gaussian-margin vs Cantelli):")
    for tag in ["heavy_gauss","heavy_cantelli","bimodal_gauss","bimodal_cantelli"]:
        v=V[tag]
        print(f"  {tag:17s} sla2={v['sla_miss_pct']:.2f}%  sla1={v['sla_miss_batch_pct']:.2f}%  hotspot={v['hotspot_min_day']:.0f}")
except FileNotFoundError:
    print("\n(no validation.json)")

print("\nwrote results/table2_final.json")
