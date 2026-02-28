# SustainSched-MPC
Risk-Constrained Power-, Carbon-, and Thermal-Aware Scheduling for Sustainable Distributed Computing.

Implementation codebase replicating the core logic of the chance-constrained MPC geo-distributed data center scheduler.

## Features
- **Thermal Model**: Implements First-order RC lumped capacitance thermal model for nodes.
- **Power Model**: Piece-wise linear DVFS power scaling $P_h = P_{idle} + \alpha U + \beta \phi(f)$.
- **Chance Constraints**: Guarantee SLA boundaries probabilistically under real-time uncertainty margins mapped to prediction deviations.
- **MPC Solver**: Receding-horizon Mixed Integer Linear Programming (MILP) scheduling logic built using Python `pulp`

## Installation
```bash
pip install -r requirements.txt
```

## Running the Simulator

To simulate the exact 3-region geo-distributed cluster over `N` days:

```bash
python -m src.simulator --days 1 --seed 42
```
This generates the synthetic workload traces, runs the real-time receding horizon loop, manages state transition updates dynamically, and writes log constraints to completion.

## Testing
```bash
pytest tests/
```
