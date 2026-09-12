# SOTA — Multigrid Methods

Reference for Step 2 and Step 4.
Domain: geometric and algebraic multigrid, V/W/F-cycles, smoothers,
coarsening strategies. Highly relevant as standalone solvers and
preconditioners for neutronics and thermohydraulics systems.

---

## Table of contents
- [When to use multigrid vs direct solver](#when)
- [Geometric multigrid (GMG)](#gmg)
- [Algebraic multigrid (AMG)](#amg)
- [AMG libraries — production implementations](#libraries)
- [Common SOTA gaps](#gaps)

---

## When to use multigrid vs direct solver <a name="when"></a>

| Problem size | Sparsity | Recommendation |
|---|---|---|
| n < ~10⁴ | Any | Direct solver (LAPACK/UMFPACK) — simpler, robust |
| n ~ 10⁴–10⁶ | Structured (FD/FEM mesh) | GMG or BoomerAMG + CG |
| n > 10⁶ | Unstructured | AMG (BoomerAMG, AGMG, MueLu) — only viable O(n) option |
| Multiple RHS (same A) | Any | Factorize once (direct) if A fits in memory |
| Sequence of slowly varying A | Large | Recycle AMG setup: update coarse grids incrementally |

**O(n) complexity**: multigrid achieves O(n) solve complexity for elliptic
problems. Direct solvers are O(n^{1.5}) for 2D problems and O(n^2) for 3D.
For n > 10⁵ and single RHS, multigrid should dominate.

**SOTA gap signal**: using direct sparse solver (UMFPACK, PARDISO) on a
3D elliptic PDE system with n > 10⁶ — this will run out of memory or be
prohibitively slow compared to AMG-preconditioned CG/GMRES.

---

## Geometric multigrid (GMG) <a name="gmg"></a>

Applies when the problem lives on a structured or semi-structured mesh.

### Components

**Smoothers** (by quality for elliptic problems):
| Smoother | Cost per sweep | Good for |
|---|---|---|
| Weighted Jacobi (ω=2/3) | O(n) | Structured grids, parallelisable |
| Gauss-Seidel (GS) | O(n) | Serial, better smoothing than Jacobi |
| Red-Black GS | O(n) | Structured grids, parallel-friendly |
| ILU(0) | O(nnz) | Unstructured, stronger smoothing |
| Chebyshev polynomial | O(n) | Spectral radius known, good parallel |

**SOTA gap**: plain Jacobi smoother (ω=1) on an elliptic operator — diverges
or converges extremely slowly. Use weighted Jacobi (ω=2/3 for Laplacian on
uniform grid) or Gauss-Seidel.

**Cycle types**:
- V-cycle: cheap, robust for well-conditioned problems
- W-cycle: more expensive, better for anisotropic problems
- F-cycle (Full multigrid): nested iteration, O(n) optimal convergence, SOTA

**Coarse grid correction**: standard Galerkin P^T A P where P is prolongation.
For FEM: use standard linear interpolation. For FD: use 7-point stencil in 3D.

```fortran
! Minimal GMG V-cycle structure (pseudocode)
recursive subroutine vcycle(u, f, level)
  if (level == coarsest) then
    call direct_solve(u, f)
    return
  end if
  call smooth(u, f, nu1)          ! pre-smoothing (nu1 sweeps)
  call restrict(residual(u,f), fc) ! restrict residual to coarse grid
  call vcycle(uc, fc, level-1)    ! recursive coarse correction
  call prolongate(uc, u)           ! prolongate and correct
  call smooth(u, f, nu2)          ! post-smoothing (nu2 sweeps)
end subroutine
```

**Reference**: Briggs, Henson, McCormick, "A Multigrid Tutorial", 2nd ed.,
SIAM (2000). Free PDF: https://www.math.ust.hk/~mawang/teaching/math532/mgtut.pdf

---

## Algebraic multigrid (AMG) <a name="amg"></a>

Applies when the mesh is unstructured or the matrix comes from general FEM/FV.
AMG constructs the coarse grids from the matrix entries alone, no geometry needed.

### AMG variants

| Variant | Coarsening | SOTA use case |
|---|---|---|
| Ruge-Stüben (RS) | C/F splitting, strong connections | General SPD systems, classic |
| Smoothed aggregation (SA) | Aggregation of unknowns | FEM, better for elasticity |
| AGMG | Pairwise aggregation | Very robust, simple to use |
| Bootstrap AMG | Adaptive, learns near-null space | Indefinite, highly anisotropic |

**Choosing AMG variant**:
- Scalar elliptic (Poisson, diffusion): RS or SA, both work well
- Neutron diffusion (multigroup): SA with energy-block aggregation
- Elasticity / structural: SA preserving rigid body modes (need to pass them)
- Convection-dominated: AMG as preconditioner for GMRES, not standalone

**Near-null space**: for SA-AMG to work well, provide the near-null space
vectors. For scalar diffusion: constant vector. For elasticity: 6 rigid body
modes. Omitting this degrades convergence significantly.

**SOTA gap**: using unpreconditioned GMRES or CG on a large elliptic system
where AMG-preconditioned CG would converge in O(1) iterations (mesh-independent
iteration count for well-chosen AMG).

---

## AMG libraries — production implementations <a name="libraries"></a>

| Library | Language | Variant | Notes |
|---|---|---|---|
| **BoomerAMG** (Hypre) | C / Fortran IF | RS + SA | SOTA for HPC; used in LLNL codes |
| **MueLu** (Trilinos) | C++ | SA | Most flexible; near-null space API |
| **AGMG** | Fortran / C | Aggregation | Simplest to use; excellent for scalar |
| **GAMG** (PETSc) | C | SA | Good PETSc integration |
| **PyAMG** | Python | RS + SA | Development/prototyping; not HPC scale |

```python
# Python — PyAMG for moderate scale
import pyamg
A = build_matrix()
ml = pyamg.smoothed_aggregation_solver(A, B=near_null)
residuals = []
x = ml.solve(b, tol=1e-10, residuals=residuals)

# Python — scipy.sparse.linalg with BoomerAMG via pyamgx or petsc4py
# For HPC scale, use PETSc via petsc4py:
from petsc4py import PETSc
ksp = PETSc.KSP().create()
ksp.setType('cg')
pc = ksp.getPC()
pc.setType('hypre')
pc.setHYPREType('boomeramg')
```

```fortran
! Fortran — AGMG (simplest AMG interface)
! Download: https://homepages.ulb.ac.be/~ynotay/AGMG/
call dagmg(n, a, ja, ia, f, x, ijob, iprint, nrest, iter, tol)
! ijob=0: setup + solve; ijob=2: solve only (reuse setup)
```

**Reference**: Henson & Yang, "BoomerAMG: A Parallel Algebraic Multigrid
Solver and Preconditioner" (2002). Applied Numerical Mathematics 41:155-177.
DOI:10.1016/S0168-9274(01)00115-5.
Notay, "An Aggregation-Based Algebraic Multigrid Method" (2010).
Electron. Trans. Numer. Anal. 37:123-146. Free: http://etna.mcs.kent.edu

---

## Common SOTA gaps <a name="gaps"></a>

### Gap 1 — Gauss-Seidel without multigrid for large elliptic systems
Gauss-Seidel alone is O(n²) iterations × O(n) per iteration = O(n³) total.
AMG-preconditioned CG is O(n) total.
**Severity**: HIGH for n > 10⁴.

### Gap 2 — AMG without near-null space for SA variant
For smoothed aggregation AMG on elasticity or multigroup diffusion,
omitting the near-null space vectors causes SA to aggregate poorly,
destroying mesh-independent convergence.
**Severity**: MEDIUM (AMG still works, but may need 5-10× more iterations).

### Gap 3 — Rebuilding AMG setup at every time step
AMG setup (coarsening + smoother construction) costs O(n log n).
For time-dependent problems where A changes slowly, reusing the setup
for multiple time steps and only updating the operator is SOTA.
PETSc: `KSPSetReusePreconditioner` / Hypre: preserve coarse grids.
**Severity**: MEDIUM (performance, not correctness).

### Gap 4 — Using AMG as standalone solver instead of preconditioner
AMG convergence as a standalone solver can stagnate for non-elliptic problems.
SOTA: always use AMG as a preconditioner for CG (SPD) or GMRES (non-symmetric).
**Severity**: MEDIUM.
