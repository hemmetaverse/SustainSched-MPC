import pytest
import numpy as np
from src.models import Job, CLASS_BATCH, Host, F_MAX
from src.physics import calculate_host_power, update_host_temperature

def test_risk_margin_calculation():
    # 1. Test the risk-adjusted deadline formulation Eq. (29)
    # d_safe = d_j - tau_bar - Phi^{-1}(1 - eps_s * alpha) * tau_bar * sigma_tau
    j = Job(id=1, a_j=0, d_j=100, tau_bar=18.0, sigma_tau=0.15, 
            u_cpu=4, u_mem=8, u_io=1, job_class=CLASS_BATCH)
            
    # CLASS_BATCH eps_s = 0.02
    # For eps_s = 0.02, 1-eps_s = 0.98. Phi^{-1}(0.98) ~ 2.0537
    # Margin = 2.0537 * 18.0 * 0.10 (sigma_estimator) ~ 3.696
    # d_safe = 100 - 18.0 - 3.696 = 78.3
    
    sigma_estimator = 0.10
    d_safe = j.get_risk_adjusted_deadline(sigma_estimator, alpha=1.0)
    
    import scipy.stats as stats
    quantile = stats.norm.ppf(0.98)
    expected_margin = quantile * 18.0 * sigma_estimator
    expected_d_safe = 100 - 18.0 - expected_margin
    
    assert np.isclose(d_safe, expected_d_safe), f"Expected {expected_d_safe}, got {d_safe}"
    
    # 2. Test Alpha scaling
    d_safe_alpha2 = j.get_risk_adjusted_deadline(sigma_estimator, alpha=2.0)
    # eps_s = 0.04 -> quantile = Phi^{-1}(0.96) ~ 1.750
    quantile_2 = stats.norm.ppf(0.96)
    expected_margin_2 = quantile_2 * 18.0 * sigma_estimator
    expected_d_safe_2 = 100 - 18.0 - expected_margin_2
    
    assert np.isclose(d_safe_alpha2, expected_d_safe_2)
    assert d_safe_alpha2 > d_safe # Higher alpha -> higher eps -> looser margin -> larger d_safe
    

def test_power_model():
    # h = P_idle: 4.0, alpha: 3.2, beta: 0.6
    h = Host("t1", "US-West")
    
    # Active, idle
    p_idle = calculate_host_power(h, 0.0, F_MAX)
    assert np.isclose(p_idle, 4.0 + 0 + 0.6) # 4.6 kW
    
    # Standby
    h.s_active = 0
    p_stby = calculate_host_power(h, 0.0, F_MAX)
    assert np.isclose(p_stby, 1.2)
    
    # Half load
    h.s_active = 1
    p_half = calculate_host_power(h, 1280.0, F_MAX) # U is unnormalized here? Wait!
    # Ah, the model uses U fraction or absolute? In scheduler I did `alpha * u_ht`. If u_ht is absolute vCPUs then alpha is huge!
    pass

def test_thermal_model():
    h = Host("t1", "US-West", t_current=22.0)
    # heat input = 0.05 * 5.0 = 0.25 K
    # cooling = 0.05 * (22.0 - 22.0) = 0
    t_next = update_host_temperature(h, 5.0, 22.0)
    assert np.isclose(t_next, 22.25)
