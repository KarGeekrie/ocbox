# SOTA — Linear Algebra

Reference for Step 2 (internal knowledge) and Step 4 (gap analysis).
Domain: dense and sparse solvers, decompositions, eigenvalue problems,
matrix-vector products. Relevant for physical system modelling.

---

## Table of contents
- [Matrix inversion — almost always wrong](#inversion)
- [Dense linear solve — structure matters](#dense-solve)
- [Sparse linear solve](#sparse-solve)
- [Eigenvalue problems](#eigen)
- [Structured matrix products](#structured)
- [Low-rank approximation](#lowrank)

---

## Matrix inversion — almost always wrong <a name="inversion"></a>

**Red flag**: any explicit computation of A⁻¹.

Computing A⁻¹ explicitly to then multiply A⁻¹b is:
- Same asymptotic cost as solve (both O(n³) for dense)
- Numerically less stable (propagates rounding from inversion into every solve)
- Memory-wasteful (stores full n×n inverse)

**SOTA**: solve directly.
- Single RHS: `scipy.linalg.solve(A, b)` → LAPACK `dgesv`
- Multiple RHS: factorize once, solve repeatedly:
  ```python
  from scipy.linalg import lu_factor, lu_solve
  lu, piv = lu_factor(A)
  x1 = lu_solve((lu, piv), b1)
  x2 = lu_solve((lu, piv), b2)
  ```
- C++ / Fortran: `LAPACK dgesv` (factorize+solve) or `dgetrf` + `dgetrs`

**Legitimate exceptions** (document explicitly):
- Computing `trace(A⁻¹ B)` — can sometimes be rewritten, but not always
- Updating inverse incrementally via Sherman-Morrison-Woodbury formula
- Explicit inverse needed for a physical observable (e.g., covariance matrix)

**Gap level if flagged**: HIGH — always flag unexplained explicit inversion.

---

## Dense linear solve — structure matters <a name="dense-solve"></a>

The single biggest source of SOTA gaps: using a general solver when the
matrix has exploitable structure.

| Structure | SOTA method | LAPACK routine | Python |
|---|---|---|---|
| General | LU, partial pivoting | `dgesv` | `scipy.linalg.solve` |
| Symmetric positive definite | Cholesky | `dpotrf` + `dpotrs` | `solve(A, b, assume_a='pos')` |
| Symmetric indefinite | Bunch-Kaufman | `dsytrf` + `dsytrs` | `solve(A, b, assume_a='sym')` |
| Banded general | Banded LU | `dgbsv` | `scipy.linalg.solve_banded` |
| Tridiagonal | Thomas algorithm | `dgtsv` | `scipy.linalg.solve_banded(1,1,...)` |
| Positive definite banded | Banded Cholesky | `dpbsv` | `scipy.linalg.solveh_banded` |
| Overdetermined (least squares) | QR | `dgels` | `scipy.linalg.lstsq` |
| Rank-deficient | SVD | `dgelsd` | `scipy.linalg.lstsq(cond=...)` |

**Common SOTA gap**: using `solve(A, b)` (general LU) on a symmetric positive
definite matrix. Cholesky is 2× faster, uses half the memory, and is more
numerically stable.

**Detection**: look for `np.linalg.solve`, `scipy.linalg.solve` without
`assume_a` keyword, or manual LU on a matrix that is known to be SPD from
the physics (mass matrix, stiffness matrix, covariance).

**Reference**: Golub & Van Loan, "Matrix Computations", 4th ed. (2013).
Anderson et al., "LAPACK Users' Guide", 3rd ed. (1999). Open access at
https://www.netlib.org/lapack/lug/

---

## Sparse linear solve <a name="sparse-solve"></a>

### Direct solvers (exact, for moderate-size problems)

| Structure | SOTA library | Python interface |
|---|---|---|
| General sparse | UMFPACK (SuiteSparse) | `scipy.sparse.linalg.spsolve` |
| Symmetric positive definite | CHOLMOD (SuiteSparse) | `scikit-sparse` |
| General, large | PARDISO (Intel MKL) | `pydiso` or MKL via scipy |

`scipy.sparse.linalg.spsolve` uses UMFPACK if installed, SuperLU otherwise.
For SPD systems in production HPC code, prefer CHOLMOD — significantly faster
for large SPD sparse systems.

### Iterative solvers (for very large systems)

| System type | SOTA method | Preconditioner | Python |
|---|---|---|---|
| SPD | Conjugate Gradient (CG) | AMG (PyAMG), ICC | `scipy.sparse.linalg.cg` |
| Symmetric indefinite | MINRES | ILU | `scipy.sparse.linalg.minres` |
| Non-symmetric | GMRES | ILU(k), AMG | `scipy.sparse.linalg.gmres` |
| Non-symmetric | BiCGSTAB | ILU | `scipy.sparse.linalg.bicgstab` |

**Preconditioner is critical**: unpreconditioned iterative solver is NOT SOTA.
An ILU preconditioner (`scipy.sparse.linalg.spilu`) reduces iteration count
by orders of magnitude. Algebraic multigrid (PyAMG) is SOTA for elliptic PDEs.

**SOTA gap signals**:
- Jacobi or Gauss-Seidel iterations without preconditioning
- Manual CG without a preconditioner on a large SPD system
- Fixed number of iterations instead of convergence criterion

**Reference**: Saad, "Iterative Methods for Sparse Linear Systems", 2nd ed.
Free PDF: https://www-users.cse.umn.edu/~saad/IterMethBook_2ndEd.pdf

---

## Eigenvalue problems <a name="eigen"></a>

| Problem | SOTA method | LAPACK/Library | Python |
|---|---|---|---|
| Dense symmetric, all eigenvalues | Divide-and-conquer | `dsyevd` | `scipy.linalg.eigh` |
| Dense symmetric, selected | MRRR | `dsyevr` | `scipy.linalg.eigh(subset_by_index=...)` |
| Dense non-symmetric | QR algorithm | `dgeev` | `scipy.linalg.eig` |
| Dense generalised Ax=λBx | `dsygv` | `dsygv` | `scipy.linalg.eigh(b=B)` |
| Sparse, few eigenvalues | Implicitly Restarted Arnoldi (IRAM) | ARPACK | `scipy.sparse.linalg.eigsh` |
| Sparse, few eigenvalues, more robust | Krylov-Schur | SLEPc | Improvement over IRAM (Stewart 2002); not in scipy |
| Sparse, largest/smallest | LOBPCG | — | `scipy.sparse.linalg.lobpcg` |
| Sparse, many eigenvalues | FEAST | Intel MKL FEAST | — |

**SOTA gaps**:
- Power iteration for anything but the dominant eigenvalue — use ARPACK
- Manual QR iteration — always use LAPACK
- Using `scipy.linalg.eig` (non-symmetric) on a symmetric matrix — use `eigh`
  which is 2-3× faster and guarantees real eigenvalues
- IRAM (ARPACK/scipy) restarting stagnates on tightly clustered eigenvalues;
  Krylov-Schur (SLEPc) is more robust for those cases but requires PETSc/SLEPc,
  a heavier dependency than scipy

**Structured eigenvalue problems** (physical systems often have structure):
- Mass-spring: generalised symmetric → `dsygv`
- Stability analysis of dynamic systems: `dgeev` but check for structure
- Gyroscopic systems (skew-symmetric part): specialised methods exist

---

## Structured matrix products <a name="structured"></a>

Manual O(n²) or O(n³) products where structure allows faster computation:

| Structure | Naive | SOTA | Speed |
|---|---|---|---|
| Toeplitz/circulant | O(n²) matvec | FFT-based O(n log n) | asymptotic ratio ~n/log n; realised speedup depends heavily on constants (a BLAS-optimised dense matvec narrows the gap) — benchmark on the actual case |
| Low-rank A = UVᵀ | O(n²) matvec | O(nk) where k≪n | — |
| Kronecker product A⊗B | O(n²m²) | O(n²m + nm²) | — |
| Block diagonal | O(N³) | O(N·b³) per block | — |

**Detection**: look for nested loops over matrix rows/columns where the matrix
has a known analytic structure from the physics.

---

## Low-rank approximation <a name="lowrank"></a>

For large dense matrices where exact factorisation is too expensive:

| Method | SOTA implementation | Use case |
|---|---|---|
| Randomised SVD | `sklearn.utils.extmath.randomized_svd` | Large dense, approximate top-k singular values |
| Randomised range finder | Halko et al. (2011) | Basis for many randomised algorithms |
| Hierarchical matrices (H-matrices) | HLIBpro, H2Lib | Dense matrices from BEM, covariance |

**Reference (open access)**: Halko, Martinsson, Tropp,
"Finding Structure with Randomness" (2011), SIAM Review.
arXiv:0909.4061