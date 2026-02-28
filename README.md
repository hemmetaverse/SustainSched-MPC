# SustainSched-MPC Simulator

**Risk-Constrained Power-, Carbon-, and Thermal-Aware Scheduling for Sustainable Distributed Computing**

SustainSched-MPC is a receding-horizon, chance-constrained scheduling framework that jointly optimizes energy consumption, carbon emissions, thermal stress, and Service Level Agreement (SLA) deadline reliability for geo-distributed computing clusters.

## 🌟 Overview

Data centers require complex orchestration to balance sustainability parameters (energy and carbon) against operational safety (thermal limits) and user guarantees (SLA deadlines). Optimizing these elements in isolation creates compensating degradations (e.g., carbon-optimizers create thermal hotspots; thermal-cappers forfeit carbon savings). 

**SustainSched-MPC** solves this by unifying all these constraints into a single Mixed Integer Linear Programming (MILP) model. Solved online every 5 minutes over a 60-minute prediction horizon via Lagrangian region decomposition, it guarantees adherence to thermal and SLA limits probabilistically under stochastic forecast uncertainty.

### Core Framework Components
- **Power Model**: Piece-wise linear DVFS power scaling combining static and dynamic power $\rightarrow P_h = s_h \cdot P_{idle} + \alpha u_h + \beta \phi(f)$.
- **Thermal Model**: Proactive, first-order RC (Lumped Capacitance) discrete-time thermal dynamics $T_{h,t+1} = T_{h,t} + \eta_h P_{h,t} - \kappa_h(T_{h,t} - T_{amb})$.
- **Carbon Accounting**: Region-dependent PUE and real-time Marginal Emission Factors (MEF) to quantify operational CO2e accurately via geographic traces.
- **SLA Chance Constraints**: SLA deadlines are mapped to risk margins calibrated to runtime prediction uncertainties $\rightarrow d^{safe}_j(\epsilon_s)$.
- **MPC Solver**: A rolling receding-horizon `PuLP` scheduler operating within 5-minute intervals.

## 🚀 Installation

The simulator utilizes standard Python scientific and optimization libraries. It requires Python 3.9+.

```bash
# 1. Clone the repository
git clone https://github.com/hemmetaverse/SustainSched-MPC.git
cd SustainSched-MPC

# 2. Setup a virtual environment (Recommended)
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

## 📊 Data Ingestion (Carbon Intensity)

SustainSched-MPC uses real-world grid carbon intensity traces to intelligently shift jobs spatially and temporally. A built-in scraping pipeline integrates with the [Electricity Maps API](https://www.electricitymaps.com/) to fetch historical MEF data for three distinct regions (US-West high solar, EU-Central mixed renewables, AS-East fossil-dominated). 

You must generate an API Token from the Electricity Maps Free-Tier portal. Run the ingestion pipeline to compile the dataset into 5-minute CSV intervals:

```bash
python -m src.data_ingestion --token "YOUR_API_TOKEN" --out "data/carbon"
```

## 🖥️ Running the Simulator

To replicate the evaluation scaling and run the closed-loop simulator over `N` days:

```bash
python -m src.simulator --days 1 --seed 42
```

### What happens during simulation?
1. **Infrastructure Initialization**: A 3-region geo-distributed cluster is spun up. 24 rack nodes map to 960 servers handling 61,440 vCPUs.
2. **Trace Generation**: Synthesizes a hybrid batch and latency-critical workload trace (0.55M jobs over a 30-day profile distribution).
3. **Receding-Horizon Loop**: Progresses step-by-step through 5-minute intervals. State tracking reads active power bounds, forecasts carbon footprints and ambient temperatures, configures the Risk Margins, executes the MILP scheduler algorithm via PuLP, commits the first actions, and records KPI performance.
4. **Metrics Evaluated**: Outputs the combined Energy (kWh), Operational Carbon (kgCO2e), Peak Temperatures ($^\circ$C), Thermal Hotspot bounds, and exact SLA adherence figures at the end of the simulation.

## 🧪 Testing

The framework includes an integration test suite validating the constraints, thermal conversions, and bounding margins.

```bash
python -m pytest tests/
```

## 🏗️ Repository Structure
- `src/models.py`: Defines the foundational physical data objects (`Region`, `Host`, `Job`) and configuration constants.
- `src/physics.py`: Contains the RC Thermal logic and DVFS Power formulations.
- `src/scheduler.py`: The core SustainSched-MPC logic implementing the MILP algorithm and mathematical relaxations (Big-M, Epigraph conversions).
- `src/simulator.py`: Connects models with datasets into a fully autonomous event loop simulating time progression.
- `src/trace_generator.py`: Generates representative job workloads and environmental data forecasts.
- `src/data_ingestion.py`: Helper script bridging API access to historic carbon signals.
- `tests/`: Collection of automated test scripts executing unit and end-to-end integration validations.

## 📜 Citation
This codebase was developed as the core software representation of the methodology mapped out in the paper:
*Risk-Constrained Power-, Carbon-, and Thermal-Aware Scheduling for Sustainable Distributed Computing.*
