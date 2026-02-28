import os
import argparse
from typing import List, Dict
import numpy as np

from .models import Host, Region, Job, P_STATES, F_MAX
from .physics import calculate_host_power, update_host_temperature
from .scheduler import SustainSchedMPC
from .trace_generator import generate_daily_trace, generate_carbon_forecasts, generate_temp_forecasts

def setup_infrastructure() -> List[Region]:
    regions = []
    
    # US-West: PUE 1.10, tau=110m -> kappa=5/110=0.045
    us_hosts = [Host(f"us_{i}", "US-West", eta=0.045, kappa=0.045) for i in range(8)]
    regions.append(Region("US-West", 1.10, us_hosts))
    
    # EU-Central: PUE 1.20, tau=90m -> kappa=5/90=0.055
    eu_hosts = [Host(f"eu_{i}", "EU-Central", eta=0.055, kappa=0.055) for i in range(8)]
    regions.append(Region("EU-Central", 1.20, eu_hosts))
    
    # AS-East: PUE 1.30, tau=75m -> kappa=0.066
    as_hosts = [Host(f"as_{i}", "AS-East", eta=0.066, kappa=0.066) for i in range(8)]
    regions.append(Region("AS-East", 1.30, as_hosts))
    
    return regions

def run_simulation(args):
    regions = setup_infrastructure()
    scheduler = SustainSchedMPC(regions)
    
    slots_per_day = 288
    total_slots = slots_per_day * args.days
    
    print(f"Generating Trace for {args.days} days...")
    all_jobs = []
    for d in range(args.days):
        all_jobs.extend(generate_daily_trace(seed=args.seed + d))
        
    carbon_full = generate_carbon_forecasts(slots_per_day)
    temp_full = generate_temp_forecasts(slots_per_day)
    
    # Initialize state
    sigma_estimator = 0.10
    active_jobs = []
    pending_jobs = []
    
    # Metrics
    total_energy = 0
    total_carbon = 0
    hotspot_minutes = 0
    sla_misses = 0
    completed_jobs = 0
    peak_temp = 0.0
    
    print("Starting Receding-Horizon Control Loop")
    for t in range(total_slots):
        # 1. State Ingestion
        arriving = [j for j in all_jobs if j.a_j == t]
        pending_jobs.extend(arriving)
        
        # Free completed jobs
        for j in active_jobs[:]:
            if t >= j.t_start + int(np.ceil(j.actual_runtime)):
                active_jobs.remove(j)
                completed_jobs += 1
                if t > j.d_j: # SLA miss
                    sla_misses += 1
        
        # Get current host powers and update temperatures
        for r in regions:
            for h in r.hosts:
                active_u = sum(j.u_cpu for j in active_jobs if j.assigned_host_id == h.id)
                p_ht = calculate_host_power(h, active_u, h.f_current)
                t_amb = temp_full[r.id][t % slots_per_day]
                
                # Advance temp
                h.t_current = update_host_temperature(h, p_ht, t_amb)
                if h.t_current > 80.0:
                    hotspot_minutes += 5
                peak_temp = max(peak_temp, h.t_current)
                
                # KPIs
                step_energy = r.pue * p_ht * (300 / 3600.0) # kWh
                total_energy += step_energy
                total_carbon += step_energy * (carbon_full[r.id][t % slots_per_day] / 1000.0)
                
        if t % 60 == 0:
            print(f"Slot {t}/{total_slots} - Queue Size: {len(pending_jobs)}")
                
        # 2. Forecast Ingestion
        c_forecast = {r: [carbon_full[r][(t+k)%slots_per_day] for k in range(scheduler.horizon)] for r in ["US-West", "EU-Central", "AS-East"]}
        t_forecast = {r: [temp_full[r][(t+k)%slots_per_day] for k in range(scheduler.horizon)] for r in ["US-West", "EU-Central", "AS-East"]}
        
        # 3 + 4. Optimization
        decisions, status = scheduler.schedule(
            current_slot=t,
            pending_jobs=pending_jobs,
            active_jobs=active_jobs,
            carbon_forecasts=c_forecast,
            temp_forecasts=t_forecast,
            sigma_estimator=sigma_estimator
        )
            
        # 5. Commit
        if status == "Optimal" and decisions:
            # Dispatch starting jobs for this exact slot
            for alloc in decisions['starts']:
                if alloc['start_slot'] == t:
                    j = next(job for job in pending_jobs if job.id == alloc['job_id'])
                    j.t_start = t
                    j.assigned_host_id = alloc['host'].id
                    j.assigned_region = alloc['host'].region_id
                    
                    pending_jobs.remove(j)
                    active_jobs.append(j)
                    
            # Update F and S states
            for r in regions:
                for h in r.hosts:
                    if h.id in decisions['f_states']:
                        h.f_current = decisions['f_states'][h.id]['f']
                        h.s_active = decisions['f_states'][h.id]['s']
                            
    # Final Metrics
    print("\n=== Eval Results ===")
    print(f"Total Energy (kWh): {total_energy:.2f}")
    print(f"Total Operational Carbon (kgCO2e): {total_carbon:.2f}")
    print(f"Peak Temperature (C): {peak_temp:.2f}")
    print(f"Hotspot Accumulation (min): {hotspot_minutes}")
    print(f"SLA Misses: {sla_misses}/{completed_jobs} ({(sla_misses/(completed_jobs+1))*100:.2f}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1, help="Simulation duration")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()
    
    run_simulation(args)
