from .models import Host, F_MAX

def calculate_host_power(host: Host, u_ht: float, f_ht: float) -> float:
    """
    Eq. (10): P_ht = s_ht * [P_idle + alpha * u_ht + beta * phi(f_ht)] + (1-s_ht)*P_stby
    Computes power in kW.
    """
    if host.s_active == 0:
        return host.P_stby
        
    # Normalized frequency cube
    phi_f = (f_ht / F_MAX) ** 3
    power = host.P_idle + host.alpha * u_ht + host.beta * phi_f
    return power


def update_host_temperature(host: Host, P_ht: float, T_amb: float) -> float:
    """
    Eq. (12): T_{h,t+1} = T_{h,t} + eta_h * P_ht - kappa_h * (T_ht - T_amb)
    Returns discrete time RC thermal update.
    """
    heat_input = host.eta * P_ht
    cooling = host.kappa * (host.t_current - T_amb)
    
    next_temp = host.t_current + heat_input - cooling
    return next_temp


def piecewise_linear_phi(f: float) -> float:
    """
    Piecewise linear upper envelope for phi(f) = (f/F_MAX)^3 over P_STATES.
    """
    from .models import P_STATES
    import numpy as np
    
    # Calculate exact phi for breakpoints
    phi_exact = [(state / F_MAX)**3 for state in P_STATES]
    
    # Find segment
    if f <= P_STATES[0]: return phi_exact[0]
    if f >= P_STATES[-1]: return phi_exact[-1]
    
    for i in range(len(P_STATES)-1):
        f_k = P_STATES[i]
        f_k1 = P_STATES[i+1]
        if f_k <= f <= f_k1:
            slope = (phi_exact[i+1] - phi_exact[i]) / (f_k1 - f_k)
            return phi_exact[i] + slope * (f - f_k)
            
    return (f / F_MAX)**3 # fallback
