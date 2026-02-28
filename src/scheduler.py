import pulp
import numpy as np
from typing import List, Dict, Any, Tuple
from .models import Job, Host, Region, INTERVAL_DURATION, P_STATES, F_MAX, T_HOT, T_MAX

class SustainSchedMPC:
    def __init__(self, regions: List[Region], horizon: int = 12):
        self.regions = regions
        self.horizon = horizon  # H_p = 12 slots (60 mins)
        self.lambdas = {
            'E': 0.15,
            'C': 0.55,
            'T': 0.20,
            'D': 0.10
        }
        self.M_max = 5  # Max cross-region migrations per int.

    def schedule(self, current_slot: int, pending_jobs: List[Job],
                 carbon_forecasts: Dict[str, List[float]], 
                 temp_forecasts: Dict[str, List[float]],
                 sigma_estimator: float, alpha: float = 1.0) -> Tuple[Dict, str]:
        """
        Solves the relaxed MILP for the current step t_0 across the H_p horizon.
        For simplicity in this localized simulation, we formulate a single global MILP 
        with PuLP rather than Lagrangian Decomposition since python/pulp scale limits differ 
        from native C++ GLPK.
        """
        prob = pulp.LpProblem("SustainSched_MPC", pulp.LpMinimize)
        
        # We will bound the number of jobs scheduled in a single 5 min window
        # to ensure it solves quickly via local python solver.
        jobs_to_schedule = pending_jobs[:150]  # Cap at max queue depth for 5min interval

        # Variables
        # X[j_id][r_id][h_id][t] : Binary assigning Job to Host in Region starting at time Slot t
        X = pulp.LpVariable.dicts("X", 
                                 ((j.id, r.id, h.id, t) 
                                  for j in jobs_to_schedule 
                                  for r in self.regions 
                                  for h in r.hosts 
                                  for t in range(current_slot, current_slot + self.horizon)),
                                 cat='Binary')
        
        # F[h_id][t] : Continuous DVFS frequency envelope relaxed in [1.2, 3.6]
        F = pulp.LpVariable.dicts("F",
                                 ((h.id, t) for r in self.regions for h in r.hosts for t in range(current_slot, current_slot + self.horizon)),
                                 lowBound=P_STATES[0], upBound=F_MAX)
                                 
        # S[h_id][t] : Binary Standby (1=active, 0=standby)
        S = pulp.LpVariable.dicts("S",
                                 ((h.id, t) for r in self.regions for h in r.hosts for t in range(current_slot, current_slot + self.horizon)),
                                 cat='Binary')
                                 
        # Z[h_id][t] : Continuous Slack for Thermal Epigraph
        Z = pulp.LpVariable.dicts("Z",
                                 ((h.id, t) for r in self.regions for h in r.hosts for t in range(current_slot, current_slot + self.horizon)),
                                 lowBound=0.0)

        # Build Objectives
        obj_energy = 0
        obj_carbon = 0
        obj_thermal = 0
        obj_delay = 0

        # We need continuous representation of Temperature to define constraints
        # T_var[h_id][t]
        T_var = pulp.LpVariable.dicts("T",
                                     ((h.id, t) for r in self.regions for h in r.hosts for t in range(current_slot, current_slot + self.horizon + 1)),
                                     lowBound=20.0, upBound=T_MAX)

        # Helper: Mapped jobs executing at slot t
        # u_ht(j, h_id, t) -> 1 if job j is active on h at t
        def get_utilization(h_id, t):
            u_term = 0
            # For each job, sum up their required resource if they started 
            # within t-tau_bar <= start_time <= t
            for j in jobs_to_schedule:
                # Assuming deterministic tau_bar for capacity bounds
                tau = int(j.tau_bar)
                for start_t in range(max(current_slot, t - tau + 1), t + 1):
                    for r in self.regions:
                        if (j.id, r.id, h_id, start_t) in X:
                            u_term += X[j.id, r.id, h_id, start_t] * j.u_cpu
            return u_term
            
        # Core Constraints and Obj terms
        for r in self.regions:
            for h in r.hosts:
                T_var[h.id, current_slot] = h.t_current # Init condition

                for step in range(self.horizon):
                    t = current_slot + step
                    
                    u_ht = get_utilization(h.id, t)
                    
                    # Capacity constraint: u_ht <= K_cpu * (F_ht / F_max)
                    prob += u_ht <= h.K_cpu * S[h.id, t]
                    
                    # We linearize the power: P_ht = S * P_idle + alpha * u_ht + beta * (F/F_max)
                    # For simplicity in optimization, we'll approximate the bilinear `s_ht * P_idle` & active power directly
                    P_ht_expr = S[h.id, t] * h.P_idle + h.alpha * u_ht + h.beta * (F[h.id, t] / F_MAX)
                    
                    amb_t = temp_forecasts[r.id][step]
                    
                    # Thermal transition: T_next = T_cur + eta*P - kappa*(T_cur - T_amb)
                    prob += T_var[h.id, t+1] == T_var[h.id, t] + h.eta * P_ht_expr - h.kappa * (T_var[h.id, t] - amb_t)
                    
                    # Thermal cap constraint
                    prob += T_var[h.id, t+1] <= T_MAX
                    
                    # Epigraph
                    prob += Z[h.id, t] >= T_var[h.id, t] - T_HOT
                    
                    # Accumulate terms
                    step_energy = r.pue * P_ht_expr * (INTERVAL_DURATION / 3600.0)
                    obj_energy += step_energy
                    obj_carbon += step_energy * (carbon_forecasts[r.id][step] / 1000.0)
                    obj_thermal += Z[h.id, t] * (INTERVAL_DURATION / 60.0)

        # Single assignment and delay for jobs
        M_count = {t: 0 for t in range(current_slot, current_slot + self.horizon)}
        
        for j in jobs_to_schedule:
            d_safe = j.get_risk_adjusted_deadline(sigma_estimator, alpha)
            
            # Constraint: Must schedule pending job once
            assign_sum = []
            for r in self.regions:
                # Migration constraint (simplified)
                mig_latency = 0 if j.assigned_region is None or j.assigned_region == r.id else 1
                
                for h in r.hosts:
                    for t in range(current_slot, current_slot + self.horizon):
                        valid_start = t >= j.a_j + mig_latency
                        valid_end = (t + int(j.tau_bar) - 1) <= d_safe
                        
                        if valid_start and valid_end:
                            assign_sum.append(X[j.id, r.id, h.id, t])
                            
                            # Delay Obj
                            if j.job_class.class_id == 1:
                                obj_delay += X[j.id, r.id, h.id, t] * (t - j.a_j) * INTERVAL_DURATION
                                
                            # Migration sum
                            if mig_latency > 0:
                                M_count[t] += X[j.id, r.id, h.id, t]
                        else:
                            # Not valid domain
                            prob += X[j.id, r.id, h.id, t] == 0
                            
            if len(assign_sum) > 0:
                if d_safe < current_slot + self.horizon:
                    # Must schedule if deadline is within horizon
                    prob += pulp.lpSum(assign_sum) == 1
                else:
                    # Can defer to future horizons
                    prob += pulp.lpSum(assign_sum) <= 1
            else:
                # No valid domain in this horizon. It will be deferred or inevitably miss SLA.
                pass
                
        # Migration quota bounds
        for t in range(current_slot, current_slot + self.horizon):
            prob += M_count[t] <= self.M_max
            
        prob += self.lambdas['E']*obj_energy + self.lambdas['C']*obj_carbon + self.lambdas['T']*obj_thermal + self.lambdas['D']*obj_delay
        
        # We allow fallback to CBC as it is default
        solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=60)
        status = prob.solve(solver)
        
        if pulp.LpStatus[status] != 'Optimal':
            return None, "Infeasible"
            
        # Extract decisions
        decisions = {'starts': [], 'f_states': {}}
        for j in jobs_to_schedule:
            for r in self.regions:
                for h in r.hosts:
                    for t in range(current_slot, current_slot + self.horizon):
                        if X[j.id, r.id, h.id, t].value() and X[j.id, r.id, h.id, t].value() > 0.5:
                            decisions['starts'].append({
                                'job_id': j.id,
                                'host': h,
                                'start_slot': t
                            })
                            
        for r in self.regions:
            for h in r.hosts:
                # round the continuous F up to the nearest valid P_STATE
                f_val = F[h.id, current_slot].value()
                f_opt = min(P_STATES, key=lambda x: abs(x - f_val))
                s_val = int(round(S[h.id, current_slot].value()))
                decisions['f_states'][h.id] = {'f': f_opt, 's': s_val}

        return decisions, "Optimal"
