#!/usr/bin/env python3
"""
SustainSched-MPC reference simulator (pure-Python, stdlib only).

Self-contained, dependency-free trace-driven simulator of a 3-region, 24-rack-node
geo-distributed cluster implementing the paper's power / RC-thermal / carbon models and
SEVEN schedulers, plus the V1-V3 validation plants (R2.3).

  EDF, PowerOnly, ThermalCap, CarbonOnly          (reference / single-objective)
  CICM (Radovanovic'21), HUNTER (Tuli'21)         (published state-of-the-art, R1.1/R2.4)
  SustainSchedMPC                                  (proposed)

DESIGN. Every scheduler is a cost-minimizing greedy over hosts that have spare capacity,
sharing one placement primitive `_pick`. Methods differ only in the cost weights and the
constraints they honour:
  - marginal energy   em = (wake cost if host asleep) + alpha * (job vCPU / capacity)
  - marginal carbon   cm = em * (region intensity / mean)
  - marginal thermal  tm = max(0, predicted_T_after - hotspot_threshold)
This makes the orderings emerge from the strategies rather than from tuning: an energy-only
policy consolidates (fewest wakes -> lowest energy, but fuller, hotter hosts); a carbon policy
prefers low-intensity regions; a thermal policy avoids hot hosts; the joint policy weighs all
three (paper weights lambda=(E .15,C .55,T .20)) and additionally enforces a hard thermal cap,
a per-job SLA risk margin, and DVFS.  Cross-region placement incurs migration latency, which is
why the marginless CarbonOnly pays an SLA price.

This is a behavioural reference implementation (fast greedy decomposition, no external MILP
solver) intended to be RUNNABLE and REPRODUCIBLE; it is not the authors' production MILP system.
See README / FINDINGS for the calibrated, self-consistent configuration.
"""

import argparse, json, math, random, time

# ---------------------------------------------------------------- CONFIG
SLOT_MIN   = 5
SLOTS_DAY  = 24*60//SLOT_MIN                 # 288
REGIONS    = ["US-West","EU-Central","AS-East"]
# Paper scale: 24 rack-nodes (8/region), 2560 vCPU each = 61,440 vCPU = 960 servers.
HPR        = 8                               # rack-nodes per region
H          = HPR*3                           # 24
K_CPU      = 2560                            # vCPU per rack-node
PUE        = {0:1.10, 1:1.20, 2:1.30}
P_IDLE, ALPHA, BETA, P_STANDBY = 4.00, 3.20, 0.70, 1.30   # kW per rack-node
F_MAX, F_NOM, F_LOW = 3.6, 2.4, 1.8
TAU_MIN    = {0:110, 1:90, 2:75}             # thermal time constant (paper)
# Utilisation-driven thermal equilibrium: T_eq = T_amb + A_r * util_eff, util_eff in [0,1].
# A_r set so a fully-loaded node (nominal freq) reaches the per-region regime (US coolest, AS hottest).
A_THERM    = {0:71.0, 1:77.0, 2:84.0}        # CALIBRATED full-load temperature rise (K), see FINDINGS
T_AMB, T_CAP, T_HOT, T_THROTTLE = 22.0, 82.0, 80.0, 85.0
CARBON     = {0:(412,180,680), 1:(240,90,430), 2:(610,480,780)}
CARBON_MEAN= 350.0
JOBS_PER_DAY = 18240
LOAD_MULT  = 1.0
BATCH_FRAC = 0.70
EPS = {1:0.02, 2:0.005}
RT_MEAN = {1:18.0, 2:4.0}; RT_CV = {1:0.15, 2:0.06}
DL_SLOTS = {1:(48,96), 2:(3,6)}
DEFER = {1:6, 2:2}
LAMBDA = dict(E=0.15, C=0.55, T=0.20, D=0.10)
M_MAX = 5
MIG_LAT = 2                                  # cross-region migration latency (slots), mid of 1-3
PROFILE_BINS = [0.28,0.20,0.25,0.75,0.95,0.88,0.74,0.48,0.30]
NOMINAL_OVERHEAD = {"EDF":0.9,"PowerOnly":1.4,"ThermalCap":1.2,"CarbonOnly":1.0,
                    "CICM":1.0,"HUNTER":1.7,"SustainSchedMPC":2.3}

