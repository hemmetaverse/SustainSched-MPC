#!/usr/bin/env python3
"""Run the primary 7-method x seeds matrix; write results/table2_<tag>.json and print a table.
Usage: python3 run_all.py --days 30 --load 1.0 --seeds 42,137,271,500,999 --tag stated
"""
import argparse, json, statistics, sys, os
import sim
os.makedirs("results", exist_ok=True)

METHODS = ["EDF","PowerOnly","ThermalCap","CarbonOnly","CICM","HUNTER","SustainSchedMPC"]

def mean_runs(method, seeds, days, load):
    sim.LOAD_MULT = load
    runs=[sim.run_one(method, s, days) for s in seeds]
    keys=["energy_kwh_day","co2e_kg_day","peak_temp","hotspot_min_day","sla_miss_pct",
          "sla_miss_batch_pct","p95_queue_s","overhead_s","thermal_viol_pct","jobs",
          "mean_util_pct","peak_util_pct","r0_mean_util","r0_peak_util",
          "r1_mean_util","r1_peak_util","r2_mean_util","r2_peak_util"]
    out={k: statistics.mean(r[k] for r in runs) for k in keys}
    out["energy_std_pct"]=100*statistics.pstdev([r["energy_kwh_day"] for r in runs])/max(1,out["energy_kwh_day"]) if len(seeds)>1 else 0.0
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--load", type=float, default=1.0)
    ap.add_argument("--seeds", default="42,137,271,500,999")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--methods", default=",".join(METHODS), help="comma list of methods to run this call")
    ap.add_argument("--merge", action="store_true", help="merge into existing results/table2_<tag>.json")
    a=ap.parse_args()
    seeds=[int(x) for x in a.seeds.split(",")]
    res={}
    if a.merge:
        try: res=json.load(open(f"results/table2_{a.tag}.json"))["results"]
        except FileNotFoundError: res={}
    for m in [x for x in a.methods.split(",") if x]:
        res[m]=mean_runs(m, seeds, a.days, a.load)
        r=res[m]
        print(f"{m:16s} E={r['energy_kwh_day']:7.0f} CO2={r['co2e_kg_day']:6.0f} "
              f"peakT={r['peak_temp']:5.1f} hot={r['hotspot_min_day']:6.1f} "
              f"sla2={r['sla_miss_pct']:5.2f} sla1={r['sla_miss_batch_pct']:5.2f} "
              f"p95={r['p95_queue_s']:6.0f} thv={r['thermal_viol_pct']:.2f}", flush=True)
    # deltas vs EDF
    if "EDF" in res and "SustainSchedMPC" in res:
        edf=res["EDF"]; ss=res["SustainSchedMPC"]
        print("\n-- SustainSched-MPC vs EDF --")
        print(f"energy {100*(1-ss['energy_kwh_day']/edf['energy_kwh_day']):+.1f}%  "
              f"CO2e {100*(1-ss['co2e_kg_day']/edf['co2e_kg_day']):+.1f}%  "
              f"hotspot {100*(1-ss['hotspot_min_day']/max(1e-9,edf['hotspot_min_day'])):+.1f}%")
    meta=dict(days=a.days, load=a.load, seeds=seeds, tag=a.tag)
    json.dump({"meta":meta,"results":res}, open(f"results/table2_{a.tag}.json","w"), indent=2)
    print(f"\nwrote results/table2_{a.tag}.json")

if __name__=="__main__":
    main()
