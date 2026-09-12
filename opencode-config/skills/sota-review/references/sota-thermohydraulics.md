# SOTA — Thermohydraulics, Two-Phase Transient

Reference for Step 2 and Step 4.
Domain: two-phase transient flow in nuclear systems, multi-1D network codes,
thermal-hydraulic models for reactor safety analysis (LOCA, pump trip, etc.).
Relevant codes: CATHARE, RELAP5, TRACE (NRC), SAM (ANL), ATHLET.

---

## Table of contents
- [Two-phase flow model hierarchy](#models)
- [Spatial discretisation for 1D networks](#spatial)
- [Time integration for stiff two-phase systems](#time)
- [Pressure-velocity coupling](#pressure)
- [Constitutive relations — closure laws](#closure)
- [Multi-1D network coupling](#network)
- [Common SOTA gaps](#gaps)

---

## Two-phase flow model hierarchy <a name="models"></a>

| Model | Equations | SOTA? | Use case |
|---|---|---|---|
| HEM (Homogeneous Equilibrium) | 3 | Baseline | Critical flow, fast transients |
| Drift-flux (DFM) | 3 + slip relation | SOTA baseline | System codes, bubbly/slug flow |
| Two-fluid (TFM) 6-equation | 6 (2×mass, 2×momentum, 2×energy) | SOTA | Full two-phase; CATHARE, RELAP5 |
| Two-fluid 7-equation | 6 + interfacial pressure | Research SOTA | Better hyperbolicity |

**SOTA for reactor safety codes**: 6-equation two-fluid model with
interfacial exchange terms. HEM is not appropriate when phases have
significantly different velocities (stratified flow, counter-current flow).

**SOTA gap**: HEM used for flow regimes with slip > 0.3 without documented
justification — slip velocity is physically important and HEM incorrectly
assumes mechanical equilibrium between phases.

### Thermodynamic closure

| Assumption | SOTA? | Notes |
|---|---|---|
| Thermal equilibrium (saturation) | Baseline | Both phases at T_sat |
| Thermal non-equilibrium | SOTA | Subcooled boiling, flashing; separate liquid/vapor T |
| Metastable state | SOTA for flashing | Spinodal region; required for rapid depressurisation |

**SOTA gap**: thermal equilibrium assumption during rapid depressurisation
(LOCA blowdown) — misses flashing dynamics and critical flow phenomena.

---

## Spatial discretisation for 1D networks <a name="spatial"></a>

### Staggered vs collocated mesh

| Mesh | SOTA? | Notes |
|---|---|---|
| Staggered (MAC/Harlow-Welch) | SOTA | Scalar (P, α, ρ) at cell centre; velocity at face |
| Collocated | Needs Rhie-Chow | Requires pressure-velocity correction to avoid chequerboard |

**SOTA for 1D thermohydraulics**: staggered mesh. Pressure and void fraction
at cell centres, velocity at cell faces. Avoids pressure-velocity decoupling
and chequerboard pressure oscillations naturally.

**SOTA gap**: collocated mesh without Rhie-Chow interpolation — spurious
pressure oscillations, particularly at flow reversals.

### Numerical schemes

| Scheme | Order | SOTA? | Notes |
|---|---|---|---|
| Upwind (donor cell) | 1 | Baseline | Diffusive but stable |
| MUSCL (van Leer) | 2 | SOTA | Monotone, slope limiter |
| PPM (Colella-Woodward) | 3 | SOTA | Better accuracy; complex |
| WENO | 3-5 | SOTA for shocks | Overkill for most system codes |

**SOTA for two-phase system codes**: first-order upwind in time with
second-order spatial reconstruction (MUSCL + minmod or van Leer limiter).
Higher-order schemes add cost without stability benefit in the presence
of stiff source terms.

**SOTA gap**: central differences for convection terms — produces oscillations
at discontinuities (boiling front, void waves). Use upwind-biased schemes.

---

## Time integration for stiff two-phase systems <a name="time"></a>

Two-phase thermohydraulic equations are stiff due to:
- Fast acoustic waves (CFL condition: Δt ~ Δx/c_sound ~ 10⁻⁵ s)
- Stiff source terms (interphase exchange, wall heat transfer)
- Wide range of time scales (1 µs acoustic vs 1000 s thermal)

### Implicit vs explicit

| Scheme | Stability | Cost | SOTA? |
|---|---|---|---|
| Explicit Euler | Explicit | CFL-limited Δt | Not SOTA for stiff |
| Semi-implicit (SIMPLE-like) | Partial | 10-100× larger Δt | SOTA for system codes |
| Fully implicit | A-stable | Largest Δt | SOTA for stiff-dominant |
| IMEX (implicit-explicit splitting) | A-stable for stiff part | Good balance | SOTA for mixed |

**SOTA for nuclear system codes (CATHARE, RELAP5, SAM)**: semi-implicit
or fully implicit scheme allowing Δt ~ 0.01-1 s for steady-state approach,
Δt ~ 0.001-0.01 s during fast transients. The acoustic part is often
treated implicitly to remove the acoustic CFL constraint.

**SOTA gap**: explicit Euler for two-phase thermohydraulics — acoustic CFL
forces Δt ~ 10⁻⁵ s, making a 1000-second transient require 10⁸ time steps.
Completely impractical for safety analysis.

### Newton convergence

For fully implicit schemes, the nonlinear system is solved by Newton iterations.

**SOTA**: Newton-Krylov (NK) or Newton-GMRES for large systems.
JFNK (Jacobian-Free Newton-Krylov) avoids explicit Jacobian assembly.

**SOTA gap**: fixed-point (Picard) iteration for the implicit system without
Anderson acceleration or Newton correction — may require 10-50 iterations per
time step where Newton needs 3-5.

---

## Pressure-velocity coupling <a name="pressure"></a>

The pressure equation couples all cells through the incompressibility or
equation of state constraint.

### Pressure solvers for 1D networks

| Method | SOTA? | Notes |
|---|---|---|
| Thomas algorithm (tridiagonal) | SOTA for 1D | Single pipe: direct O(n) |
| LU for network (sparse) | SOTA for small network | n_junctions < ~10⁴ |
| GMRES + ILU for large network | SOTA for large | n_junctions > 10⁴ |
| Pressure correction (SIMPLE) | SOTA for iterative | Standard in CATHARE |

**For multi-1D network codes**: the pressure equation has the sparsity
structure of the network graph. For typical nuclear circuits (~10³ junctions),
sparse direct LU (UMFPACK) is faster than iterative solvers.

**SOTA gap**: dense LU for the pressure matrix — O(n³) cost.
Network pressure matrix is sparse (banded for linear pipes, sparse for junctions).
Use sparse LU (see `sota-linear-algebra.md`).

---

## Constitutive relations — closure laws <a name="closure"></a>

The 6-equation model requires closure laws for:
- Void fraction: drift-flux correlation (Zuber-Findlay or EPRI)
- Interfacial drag: Ishii-Zuber correlations per flow regime
- Wall heat transfer: Chen correlation for nucleate boiling, Dittus-Boelter for single-phase
- Critical heat flux (CHF): look-up tables (AECL 1995/2006) or correlations

**SOTA for flow regime detection**:
- Map-based (Taitel-Dukler, Hewitt-Roberts): deterministic flow pattern identification
- SOTA: continuous flow regime transition (void fraction-based smooth weighting)
  to avoid numerical discontinuities at regime boundaries

**SOTA gap**: sharp flow regime transitions (step function in void fraction)
— causes numerical oscillations and convergence difficulties. Use smooth
transition functions (e.g., tanh-based blending) near transition boundaries.

**SOTA for CHF**: 2006 AECL look-up tables are the most validated reference
for BWR/PWR conditions. Any code using older or simplified CHF correlations
should document validation range explicitly.

---

## Multi-1D network coupling <a name="network"></a>

Nuclear circuits consist of multiple 1D pipes, volumes, junctions connected
in a network (primary circuit, secondary circuit, steam generators, pressuriser).

**SOTA coupling approach**:
1. Build global pressure matrix from network topology
2. Solve simultaneously (not sequentially pipe-by-pipe)
3. Update velocities, void fractions, enthalpies from pressure solution

**SOTA gap**: Gauss-Seidel sequential sweep over pipes without global pressure
matrix — first-order convergence; convergence issues in strongly coupled loops
(counter-current flow in steam generators).

**Operator splitting for implicit thermal coupling**:
- Fluid equations implicit, fuel heat conduction implicit, exchange explicit
  → first-order operator split; SOTA: Strang splitting for 2nd order in time
- Full coupling (Picard or Newton): SOTA for tight coupling

---

## Common SOTA gaps <a name="gaps"></a>

1. **HEM for flows with significant slip** — use drift-flux or two-fluid model
2. **Explicit time integration** — acoustic CFL impractical; use semi-implicit
3. **Picard iteration without acceleration** — use Anderson acceleration or Newton
4. **Dense pressure matrix** — network is sparse; use sparse direct solver
5. **Sharp flow regime transitions** — use smooth blending functions
6. **Central differences for convection** — use upwind + MUSCL limiter
7. **Per-pipe pressure solve instead of global** — couples badly in closed loops

**Reference (open access)**:
Bestion, "The physical closure laws in the CATHARE code" (1990).
Nucl. Eng. Des. 124:229-245. (Check access — historical paper)
Berry et al., "RELAP-7 Theory Manual" (2014, rev. 1: 2015). INL/EXT-14-31366.
Searchable via the INL Digital Library (inldigitallibrary.inl.gov) or OSTI.gov.
Hu, "SAM Theory Manual" (2017). ANL/NE-17/4. OSTI open access.
https://www.osti.gov/biblio/1364503
