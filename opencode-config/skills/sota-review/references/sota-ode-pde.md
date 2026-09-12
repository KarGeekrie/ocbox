# SOTA — ODE/DAE Time Integration and PDE Discretisation

Reference for Step 2 and Step 4.
Domain: time-stepping schemes, symplectic integrators, stiff solvers,
DAE systems, PDE spatial discretisation, spectral methods.

---

## Table of contents
- [ODE integrators — non-stiff](#non-stiff)
- [ODE integrators — stiff](#stiff)
- [Symplectic integrators — Hamiltonian systems](#symplectic)
- [DAE systems](#dae)
- [PDE spatial discretisation](#pde)
- [Spectral / FFT methods](#spectral)

---

## ODE integrators — non-stiff <a name="non-stiff"></a>

### Quality hierarchy

| Method | Order | Adaptive | SOTA? | Notes |
|---|---|---|---|---|
| Forward Euler | 1 | No | Never | Academic only |
| RK4 (classical) | 4 | No | Rarely | No error control |
| Dormand-Prince (RK45) | 4(5) | Yes | **Yes** | SOTA for smooth non-stiff |
| Bogacki-Shampine (RK23) | 2(3) | Yes | Yes | Lower accuracy, faster steps |
| Verner (RK65) | 5(6) | Yes | Yes | Higher accuracy |

**SOTA gap**: Fixed-step RK4 where an adaptive RK45 applies.
A fixed step forces the user to guess an appropriate step size.
Dormand-Prince adjusts automatically, uses fewer function evaluations for
the same accuracy, and provides error estimates.

```python
# SOTA (Python)
from scipy.integrate import solve_ivp
sol = solve_ivp(f, [t0, tf], y0, method='RK45',
                rtol=1e-6, atol=1e-9, dense_output=True)

# SOTA (Fortran/C++) — ODEPACK DOPRI5 or equivalent
# Available via Fortran source: https://www.unige.ch/~hairer/software.html
```

**Reference**: Hairer, Norsett, Wanner, "Solving ODEs I", 2nd ed. (1993).
Dormand & Prince (1980), J. Comput. Appl. Math. 6:19-26.

---

## ODE integrators — stiff <a name="stiff"></a>

**Stiffness detection**: if a fixed explicit step size must be orders of
magnitude smaller than the problem timescale (to maintain stability rather
than accuracy), the system is stiff.

### Quality hierarchy

| Method | Order | Stiff? | SOTA? | Notes |
|---|---|---|---|---|
| Implicit Euler (BDF1) | 1 | Yes | No | Low accuracy |
| Crank-Nicolson / Trapezoid | 2 | Marginally | No | A-stable, not L-stable |
| Radau IIA | 5 | **Yes** | **Yes** | L-stable, high accuracy |
| BDF2-BDF6 | 2–6 | **Yes** | **Yes** | SOTA for very stiff large systems |
| SDIRK | varies | Yes | Yes | Stiffly-accurate DIRK variants |

**SOTA gap**: using a low-order stiff method (Implicit Euler, Crank-Nicolson)
where Radau or BDF would give the same stability at significantly higher order.

```python
# SOTA
sol = solve_ivp(f, [t0, tf], y0, method='Radau',
                rtol=1e-8, atol=1e-10, jac=jac_f)
# For very large stiff systems:
sol = solve_ivp(f, [t0, tf], y0, method='BDF',
                rtol=1e-8, atol=1e-10)
```

**For C++/Fortran**: Sundials CVODE is SOTA.
```
https://sundials.readthedocs.io  — open access
Python interface: diffrax (JAX-based), assimulo (Python wrapper)
```

**Reference**: Hairer & Wanner, "Solving ODEs II: Stiff and
Differential-Algebraic Problems", 2nd ed. (1996).

---

## Symplectic integrators — Hamiltonian systems <a name="symplectic"></a>

This is the most common SOTA gap in physics simulation code.

**Problem**: Hamiltonian systems (conservative mechanics, molecular dynamics,
orbital mechanics, plasma physics) have a conserved energy H(q,p) = const.
Standard Runge-Kutta methods are NOT symplectic — they introduce or dissipate
energy artificially, leading to unphysical drift in long-time simulations.

**SOTA gap signal**: RK4 (or any non-symplectic method) applied to a
Hamiltonian system q̈ = f(q) or equivalent first-order form.

### Symplectic methods (structure-preserving)

| Method | Order | Notes |
|---|---|---|
| Störmer-Verlet / Leapfrog | 2 | SOTA baseline; time-reversible; O(h²) |
| Ruth (1983) / Forest-Ruth | 4 | O(h⁴) symplectic |
| PEFRL | 4 | Position Extended Forest-Ruth Like; more efficient than Forest-Ruth |
| Yoshida (1990) | 6 | O(h⁶) symplectic via composition |
| Suzuki-Trotter | 2 | Used in quantum simulation |

```python
# Störmer-Verlet (example — no standard scipy implementation)
def verlet_step(q, p, dt, grad_V):
    p_half = p - 0.5 * dt * grad_V(q)
    q_new  = q + dt * p_half
    p_new  = p_half - 0.5 * dt * grad_V(q_new)
    return q_new, p_new

# For molecular dynamics: ASE, LAMMPS
# For orbital mechanics: rebound (N-body, open source)
```

**Gap severity**: HIGH when the simulation claims long-time energy conservation
without a symplectic integrator. RK4 applied to a Hamiltonian system will show
energy drift; symplectic methods show oscillating energy error bounded by O(h²).

**Reference**: Leimkuhler & Reich, "Simulating Hamiltonian Dynamics" (2004).
Hairer, Lubich, Wanner, "Geometric Numerical Integration" (2006).
Both are standard references; check library availability.

---

## DAE systems <a name="dae"></a>

Differential-Algebraic Equations arise naturally in constrained mechanics,
circuit simulation, and chemical kinetics.

| Method | SOTA? | Notes |
|---|---|---|
| Numerical differentiation index reduction + BDF | Yes | DASSL/DASPK |
| Implicit Runge-Kutta on DAE (Radau) | Yes | For low-index DAE |
| Sundials IDA | **SOTA** | BDF + Newton, handles index-1 DAE |

**SOTA gap**: manually differentiating constraints to reduce index, without
using a robust DAE solver. Index reduction should use Pantelides algorithm
or similar systematic approach.

```python
# Python: assimulo wraps Sundials IDA
from assimulo.solvers import IDA
from assimulo.problem import Implicit_Problem
```

**Reference**: Brenan, Campbell, Petzold,
"Numerical Solution of Initial-Value Problems in Differential-Algebraic
Equations", SIAM (1996).

---

## PDE spatial discretisation <a name="pde"></a>

### Finite differences

| Problem type | SOTA scheme | Notes |
|---|---|---|
| Elliptic (Laplacian) | Standard 2nd order FD or compact 4th order | Multigrid for solver |
| Parabolic (diffusion) | Crank-Nicolson in time + FD in space | Unconditionally stable |
| Hyperbolic smooth | WENO3/WENO5 | Weighted Essentially Non-Oscillatory |
| Hyperbolic with shocks | WENO5 + Riemann solver | Godunov-type |

**SOTA gap**: upwinding or forward differences for a hyperbolic problem
where WENO would provide higher accuracy with the same stencil.

### Finite elements

| Problem | SOTA | Framework |
|---|---|---|
| Elliptic / parabolic | Galerkin FEM | FEniCS, Firedrake, deal.II |
| Structural mechanics | Isogeometric Analysis (IGA) | More recent, not always SOTA |
| Fluid dynamics | Mixed FEM, DG | Problem-specific |

### Method of Lines

Spatial discretisation → ODE system → use SOTA ODE solver from above.
This is the standard approach. If the code implements a custom time
integrator instead of coupling to a library, flag with [SOTA-CHECK].

---

## Spectral / FFT methods <a name="spectral"></a>

### FFT implementations

| Context | SOTA | Notes |
|---|---|---|
| CPU, standard | FFTW3 | Industry standard; also numpy.fft (pocketfft, competitive since 1.17) |
| GPU | cuFFT (CUDA) | SOTA for GPU-accelerated FFT |
| Non-uniform | FINUFFT | Flatiron Institute NUFFT; open source; SOTA |
| Large distributed | MPI-FFTW, heFFTe | HPC FFT |

**SOTA gap**: manual DFT loop (`for k in range(N): sum exp(...)`) — always use FFT.
Gap: O(n²) vs O(n log n). Theoretical ratio ~n/log₂n (~750× at n=10⁴); the
realised speedup vs a pure-Python DFT loop is enormous (the loop adds
interpreter overhead on top of the O(n²)), but vs a BLAS-optimised dense DFT
matrix it is more modest (~20× measured at n=4096) — constants matter.
Either way FFT always wins; only the margin varies.

```python
# SOTA
import numpy as np
X = np.fft.rfft(x)    # real input → half spectrum, faster
x_back = np.fft.irfft(X, n=len(x))

# For non-uniform data (SOTA)
# pip install finufft
import finufft
c = finufft.nufft1d1(x_nonuniform, f_vals, n_modes)
```

**Reference**: FFTW: Frigo & Johnson, Proc. IEEE (2005). DOI:10.1109/JPROC.2004.840301
FINUFFT: Barnett et al., SIAM J. Sci. Comput. (2019). arXiv:1808.06736