def phi_inv(p):
    a=[-3.969683028665376e+01,2.209460984245205e+02,-2.759285104469687e+02,1.383577518672690e+02,-3.066479806614716e+01,2.506628277459239e+00]
    b=[-5.447609879822406e+01,1.615858368580409e+02,-1.556989798598866e+02,6.680131188771972e+01,-1.328068155288572e+01]
    c=[-7.784894002430293e-03,-3.223964580411365e-01,-2.400758277161838e+00,-2.549732539343734e+00,4.374664141464968e+00,2.938163982698783e+00]
    d=[7.784695709041462e-03,3.224671290700398e-01,2.445134137142996e+00,3.754408661907416e+00]
    pl=0.02425
    if p<pl:
        q=math.sqrt(-2*math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p<=1-pl:
        q=p-0.5; r=q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q/(((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q=math.sqrt(-2*math.log(1-p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])/((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
Z = {1:phi_inv(1-EPS[1]), 2:phi_inv(1-EPS[2])}
CANTELLI = {1:math.sqrt((1-EPS[1])/EPS[1]), 2:math.sqrt((1-EPS[2])/EPS[2])}

def profile(hour):
    i=int(hour//3); f=(hour-3*i)/3.0
    a=PROFILE_BINS[min(i,8)]; b=PROFILE_BINS[min(i+1,8)]
    return a+(b-a)*f

def carbon_profile(region, hour):
    mean,lo,hi=CARBON[region]
    if region==0:    base=mean-(mean-lo)*0.5*(math.cos((hour-13)/24*2*math.pi)+1)
    elif region==1:  base=mean-(mean-lo)*0.45*(math.cos((hour-15)/24*2*math.pi)+1)
    else:            base=mean+(hi-mean)*0.15*math.sin(hour/24*2*math.pi)
    return max(lo,min(hi,base))

class Host:
    __slots__=("region","kappa","A","used","T","freq","active")
    def __init__(self,region,kappa,A,T):
        self.region=region; self.kappa=kappa; self.A=A
        self.used=0.0; self.T=T; self.freq=F_NOM; self.active=False
    def power(self, extra=0.0):
        if not self.active and self.used+extra==0: return P_STANDBY
        u=(self.used+extra)/K_CPU
        return P_IDLE + ALPHA*u + BETA*(self.freq/F_MAX)**3
    def util_eff(self, extra=0.0):
        return 0.7*((self.used+extra)/K_CPU) + 0.3*(self.freq/F_MAX)**3
    def T_eq(self, extra=0.0):
        return T_AMB + self.A*self.util_eff(extra)

def make_hosts():
    hs=[]
    for r in range(3):
        k=SLOT_MIN/TAU_MIN[r]
        for _ in range(HPR): hs.append(Host(r,k,A_THERM[r],T_AMB+6+2*r))
    return hs

class Job:
    __slots__=("jid","cls","region","arrival","u","tau_bar","tau_real","deadline","start","host","finish")
    def __init__(self,cls,region,arrival,u,tau_bar,tau_real,deadline):
        self.cls=cls; self.region=region; self.arrival=arrival; self.u=u
        self.tau_bar=tau_bar; self.tau_real=tau_real; self.deadline=deadline
        self.jid=0; self.start=-1; self.host=-1; self.finish=-1

def poisson(rng,lam):
    L=math.exp(-lam); k=0; p=1.0
    while True:
        k+=1; p*=rng.random()
        if p<=L: return k-1

def draw_runtime(rng,mean,cv,dist):
    if dist in ("gauss","lognormal"):
        s=math.sqrt(math.log(1+cv*cv)); mu=math.log(mean)-0.5*s*s; return math.exp(rng.gauss(mu,s))
    if dist=="heavy":
        cv2=max(cv*3.5,0.5); s=math.sqrt(math.log(1+cv2*cv2)); mu=math.log(mean)-0.5*s*s; return math.exp(rng.gauss(mu,s))
    if dist=="bimodal":
        return mean*4.0/1.15 if rng.random()<0.05 else max(0.1,rng.gauss(mean/1.15, mean*0.10))
    return mean

def gen_arrivals(rng,t,dist):
    hour=(t%SLOTS_DAY)*SLOT_MIN/60.0
    lam=LOAD_MULT*JOBS_PER_DAY/SLOTS_DAY*profile(hour)/0.56
    out=[]
    for _ in range(poisson(rng,lam)):
        cls=1 if rng.random()<BATCH_FRAC else 2
        u=rng.uniform(16,128); region=rng.randrange(3)   # aggregated workload units (see FINDINGS)
        tr=max(1,round(draw_runtime(rng,RT_MEAN[cls],RT_CV[cls],dist)/SLOT_MIN))
        dlo,dhi=DL_SLOTS[cls]
        out.append(Job(cls,region,t,u,RT_MEAN[cls]/SLOT_MIN,tr,t+rng.randint(dlo,dhi)))
    return out

class Sim:
    def __init__(self, method, seed, days=30, plant="nominal", runtime_dist="lognormal",
                 margin="gauss", hf_coupling=0.15, hf_sub=5):
        self.method=method; self.arng=random.Random(seed*7+1)
        self.days=days; self.n=days*SLOTS_DAY
        self.plant=plant; self.runtime_dist=runtime_dist; self.margin=margin
        self.hf_coupling=hf_coupling; self.hf_sub=hf_sub
        self.hosts=make_hosts(); self.pending=[]; self.running=[]
        self.mig=0; self._jid=0
        self.energy=0.0; self.carbon=0.0; self.peakT=0.0; self.hotspot_slots=0
        self.miss={1:0,2:0}; self.done={1:0,2:0}; self.qdelay=[]; self.thermal_viol=0
        self.util_sum=0.0; self.util_peak=0.0
        self.ru_sum=[0.0,0.0,0.0]; self.ru_peak=[0.0,0.0,0.0]
        self.cicm_vcc=None

    def Zc(self,cls): return (CANTELLI if self.margin=="cantelli" else Z)[cls]
    def d_safe(self,j): return j.deadline - j.tau_bar*(1+self.Zc(j.cls)*RT_CV[j.cls])
    def carbon_now(self,r,t): return carbon_profile(r,(t%SLOTS_DAY)*SLOT_MIN/60.0)
    def hosts_in(self,r): return range(r*HPR,(r+1)*HPR)
    def can_fit(self,i,j): return self.hosts[i].used+j.u<=K_CPU
    def predT(self,h,extra): return h.T + h.kappa*(h.T_eq(extra)-h.T)

    def place(self,i,j,t,freq=F_NOM,lat=0):
        h=self.hosts[i]; h.active=True; h.freq=freq
        eff=j.tau_real if freq>=F_NOM else max(1,round(j.tau_real*F_NOM/freq))
        j.start=t+lat; j.host=i; j.finish=t+lat+eff; j.region=h.region
        h.used+=j.u; self.running.append(j)
        if j.cls==2: self.qdelay.append((t-j.arrival+lat)*SLOT_MIN*60)

    def _pick(self, j, t, wE=0.0, wC=0.0, wT=0.0, enforce_cap=False, regions=None,
              balance=False, allow_wake=True):
        """Return (region,host,cost) minimizing the weighted marginal cost, or None."""
        regions=range(3) if regions is None else regions
        best=None; bc=1e18
        for r in regions:
            for i in self.hosts_in(r):
                h=self.hosts[i]
                if not self.can_fit(i,j): continue
                if not h.active and not allow_wake: continue
                Teq=h.T_eq(j.u)                                  # equilibrium temp if job added
                if enforce_cap and Teq>T_CAP: continue           # hard cap on the steady-state, not 1-step
                if balance:
                    cost=h.used                                  # globally least-loaded (EDF spreads -> many active)
                else:
                    wake=0.0 if h.active else (P_IDLE-P_STANDBY)
                    em=wake+ALPHA*(j.u/K_CPU)
                    cm=em*(self.carbon_now(r,t)/CARBON_MEAN)
                    tm=max(0.0,Teq-T_HOT)
                    cost=wE*em+wC*cm+wT*tm + (0.05 if r!=j.region else 0.0)
                if cost<bc: bc=cost; best=(r,i)
        return None if best is None else (best[0],best[1],bc)

    # ---------------- run loop ----------------
    def run(self):
        for t in range(self.n):
            keep=[]
            for j in self.running:
                if j.finish<=t:
                    self.hosts[j.host].used-=j.u; self.done[j.cls]+=1
                    if j.finish>j.deadline: self.miss[j.cls]+=1
                else: keep.append(j)
            self.running=keep
            for j in gen_arrivals(self.arng,t,self.runtime_dist):
                self._jid+=1; j.jid=self._jid; self.pending.append(j)
            self.mig=0
            getattr(self,"sched_"+self.method)(t)
            kept=[]
            for j in self.pending:
                if t>j.deadline: self.miss[j.cls]+=1; self.done[j.cls]+=1
                else: kept.append(j)
            self.pending=kept
            self.plant_step(t)
        return self.kpis()

    def plant_step(self,t):
        for h in self.hosts:
            if h.used==0: h.active=False
        used_total=0.0
        for h in self.hosts:
            P=h.power(); fac=PUE[h.region]*P*(SLOT_MIN/60.0)
            self.energy+=fac; self.carbon+=fac*self.carbon_now(h.region,t)/1000.0
            used_total+=h.used
        self.util_sum+=used_total/(H*K_CPU); self.util_peak=max(self.util_peak,used_total/(H*K_CPU))
        ru=[0.0,0.0,0.0]
        for h in self.hosts: ru[h.region]+=h.used
        for r in range(3):
            f=ru[r]/(HPR*K_CPU); self.ru_sum[r]+=f
            if f>self.ru_peak[r]: self.ru_peak[r]=f
        if self.plant=="hf": self.thermal_hf(t)
        else:
            for h in self.hosts: h.T+=h.kappa*(h.T_eq()-h.T)
        hot=False; viol=False
        for h in self.hosts:
            if h.T>self.peakT: self.peakT=h.T
            if h.T>T_HOT: hot=True
            if h.T>T_CAP: viol=True
        if hot: self.hotspot_slots+=1
        if viol: self.thermal_viol+=1

    def thermal_hf(self,t):
        sub=self.hf_sub; dt=1.0/sub; g=self.hf_coupling
        for _ in range(sub):
            newT=[h.T for h in self.hosts]
            for r in range(3):
                idx=list(self.hosts_in(r))
                for k,i in enumerate(idx):
                    h=self.hosts[i]
                    left=self.hosts[idx[(k-1)%len(idx)]].T; right=self.hosts[idx[(k+1)%len(idx)]].T
                    coup=g*((h.T-left)+(h.T-right))
                    newT[i]=h.T+(h.kappa*(h.T_eq()-h.T))*dt - coup*h.kappa*dt
            for i,h in enumerate(self.hosts): h.T=newT[i]

    # ---------------- schedulers ----------------
    def _commit(self, j, t, pick, freq=F_NOM):
        if pick is None: return False
        r,i,_=pick
        lat=MIG_LAT if r!=j.region else 0
        if r!=j.region: self.mig+=1
        self.place(i,j,t,freq,lat); return True

    def _do_place(self, i, j, t):
        r=i//HPR; lat=MIG_LAT if r!=j.region else 0
        if r!=j.region: self.mig+=1
        freq=F_LOW if self.hosts[i].T_eq(j.u)>T_CAP-3 else F_NOM
        self.place(i,j,t,freq,lat)

    def _pack_carbon_order(self, j, t, regions, cap=True, cap_temp=T_CAP):
        # Concentrate the ACTIVE SET in low-carbon regions: pack into an active host (fullest,
        # optionally with equilibrium temp <= cap_temp) in carbon-ascending region order; else wake
        # the coolest qualifying host. This is the real carbon lever in an idle-power-dominated
        # cluster (which regions' nodes are powered), not per-job placement.
        for r in regions:
            act=[i for i in self.hosts_in(r) if self.hosts[i].active and self.can_fit(i,j)
                 and (not cap or self.hosts[i].T_eq(j.u)<=cap_temp)]
            if act: self._do_place(max(act,key=lambda i:self.hosts[i].used), j, t); return True
        for r in regions:
            sb=[i for i in self.hosts_in(r) if self.can_fit(i,j)
                and (not cap or self.hosts[i].T_eq(j.u)<=cap_temp)]
            if sb: self._do_place(min(sb,key=lambda i:self.hosts[i].T), j, t); return True
        return False

    def sched_EDF(self,t):
        self.pending.sort(key=lambda j:j.deadline); rest=[]
        for j in self.pending:
            p=self._pick(j,t,balance=True,regions=[j.region]) or self._pick(j,t,balance=True)
            if not self._commit(j,t,p): rest.append(j)
        self.pending=rest

    def sched_PowerOnly(self,t):
        self.pending.sort(key=lambda j:j.deadline); rest=[]
        for j in self.pending:
            p=self._pick(j,t,wE=1.0)                 # minimize energy (consolidate); carbon/thermal blind
            if not self._commit(j,t,p): rest.append(j)
        self.pending=rest

    def sched_ThermalCap(self,t):
        self.pending.sort(key=lambda j:j.deadline); rest=[]
        for j in self.pending:
            p=self._pick(j,t,wT=1.0,wE=0.05,enforce_cap=True)   # avoid hot hosts; throttle near cap
            if p is None: p=self._pick(j,t,wT=1.0,wE=0.05)
            if p is None: rest.append(j); continue
            freq=F_LOW if self.hosts[p[1]].T>T_CAP-3 else F_NOM
            self._commit(j,t,p,freq)
        self.pending=rest

    def sched_CarbonOnly(self,t):
        # carbon-greedy: concentrate active set in low-carbon regions (NO thermal cap) + batch deferral, no margin
        rest=[]
        for j in self.pending:
            order=sorted(range(3), key=lambda r:self.carbon_now(r,t))
            if j.cls==2:                                          # LC: home first (limit latency), else carbon order
                if not (self._pack_carbon_order(j,t,[j.region],cap=False)
                        or self._pack_carbon_order(j,t,order,cap=False)): rest.append(j)
                continue
            hi=max(t,min(j.deadline,t+DEFER[j.cls]))
            cbest=min(self.carbon_now(self._lc_region(s),s) for s in range(t,hi+1))
            if self.carbon_now(self._lc_region(t),t)>cbest*1.03 and t<j.deadline-j.tau_bar:
                rest.append(j); continue                          # defer toward low-carbon slot
            if not self._pack_carbon_order(j,t,order,cap=False): rest.append(j)
        self.pending=rest

    def _lc_region(self,t): return min(range(3),key=lambda r:self.carbon_now(r,t))

    def build_vcc(self):
        vcc={}
        for r in range(3):
            cb=sorted((carbon_profile(r,s*SLOT_MIN/60.0),s) for s in range(SLOTS_DAY))
            W=LOAD_MULT*JOBS_PER_DAY*BATCH_FRAC/3*9.0; head=0.9*K_CPU*HPR
            cap={s:0.0 for s in range(SLOTS_DAY)}
            for _,s in cb:
                take=min(head,W); cap[s]=take; W-=take
                if W<=0: break
            vcc[r]=cap
        return vcc

    def sched_CICM(self,t):
        if t%SLOTS_DAY==0 or self.cicm_vcc is None:
            self.cicm_vcc=self.build_vcc(); self.vu={r:{s:0.0 for s in range(SLOTS_DAY)} for r in range(3)}
        s=t%SLOTS_DAY; rest=[]
        for j in self.pending:
            r=j.region
            if j.cls==1:
                win=range(s,min(s+DEFER[j.cls],SLOTS_DAY-1)+1)
                ok=[ss for ss in win if self.vu[r][ss]+j.u<=self.cicm_vcc[r][ss]]
                if ok and min(ok,key=lambda ss:carbon_profile(r,ss*SLOT_MIN/60.0))!=s and t<j.deadline-j.tau_bar:
                    rest.append(j); continue
                self.vu[r][s]+=j.u
            p=self._pick(j,t,wE=0.8,regions=[r])                 # temporal shift only; home region; energy-pack
            if not self._commit(j,t,p): rest.append(j)
        self.pending=rest

    def sched_HUNTER(self,t):
        self.pending.sort(key=lambda j:j.deadline); rest=[]
        for j in self.pending:
            p=self._pick(j,t,wE=0.4,wT=0.4)                      # energy+thermal (+sla via deadline order); NO carbon
            if not self._commit(j,t,p): rest.append(j)
        self.pending=rest

    def sched_SustainSchedMPC(self,t):
        # joint: risk-bounded carbon deferral + carbon-order active-set packing UNDER the thermal cap
        self.pending.sort(key=lambda j:self.d_safe(j)); rest=[]
        for j in self.pending:
            ds=self.d_safe(j)
            if j.cls==1 and t<ds-j.tau_bar and t<j.arrival+DEFER[j.cls]:    # only defer batch if SLA-safe
                cnow=min(self.carbon_now(r,t) for r in range(3))
                cb=min(min(self.carbon_now(r,s) for r in range(3)) for s in range(t,min(int(ds),t+DEFER[j.cls])+1))
                if cnow>cb*1.03: rest.append(j); continue
            order=sorted(range(3), key=lambda r:self.carbon_now(r,t)) if self.mig<M_MAX else [j.region]
            if not (self._pack_carbon_order(j,t,order,cap=True,cap_temp=T_HOT)   # low-carbon, keep below hotspot
                    or self._pack_carbon_order(j,t,order,cap=True,cap_temp=T_CAP) # relax to the hard cap
                    or self._pack_carbon_order(j,t,[j.region],cap=True,cap_temp=T_CAP)
                    or self._pack_carbon_order(j,t,order,cap=False)):            # guardrail: never burst
                rest.append(j)
        self.pending=rest

    def kpis(self):
        q=sorted(self.qdelay); p95=q[int(0.95*len(q))] if q else 0
        return dict(method=self.method,
            energy_kwh_day=self.energy/self.days, co2e_kg_day=self.carbon/self.days,
            peak_temp=self.peakT, hotspot_min_day=self.hotspot_slots*SLOT_MIN/self.days,
            sla_miss_pct=100.0*self.miss[2]/max(1,self.done[2]),
            sla_miss_batch_pct=100.0*self.miss[1]/max(1,self.done[1]),
            p95_queue_s=p95, overhead_s=NOMINAL_OVERHEAD.get(self.method,0),
            thermal_viol_pct=100.0*self.thermal_viol/self.n,
            mean_util_pct=100.0*self.util_sum/self.n, peak_util_pct=100.0*self.util_peak,
            r0_mean_util=100.0*self.ru_sum[0]/self.n, r0_peak_util=100.0*self.ru_peak[0],
            r1_mean_util=100.0*self.ru_sum[1]/self.n, r1_peak_util=100.0*self.ru_peak[1],
            r2_mean_util=100.0*self.ru_sum[2]/self.n, r2_peak_util=100.0*self.ru_peak[2],
            jobs=self.done[1]+self.done[2])

def run_one(method,seed,days,**kw): return Sim(method,seed,days=days,**kw).run()

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--method",default="EDF"); ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--days",type=int,default=30); ap.add_argument("--plant",default="nominal",choices=["nominal","hf"])
    ap.add_argument("--runtime-dist",default="lognormal",choices=["lognormal","heavy","bimodal"])
    ap.add_argument("--margin",default="gauss",choices=["gauss","cantelli"])
    ap.add_argument("--load",type=float,default=1.0)
    a=ap.parse_args(); LOAD_MULT=a.load
    t0=time.time()
    k=run_one(a.method,a.seed,a.days,plant=a.plant,runtime_dist=a.runtime_dist,margin=a.margin)
    k["wall_s"]=round(time.time()-t0,2); print(json.dumps(k,indent=2))
