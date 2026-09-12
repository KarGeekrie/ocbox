# Candidate Detection Guide

Used in Step 0 when no explicit scope is given.
Scan the codebase for functions that likely implement a known algorithm
and are therefore worth a SOTA review.

---

## Detection strategy

Run grep passes in order of signal strength. A function matching any
HIGH-SIGNAL pattern is a candidate. LOW-SIGNAL patterns need a second
confirmation before adding to the list.

---

## HIGH-SIGNAL patterns (strong algorithm indicators)

### Function / subroutine names

```bash
# Linear algebra — manual implementations
grep -rn "def solve\|def invert\|def lu_\|def chol\|def gauss\|def jacobi\
\|def seidel\|def cg_\|def gmres\|def bicg\|def pcg\b\|def sor\b\|def ilu" \
  --include="*.py" .

grep -rn "subroutine.*solve\|subroutine.*invert\|subroutine.*lu\|subroutine.*chol\
\|subroutine.*gauss\|subroutine.*jacobi\|subroutine.*seidel\|subroutine.*cg\b" \
  --include="*.f90" --include="*.F90" -i .

grep -rn "void.*[Ss]olve\|void.*[Ii]nvert\|void.*[Ll][Uu]\|void.*[Cc]hol\
\|void.*[Gg]auss\|void.*[Jj]acobi\|.*[Gg][Mm][Rr][Ee][Ss]" \
  --include="*.cpp" --include="*.hpp" .

# ODE / time integration
grep -rn "def.*step\b\|def.*integrate\|def.*rk[234]\|def.*euler\|def.*verlet\
\|def.*leapfrog\|def.*adams\|def.*bdf\b\|def.*radau\|def.*lsoda" \
  --include="*.py" -i .

grep -rn "subroutine.*step\|subroutine.*integrat\|subroutine.*rk[234]\
\|subroutine.*euler\|subroutine.*verlet\|subroutine.*leapfrog" \
  --include="*.f90" --include="*.F90" -i .

# Optimisation
grep -rn "def.*optim\|def.*minimiz\|def.*maximiz\|def.*gradient\|def.*newton\
\|def.*lbfgs\|def.*bfgs\|def.*cg_optim\|def.*lm_\|def.*levenberg\
\|def.*least_sq\|def.*residual" \
  --include="*.py" -i .

# Eigenvalue
grep -rn "def.*eigen\|def.*eig\b\|def.*power_iter\|def.*lanczos\|def.*arnoldi\
\|def.*qr_iter\|def.*lobpcg" \
  --include="*.py" -i .
```

### Comments citing algorithms or papers

```bash
# Algorithm names in comments — strong signal
grep -rn "Gauss-Seidel\|Jacobi iteration\|SOR\b\|SSOR\|Conjugate Gradient\
\|GMRES\|BiCGSTAB\|LU decomp\|Cholesky\|QR decomp\|Power method\
\|Lanczos\|Arnoldi\|Runge.Kutta\|Euler method\|Verlet\|Leapfrog\
\|Newton.Raphson\|Levenberg.Marquardt\|BFGS\|L.BFGS\|Nelder.Mead\
\|gradient descent\|steepest descent\|conjugate gradient" \
  --include="*.py" --include="*.f90" --include="*.F90" --include="*.cpp" \
  --include="*.hpp" -r .

# Paper citations in comments
grep -rn "[Rr]ef\.\|[Ss]ee.*[0-9]\{4\}\|doi:\|arXiv\|ISBN\|Algorithm [0-9]" \
  --include="*.py" --include="*.f90" --include="*.F90" --include="*.cpp" \
  --include="*.hpp" -r .
```

### Code structure signatures

```bash
# Triangular solve loops (LU backsubstitution) — a single-line pattern
# cannot detect a nested loop spanning multiple lines. Instead, find files
# with both pivot/dot-product vocabulary AND a loop keyword nearby, then
# read the function by hand:
grep -rln "pivot\|dot_product\|dot(" \
  --include="*.py" --include="*.f90" -r . \
  | xargs grep -l "for \|do "

# Explicit matrix inverse (always flag)
grep -rn "np\.linalg\.inv\|scipy\.linalg\.inv\|\.inv()\|matrix_inverse\
\|invert_matrix\|inv_mat\|A_inv\|Ainv\b" \
  --include="*.py" -r .

grep -rn "matinv\|mat_inv\|invert_mat\|compute_inverse\|A_inverse" \
  --include="*.f90" --include="*.F90" --include="*.cpp" -r -i .
```

---

## LOW-SIGNAL patterns (need confirmation)

These match common algorithmic idioms but also appear in boilerplate code.
Only add to candidate list if: (a) inside a function ≥ 20 lines, AND
(b) no corresponding scipy/LAPACK call exists nearby.

