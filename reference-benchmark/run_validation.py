#!/usr/bin/env python3
"""V2/V3 validation (R2.3) on SustainSched-MPC at the corrected config.
V1 (RC residuals vs measured coretemp) requires the authors' real telemetry and is not runnable in
this synthetic reference; it is specified in experiment-specs.md.
Usage: python3 run_validation.py --days 30 --load 2.5 --seeds 42,137,271,500,999
"""
import argparse, json, statistics, os
import sim
os.makedirs("results", exist_ok=True)
KEYS=["energy_kwh_day","co2e_kg_day","peak_temp","hotspot_min_day","sla_miss_pct",
      "sla_miss_batch_pct","thermal_viol_pct","mean_util_pct"]

def avg(seeds,days,load,**kw):
    sim.LOAD_MULT=load
    runs=[sim.run_one("SustainSchedMPC",s,days,**kw) for s in seeds]
    return {k:statistics.mean(r[k] for r in runs) for k in KEYS}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--days",type=int,default=30); ap.add_argument("--load",type=float,default=2.5)
    ap.add_argument("--seeds",default="42,137,271,500,999")
    a=ap.parse_args(); seeds=[int(x) for x in a.seeds.split(",")]
    res={}
    print("V2: higher-fidelity (finer-step + spatially coupled) thermal plant vs nominal")
    res["nominal"]=avg(seeds,a.days,a.load,plant="nominal")
    res["hf_plant"]=avg(seeds,a.days,a.load,plant="hf")
    for tag in ("nominal","hf_plant"):
        r=res[tag]; print(f"  {tag:10s} peakT={r['peak_temp']:.1f} hotspot={r['hotspot_min_day']:.0f} thv={r['thermal_viol_pct']:.2f} energy={r['energy_kwh_day']:.0f} co2={r['co2e_kg_day']:.0f}")
    print("V3: heavy-tailed / bimodal runtimes; Gaussian vs distribution-free Cantelli margin")
    res["heavy_gauss"]=avg(seeds,a.days,a.load,runtime_dist="heavy",margin="gauss")
    res["heavy_cantelli"]=avg(seeds,a.days,a.load,runtime_dist="heavy",margin="cantelli")
    res["bimodal_gauss"]=avg(seeds,a.days,a.load,runtime_dist="bimodal",margin="gauss")
    res["bimodal_cantelli"]=avg(seeds,a.days,a.load,runtime_dist="bimodal",margin="cantelli")
    for tag in ("heavy_gauss","heavy_cantelli","bimodal_gauss","bimodal_cantelli"):
        r=res[tag]; print(f"  {tag:18s} sla2={r['sla_miss_pct']:.2f} sla1={r['sla_miss_batch_pct']:.2f} hotspot={r['hotspot_min_day']:.0f}")
    json.dump({"meta":dict(days=a.days,load=a.load,seeds=seeds),"results":res},
              open("results/validation.json","w"),indent=2)
    print("wrote results/validation.json")

if __name__=="__main__": main()
