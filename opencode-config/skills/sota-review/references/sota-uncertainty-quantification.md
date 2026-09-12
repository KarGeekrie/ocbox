# SOTA — Uncertainty Quantification

Reference for Step 2 and Step 4.
Domain: forward UQ (propagation), surrogate models, sensitivity analysis,
inverse UQ (Bayesian calibration). Relevant to nuclear codes where uncertain
physical parameters (cross-sections, geometry, boundary conditions) propagate
to output quantities of interest.

---

## Table of contents
- [Method selection guide](#selection)
- [Polynomial Chaos Expansion (PCE)](#pce)
- [Gaussian Process surrogate (Kriging)](#gp)
- [Sampling methods](#sampling)
- [Sensitivity analysis — Sobol indices](#sobol)
- [Bayesian calibration](#bayes)
- [UQ libraries](#libraries)

---

## Method selection guide <a name="selection"></a>

| n_params | Cost per sim | Smoothness | SOTA method |
|---|---|---|---|
| ≤ 20, cheap sim | Any | Smooth | PCE (sparse quadrature) |
| ≤ 20, costly sim | Any | Smooth | GP surrogate (Kriging) |
| > 20, cheap sim | Any | Any | Monte Carlo + Sobol (LHS sampling) |
| > 20, costly sim | Very expensive | Smooth | GP + active learning, or PCE-sparse |
| Any, non-smooth | Any | Discontinuous | Monte Carlo or adaptive sparse PCE |
| Calibration | — | — | Bayesian MCMC or EnKF |

**SOTA gap signal**: plain Monte Carlo (random sampling) when a structured
approach (LHS, quasi-Monte Carlo, or PCE) would give the same accuracy with
10-100× fewer simulations.

---

## Polynomial Chaos Expansion (PCE) <a name="pce"></a>

PCE expands the output Y as a sum of orthogonal polynomials of the inputs:
Y = Σ c_α Ψ_α(ξ) where ξ are standardised random inputs.

### Variants

| Variant | How to compute coefficients | Use case |
|---|---|---|
| Non-intrusive PCE (regression) | Run model at quadrature/sparse points | Black-box codes |
| Non-intrusive PCE (projection) | Gauss quadrature projection | Smooth output |
| Sparse PCE (LARS/OMP) | Regression on random design + sparsity | High-dim inputs |
| Intrusive PCE | Modify governing equations | White-box codes; expensive development |

**SOTA for nuclear codes**: Non-intrusive sparse PCE (LARS regression).
Coefficients computed from a small set of model evaluations (~few hundred
for 10-20 input parameters). Full-order PCE requires d^p evaluations (curse
of dimensionality); sparse PCE uses ≈ 2p log(P) evaluations where P = n_coeffs.

```python
# SOTA — OpenTURNS sparse PCE
import openturns as ot
dist = ot.ComposedDistribution([ot.Uniform(-1,1)] * dim)
basis = ot.OrthogonalProductPolynomialFactory([ot.LegendreFactory()] * dim)
adaptive = ot.LARS()
fitting_algo = ot.LeastSquaresStrategy(adaptive)
algo = ot.FunctionalChaosAlgorithm(X_train, Y_train, dist, basis)
algo.run()
result = algo.getResult()
# Sobol indices directly from PCE coefficients — no extra simulations needed
sobol = ot.FunctionalChaosSobolIndices(result)
```

**SOTA gap**: full-tensor quadrature PCE when sparse PCE applies — exponential
cost vs near-linear for smooth outputs.

**Reference**: Blatman & Sudret, "Adaptive sparse polynomial chaos expansion
based on least angle regression" (2011). J. Comput. Phys. 230(6):2345-2367.
DOI:10.1016/j.jcp.2010.12.021.
Sudret, "Global sensitivity analysis using polynomial chaos expansions" (2008).
Reliab. Eng. Sys. Safety 93:964-979.

---

## Gaussian Process surrogate (Kriging) <a name="gp"></a>

GP models the output as a realisation of a Gaussian process:
Y(x) ~ GP(μ(x), k(x,x')). After training on n_train points, prediction is
exact at training points and provides uncertainty estimates everywhere.

### Kernel choice (critical for accuracy)

| Kernel | Properties | Use case |
|---|---|---|
| Squared exponential (SE) | Infinitely smooth | Smooth outputs, conservative |
| Matérn 5/2 | 2× differentiable | Physical simulations (recommended) |
| Matérn 3/2 | 1× differentiable | Rougher outputs |
| Rational quadratic | Scale mixture of SE | Multi-scale phenomena |

**SOTA**: Matérn 5/2 is the default recommendation for physical simulation
surrogates. SE is often over-smooth and under-estimates variability.

**SOTA gap**: SE kernel on a non-smooth response, or no nugget term when
simulation has numerical noise — leads to ill-conditioned covariance matrix.

```python
# SOTA — scikit-learn GP with Matérn kernel
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, WhiteKernel
kernel = Matern(nu=2.5) + WhiteKernel(noise_level=1e-5)
gpr = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=10,
                                normalize_y=True)
gpr.fit(X_train, y_train)
y_pred, y_std = gpr.predict(X_test, return_std=True)

# For large training sets (n > 1000): sparse GP (inducing points)
# Libraries: GPyTorch, GPflow
```

**Scalability**: standard GP is O(n³) for training, O(n²) for prediction.
For n > 500-1000 training points, use sparse GP approximations (inducing
points: GPyTorch, GPflow) or Hilbert space GP (HSGP).

**Reference**: Rasmussen & Williams, "Gaussian Processes for Machine Learning"
(2006). Free PDF: http://gaussianprocess.org/gpml/ (official, open access)

---

## Sampling methods <a name="sampling"></a>

For Monte Carlo UQ and design of experiments:

| Method | n needed for ε accuracy | Notes |
|---|---|---|
| Random Monte Carlo | O(ε⁻²) | Baseline; convergence ∝ 1/√n |
| Latin Hypercube Sampling (LHS) | O(ε⁻²) same but better coverage | SOTA for moderate d |
| Quasi-Monte Carlo (Sobol sequences) | O(ε⁻¹ log(n)^d) | SOTA for d ≤ 10-15 |
| Importance sampling | Problem-dependent | Rare events, tails |
| Antithetic variates | ~2× variance reduction | Smooth outputs |

**SOTA for nuclear UQ** (many parameters, few hundred sims): LHS with
correlation control (Iman-Conover method) or optimised LHS (maximin distance).

**SOTA gap**: random sampling when LHS or quasi-MC would give the same
variance estimate with half the simulations.

```python
# SOTA — scipy quasi-Monte Carlo (Sobol sequences, Halton)
from scipy.stats.qmc import Sobol, LatinHypercube
sampler = Sobol(d=n_params, scramble=True)
X = sampler.random(n=512)  # n must be power of 2 for Sobol
# Scale to parameter bounds:
from scipy.stats.qmc import scale
X_scaled = scale(X, l_bounds, u_bounds)
```

---

## Sensitivity analysis — Sobol indices <a name="sobol"></a>

Variance-based sensitivity: how much does each input parameter contribute
to output variance?

| Index | Formula | Meaning |
|---|---|---|
| S_i (first-order) | V[E[Y\|X_i]] / V[Y] | Main effect of X_i alone |
| S_{ij} (second-order) | Interaction X_i × X_j | |
| S_i^T (total) | 1 - V[E[Y\|X_{~i}]] / V[Y] | Total effect including interactions |

**SOTA**: Saltelli estimator (2010) for Sobol indices via Monte Carlo — needs
N×(2d+2) model evaluations. For d=10, N=1000: 22,000 simulations.

**SOTA for costly simulations**: Sobol indices from PCE coefficients — zero
additional model evaluations needed once PCE is built.

```python
# SOTA — SALib (standard library for sensitivity analysis)
from SALib.sample import saltelli
from SALib.analyze import sobol
problem = {'num_vars': d, 'names': names, 'bounds': bounds}
X = saltelli.sample(problem, N=1024, calc_second_order=True)
Y = run_model(X)
Si = sobol.analyze(problem, Y, calc_second_order=True)
print(Si['S1'], Si['ST'])
```

**Reference**: Saltelli et al., "Variance based sensitivity analysis of model
output. Design and estimator for the total sensitivity index" (2010).
Comput. Phys. Commun. 181:259-270.
SALib documentation: https://salib.readthedocs.io (open access)

---

## Bayesian calibration <a name="bayes"></a>

Estimate uncertain model parameters θ from measurements y:
posterior p(θ|y) ∝ likelihood p(y|θ) × prior p(θ).

| Method | SOTA? | Scale | Notes |
|---|---|---|---|
| MCMC (Metropolis-Hastings) | Baseline | Small d | Simple, but slow mixing |
| Adaptive MCMC | Better | Small-medium d | Haario et al. adaptation |
| Hamiltonian MC (HMC/NUTS) | SOTA | Medium d | Stan, PyMC; requires gradient |
| Ensemble Kalman Filter (EnKF) | SOTA | Large d | Sequential, no gradient needed |
| Variational Bayes | SOTA for large-scale | Large d | Approximate; fast |

**SOTA for nuclear calibration** (no gradient, expensive forward model):
EnKF or ensemble smoother (ES-MDA) with a GP surrogate replacing the
expensive forward model in the MCMC loop.

```python
# SOTA — PyMC for MCMC (gradient-based via JAX)
import pymc as pm
with pm.Model() as model:
    theta = pm.Normal('theta', mu=0, sigma=1, shape=d)
    mu = pm.Deterministic('mu', forward_model(theta))
    obs = pm.Normal('obs', mu=mu, sigma=sigma_obs, observed=y)
    trace = pm.sample(2000, tune=1000, target_accept=0.9)

# SOTA for expensive forward model: iterative_ensemble_smoother (open source)
# https://github.com/equinor/iterative_ensemble_smoother
```

---

## UQ libraries <a name="libraries"></a>

| Library | Language | Strengths |
|---|---|---|
| **OpenTURNS** | Python/C++ | SOTA for PCE, Kriging, Sobol; used in nuclear industry |
| **UQpy** | Python | Modern, research-oriented; good GP and PCE |
| **SALib** | Python | SOTA for Sobol sensitivity analysis |
| **Dakota** (Sandia) | C++ / Python IF | Production HPC UQ; NISP, LHS, OUU |
| **COSSAN** | MATLAB/Python | Structural reliability + UQ |
| **PyMC** | Python | Bayesian inference; SOTA MCMC |
| **GPyTorch** | Python/PyTorch | Large-scale GP with GPU; sparse GP |

**For neutronics UQ specifically**: OpenTURNS + SCALE/DRAGON/OpenMC
coupling is the documented industrial approach. SCALE's SAMPLER module
implements LHS for nuclear data uncertainty propagation.

**Reference (open access)**: Baudin, Dutfoy, Iooss & Popelin, "OpenTURNS: An
Industrial Software for Uncertainty Quantification in Simulation".
arXiv:1501.05242 (2015 preprint; published as a book chapter in Ghanem,
Higdon & Owhadi (eds.), Handbook of Uncertainty Quantification, Springer,
2017, DOI:10.1007/978-3-319-12385-1_64).