**Important limitation**: `grep` matches within a single line. Real nested
loops, multi-statement RK4 stages (k1/k2/k3/k4), and similar multi-line
constructs will NOT be caught by a single-line pattern spanning multiple
tokens — the patterns below are starting points to grep for a first token
(e.g. `for`, `k1`) and then read the surrounding lines by hand, not literal
patterns guaranteed to match complete constructs on their own.

```bash
# Candidate line: find loop headers, then read the following ~10 lines
grep -n "^\s*for \|^\s*do " --include="*.py" --include="*.f90" -r .

# Convergence checks (iterative solver pattern) — single-line, works as-is
grep -rn "residual\|converge\|tolerance\|tol\b\|norm.*<\|norm.*>\|abs.*err" \
  --include="*.py" --include="*.f90" --include="*.cpp" -r .

# RK-stage naming convention — find first occurrence, then read the function
grep -rn "\bk1\b\|\bk2\b\|\bk3\b\|\bk4\b" \
  --include="*.py" --include="*.f90" --include="*.cpp" -r .
```

---

## Automatic exclusion filters

Remove candidates matching these patterns — likely utility code, not algorithms:

```bash
# Test files — exclude
find . -name "test_*.py" -o -name "*_test.py" -o -name "*test*.f90"

# Generated code — exclude
find . -path "*/generated/*" -o -path "*/build/*" -o -path "*/__pycache__/*"

# Wrappers of standard libraries — exclude functions (not whole files) that
# only call scipy/LAPACK; a file mentioning scipy elsewhere may still have
# a real manual-implementation candidate function in it, so check per-function
# rather than dropping the whole file:
grep -n "scipy\.\|np\.linalg\.\|lapack\|blas\|LAPACK\|BLAS\|CHOLMOD\|UMFPACK" \
  --include="*.py" --include="*.f90" --include="*.cpp" -r .
```

---

## Cascade from code-review

`code-review` does not call this skill automatically — there is no
machine-to-machine handoff. When `code-review`'s report contains a finding
tagged `[SOTA-CHECK]`, the person copies the tag into a follow-up prompt
(see `code-review`'s `launch-review.md` → "Follow-up — hand a SOTA-CHECK
finding to sota-review"). The fields available in that finding, shown here
as JSON for clarity (the actual report format is plain text, not JSON):
```json
{
  "sota_check": true,
  "file": "src/solver.f90",
  "line": 42,
  "algorithm_hint": "manual banded LU solver",
  "domain_hint": "linear-algebra"
}
```
Add this directly to the candidate list; skip the grep step for that file.
Load the domain hint's reference file immediately.

---

## Domain-specific patterns — neutronics

```bash
# Deterministic transport / diffusion
grep -rn "subroutine.*flux\|subroutine.*diffus\|subroutine.*transport\
\|subroutine.*scatter\|subroutine.*fission\|subroutine.*eigenv\
\|power.iter\|source.iter\|keff\|k_eff\|k-eff\|wielandt\
\|cmfd\|CMFD\|dsa\|DSA\|sn.*sweep\|moc.*track\|method.of.charact" \
  --include="*.f90" --include="*.F90" --include="*.cpp" -r -i .

# Monte Carlo transport
grep -rn "def.*track\|def.*transport\|def.*collision\|def.*fission_bank\
\|def.*weight_window\|random_number\|rng\b\|mersenne\|pcg\b\
\|k_eff\|shannon_entropy\|inactive.*batch\|active.*batch" \
  --include="*.py" --include="*.cpp" -r -i .

# Eigenvalue specific
grep -rn "power_iter\|wielandt\|alpha.*eigen\|prompt.*mode\
\|arnoldi\|krylov.*eigen\|dominance.ratio" \
  --include="*.py" --include="*.f90" --include="*.cpp" -r -i .
```

## Domain-specific patterns — thermohydraulics

```bash
# Two-phase flow models
grep -rn "void.fract\|alpha\b.*liquid\|two.phase\|two_phase\
\|drift.flux\|slip.ratio\|interfac\|steam.quality\|quality\b\
\|hem\b\|HEM\b\|chf\b\|CHF\b\|critical.heat" \
  --include="*.f90" --include="*.F90" --include="*.cpp" -r -i .

# Time integration / pressure coupling
grep -rn "semi.implicit\|fully.implicit\|pressure.*matrix\
\|network.*junction\|picard.*iter\|newton.*thermo\
\|acoustic.*CFL\|time.step.*thermo" \
  --include="*.f90" --include="*.F90" -r -i .
```

## Domain-specific patterns — UQ

```bash
# Polynomial chaos / surrogate
grep -rn "polynomial.chaos\|pce\b\|PCE\b\|chaos.expansion\
\|legendre.*coeff\|hermite.*poly\|sobol.*index\|sobol.*indice\
\|kriging\|gaussian.process\|surrogate\b\|latin.hyper\|LHS\b" \
  --include="*.py" --include="*.f90" -r -i .
```
