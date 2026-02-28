from dataclasses import dataclass, field
from typing import List, Dict, Optional
import numpy as np

# System constants
INTERVAL_DURATION = 300  # seconds (5 minutes)
P_STATES = [1.2, 1.8, 2.4, 3.0, 3.6]  # GHz
F_MAX = 3.6
T_MAX = 82.0
T_HOT = 80.0
T_AMB_DEFAULT = 22.0

class JobClass:
    # 1: Batch / Analytics
    # 2: Latency-critical services
    def __init__(self, class_id: int, epsilon_s: float, max_deferral: int):
        self.class_id = class_id
        self.epsilon_s = epsilon_s
        self.max_deferral = max_deferral  # in slots

CLASS_BATCH = JobClass(1, 0.02, 6)
CLASS_LATENCY = JobClass(2, 0.005, 2)


@dataclass
class Job:
    id: int
    a_j: int            # release time (slot index)
    d_j: int            # deadline (slot index)
    tau_bar: float      # estimated mean runtime (slots)
    sigma_tau: float    # relative standard deviation (CV) of prediction
    u_cpu: float
    u_mem: float
    u_io: float
    job_class: JobClass
    
    # Internal state tracking
    t_start: Optional[int] = None
    actual_runtime: Optional[float] = None
    assigned_host_id: Optional[str] = None
    assigned_region: Optional[str] = None

    def get_risk_adjusted_deadline(self, sigma_estimator: float, alpha: float = 1.0) -> float:
        """
        Eq. (29) from paper: d_safe = d_j - tau_bar * (1 + Phi^{-1}(1 - eps * alpha) * sigma_tau)
        Returns the risk-adjusted deadline slot.
        """
        import scipy.stats as stats
        epsilon_s_adj = self.job_class.epsilon_s * alpha
        quantile = stats.norm.ppf(1 - epsilon_s_adj)
        # Note: paper uses sigma_estimator (the adaptively tracked runtime CV) instead of true sigma_tau
        risk_margin = quantile * self.tau_bar * sigma_estimator
        return self.d_j - self.tau_bar - risk_margin


@dataclass
class Host:
    id: str
    region_id: str
    
    # Hardware capacity (40 servers per rack node)
    K_cpu: float = 2560.0  # 64 vCPU * 40
    K_mem: float = 5120.0  # 128 GB * 40
    K_io: float = 400.0    # generic 10Gbps * 40
    
    # Power parameters (rack node level)
    P_idle: float = 4.0    # 4.0 kW
    P_stby: float = 1.2    # 1.2 kW
    alpha: float = 3.2     # 3.2 kW
    beta: float = 0.6      # 0.6 kW
    
    # Thermal parameters
    eta: float = 0.05      # Thermal gain (K/kW)
    kappa: float = 0.05    # Cooling coefficient
    
    # Dynamic states
    t_current: float = T_AMB_DEFAULT
    f_current: float = F_MAX
    s_active: int = 1      # 1 if active, 0 if standby
    
    # Assigned jobs running on this host
    active_jobs: List[Job] = field(default_factory=list)


@dataclass
class Region:
    id: str
    pue: float
    hosts: List[Host] = field(default_factory=list)
    
    def total_capacity(self) -> float:
        return sum(h.K_cpu for h in self.hosts if h.s_active == 1)

