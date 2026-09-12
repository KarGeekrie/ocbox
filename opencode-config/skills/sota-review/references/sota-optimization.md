# SOTA — Optimisation, Root Finding, Inverse Problems

Reference for Step 2 and Step 4.
Domain: unconstrained and constrained optimisation, nonlinear least squares,
root finding, parameter identification in physical models.

---

## Table of contents
- [Unconstrained, gradient available](#unconstrained-grad)
- [Unconstrained, derivative-free](#unconstrained-dfo)
- [Constrained optimisation](#constrained)
- [Nonlinear least squares](#leastsq)
- [Root finding](#roots)
- [Inverse problems and regularisation](#inverse)

---

## Unconstrained, gradient available <a name="unconstrained-grad"></a>

| Method | SOTA? | Scale | Notes |
|---|---|---|---|
| Gradient descent (fixed step) | No | — | SOTA gap: use line search |
| Gradient descent + line search | Baseline | Small | Wolfe conditions minimum |
| Conjugate Gradient (Fletcher-Reeves) | Baseline | Medium | Linear convergence |
| BFGS | Yes | Medium (n < ~10⁴) | Superlinear convergence; dense Hessian approx |
| L-BFGS-B | **SOTA** | Large | Limited-memory BFGS; SOTA for large-scale smooth |
| Newton-CG (trust region) | SOTA | Large | Exact Hessian-vector products via AD |

**SOTA gap**: gradient descent without adaptive step size / line search.
Fixed learning rates from ML contexts are not appropriate for physical optimisation.

```python
# SOTA for smooth unconstrained, large-scale
from scipy.optimize import minimize
result = minimize(f, x0, jac=grad_f, method='L-BFGS-B',
                  options={'maxiter': 1000, 'ftol': 1e-12})

# With Hessian (medium scale)
result = minimize(f, x0, jac=grad_f, hess=hess_f, method='trust-ncg')
```

**SOTA gap signal**: manual gradient descent loop without line search or
without a convergence criterion tied to gradient norm.

---

## Unconstrained, derivative-free <a name="unconstrained-dfo"></a>

| Method | SOTA? | Scale | Notes |
|---|---|---|---|
| Nelder-Mead | Baseline | n ≤ ~20 | No gradient needed; slow convergence |
| Powell's method | Baseline | n ≤ ~50 | Conjugate direction search |
| CMA-ES | **SOTA** | n ≤ ~1000 | Covariance Matrix Adaptation; SOTA evolutionary |
| Bayesian optimisation | SOTA | n ≤ ~50, costly f | BoTorch, Optuna; SOTA for expensive black-box |
| COBYLA | SOTA | Small | Linear constraint approximation |

**SOTA gap**: Nelder-Mead on n > 20 variables — empirically unreliable.
Use CMA-ES (`pip install cma`) or COBYLA for constrained derivative-free.

```python
# SOTA for derivative-free, medium scale
import cma
es = cma.CMAEvolutionStrategy(x0, sigma0=0.5)
es.optimize(f)
result = es.result.xbest

# SOTA for expensive black-box (few hundred evaluations budget)
import optuna
study = optuna.create_study(direction='minimize')
study.optimize(objective, n_trials=200)
```

**Reference**: Hansen, "The CMA Evolution Strategy" (2016). arXiv:1604.00772
Srinivas et al., "Gaussian Process Optimization" (2010). arXiv:0912.3995

---

## Constrained optimisation <a name="constrained"></a>

| Problem | SOTA method | Library | Notes |
|---|---|---|---|
| Equality + inequality, smooth | SLSQP | `scipy.optimize.minimize(method='SLSQP')` | Medium scale |
| Large-scale, general NLP | IPOPT | `cyipopt` | SOTA open-source NLP solver |
| Large-scale, smooth, sparse | SNOPT | Commercial | Often SOTA for engineering |
| Linear constraints | SLSQP or trust-constr | scipy | — |
| QP (quadratic program) | OSQP | `osqp` | SOTA open-source QP |

**SOTA gap**: augmented Lagrangian with simple penalty parameter — converges
slowly and is sensitive to penalty choice. Use SLSQP (for medium scale) or
IPOPT (for large scale) which implement proper interior-point or SQP methods.

```python
# SOTA medium scale
from scipy.optimize import minimize, NonlinearConstraint, Bounds
result = minimize(f, x0, jac=grad_f,
                  method='SLSQP',
                  constraints=[{'type': 'eq', 'fun': h, 'jac': jac_h},
                               {'type': 'ineq', 'fun': g}],
                  bounds=Bounds(lb, ub))

# SOTA large scale
import cyipopt
problem = cyipopt.Problem(n, m, problem_obj, lb, ub, cl, cu)
x_opt, info = problem.solve(x0)
```

**Reference**: Nocedal & Wright, "Numerical Optimization", 2nd ed. (2006).
Wächter & Biegler, "On the Implementation of IPOPT" (2006).
Math. Programming 106:25-57.

---

## Nonlinear least squares <a name="leastsq"></a>

Arises in parameter identification, data fitting, inverse problems.

| Method | SOTA? | Notes |
|---|---|---|
| Gauss-Newton | Baseline | Fast near solution, diverges far away |
| Levenberg-Marquardt | **SOTA** | Robust; blends Gauss-Newton and gradient descent |
| Trust-region reflective | SOTA | SOTA for bounded problems; handles sparse Jacobian |
| Dogleg | SOTA | Alternative to LM for unconstrained |

```python
# SOTA
from scipy.optimize import least_squares
result = least_squares(residual, x0,
                       method='trf',       # trust region reflective
                       jac=jac_residual,   # provide Jacobian for speed
                       bounds=(lb, ub),
                       ftol=1e-12, xtol=1e-12, gtol=1e-12)
# method='lm' for unconstrained (classic Levenberg-Marquardt)
```

**SOTA gap**: manual Gauss-Newton without line search or regularisation —
will diverge for bad initial conditions. Use `scipy.optimize.least_squares`.

**Large-scale sparse**: when the Jacobian is sparse, use
`jac_sparsity` parameter for automatic sparse finite differences.

**Reference**: Moré, "The Levenberg-Marquardt Algorithm" (1978).
Lecture Notes in Mathematics 630:105-116.

---

## Root finding <a name="roots"></a>

| Problem | SOTA method | Notes |
|---|---|---|
| Scalar, bracketed | Brent's method | SOTA; combines bisection, secant, inverse quadratic |
| Scalar, unbounded | Halley, Newton | Need good initial guess |
| Vector, small | Newton with LU | `scipy.optimize.fsolve` |
| Vector, large | Newton-Krylov (GMRES) | `scipy.optimize.newton_krylov` |
| Fixed-point iteration | Anderson acceleration | SOTA convergence acceleration |

```python
# SOTA scalar
from scipy.optimize import brentq
x_root = brentq(f, a, b, xtol=1e-12, rtol=1e-12)

# SOTA large vector system
from scipy.optimize import newton_krylov
x_root = newton_krylov(F, x0, method='gmres', f_tol=1e-10)

# Anderson acceleration for fixed-point x = g(x)
# pip install andersonacc  or  implement 3-5 line version
```

**SOTA gap**: Gauss-Seidel or Jacobi iterations without acceleration for
a nonlinear fixed-point problem. Anderson acceleration converges in O(m²)
history iterations vs O(1/ε) for unaccelerated fixed-point.

**Reference**: Walker & Ni, "Anderson Acceleration for Fixed-Point Iterations"
(2011). SIAM J. Numer. Anal. 49:1715-1735. Free PDF via SIAM open access.

---

## Inverse problems and regularisation <a name="inverse"></a>

Ill-posed problems arising in parameter identification from noisy data.

| Method | SOTA? | Use case |
|---|---|---|
| Tikhonov (L2 ridge) | SOTA baseline | Smooth solutions, Gaussian noise |
| LASSO (L1) | SOTA for sparse | Sparse parameter vectors |
| Total Variation | SOTA for piecewise constant | Edge-preserving |
| Truncated SVD (TSVD) | SOTA | When singular value spectrum reveals noise level |
| Randomised SVD | SOTA for large | Halko et al. (2011) |

```python
# SOTA regularised least squares
from scipy.sparse.linalg import lsqr
x, istop, itn, r1norm = lsqr(A, b, damp=lambda_reg)
# damp = Tikhonov parameter λ; LSQR = SOTA iterative for large sparse

# Cross-validation to choose λ
from sklearn.linear_model import RidgeCV
clf = RidgeCV(alphas=np.logspace(-6, 6, 100))
clf.fit(A, b)  # or use scipy for non-sklearn contexts
```

**SOTA gap**: manual normal equations (Aᵀ A + λI)x = Aᵀb for large problems.
Normal equations square the condition number — use LSQR instead, which
works with A directly.

**Reference**: Hansen, "Rank-Deficient and Discrete Ill-Posed Problems",
SIAM (1998). Bjorck, "Numerical Methods for Least Squares Problems",
SIAM (1996).
