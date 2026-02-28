import numpy as np
from typing import List, Dict
from .models import Job, CLASS_BATCH, CLASS_LATENCY, INTERVAL_DURATION

def generate_daily_trace(seed: int, num_jobs: int = 18240) -> List[Job]:
    """
    Generates a synthetic workload trace for 1 day based on Section 8.2 of the paper.
    70% Batch jobs, 30% Latency-critical.
    U_cpu ~ U[2, 16], U_mem ~ U[4, 32]
    """
    np.random.seed(seed)
    jobs = []
    
    # 24-hour arrival profile (normalized)
    # 0, 3, 6, 9, 12, 15, 18, 21 as indices approx
    profile = [0.28, 0.20, 0.25, 0.75, 0.95, 0.88, 0.74, 0.48, 0.30]
    
    # Interpolate to 288 slots (5 min intervals in 24 hrs)
    slots = np.linspace(0, 8, 288)
    lambda_t = np.interp(slots, np.arange(9), profile)
    lambda_t /= np.sum(lambda_t) # normalize to sum to 1
    
    # Assign arrivals
    arrivals_per_slot = np.random.multinomial(num_jobs, lambda_t)
    
    job_id = 0
    for slot_idx, count in enumerate(arrivals_per_slot):
        for _ in range(count):
            is_batch = np.random.rand() < 0.70
            j_class = CLASS_BATCH if is_batch else CLASS_LATENCY
            
            # log-normal dist
            if is_batch:
                mean_rt = 18 * 60 / INTERVAL_DURATION # slots
                cv = 0.15
            else:
                mean_rt = 4 * 60 / INTERVAL_DURATION
                cv = 0.06
                
            sigma2 = np.log(1 + cv**2)
            mu = np.log(mean_rt) - sigma2 / 2
            true_runtime = np.random.lognormal(mu, np.sqrt(sigma2))
            
            # Bound runtime minimum to 1 slot
            true_runtime = max(1.0, true_runtime)
            
            u_cpu = np.random.uniform(2, 16)
            u_mem = np.random.uniform(4, 32)
            u_io = np.random.uniform(1, 10)
            
            d_j = slot_idx + (8 * 60) // 5 if is_batch else slot_idx + (30) // 5 # 8h or 30m deadline
            
            job = Job(
                id=job_id,
                a_j=slot_idx,
                d_j=int(d_j),
                tau_bar=mean_rt,
                sigma_tau=cv,
                u_cpu=u_cpu,
                u_mem=u_mem,
                u_io=u_io,
                job_class=j_class,
                actual_runtime=true_runtime
            )
            jobs.append(job)
            job_id += 1
            
    return jobs

def generate_carbon_forecasts(slots: int = 288) -> Dict[str, np.ndarray]:
    """
    Simulated 24hr marginal emission factors (MEF)
    """
    x = np.linspace(0, 24, slots)
    
    # US-West: Solar peak drops carbon during midday (180 - 680)
    us_west = 680 - 500 * np.exp(-0.5 * ((x - 14) / 3)**2)
    
    # EU-Central: (90 - 430)
    eu_central = 240 + 150 * np.sin(x/24 * 2 * np.pi)
    
    # AS-East: High baseline (480 - 780)
    as_east = 610 + 50 * np.sin(x/24 * 2 * np.pi + 2)
    
    return {
        "US-West": us_west,
        "EU-Central": eu_central,
        "AS-East": as_east
    }

def generate_temp_forecasts(slots: int = 288, baseline: float = 22.0) -> Dict[str, np.ndarray]:
    forecasts = {}
    for r in ["US-West", "EU-Central", "AS-East"]:
        # Simple ambient temp variation
        forecasts[r] = np.full(slots, baseline) + np.random.normal(0, 0.5, slots)
    return forecasts
