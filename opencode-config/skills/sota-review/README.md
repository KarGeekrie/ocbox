# sota-review

State-of-the-art algorithmic review skill for opencode.
Checks that implemented numerical methods are consistent with current best
practices for scientific computing and physical system modelling.
Designed for neutronics, thermohydraulics, and multi-physics simulation labs.

## When to use

- You suspect a manual implementation where a mature library exists
- A code-review flagged `[SOTA-CHECK]` on a numerical kernel
- Before publishing or benchmarking: verify algorithmic choices are defensible
- Onboarding: audit inherited code for algorithmic debt

**Not a replacement for `code-review`**: this skill checks algorithmic choice
only, not correctness, memory safety, or style.

## File layout

```
sota-review/
├── SKILL.md                                   ← skill definition
├── launch-sota.md                             ← ready-to-use prompts
├── README.md
└── references/
    ├── candidate-detection.md                 ← grep patterns to find algorithmic candidates
    ├── literature-guide.md                    ← search strategy, access tiers, citation format
    │
    ├── sota-linear-algebra.md                 ← solvers, eigen, decompositions, inversion
    ├── sota-ode-pde.md                        ← time integration, symplectic, DAE, PDE, FFT
    ├── sota-optimization.md                   ← unconstrained, constrained, least squares, roots
    ├── sota-multigrid.md                      ← geometric + algebraic MG, AMG, BoomerAMG, AGMG
    ├── sota-uncertainty-quantification.md     ← PCE, Gaussian process, Sobol, OpenTURNS
    ├── sota-neutronics-deterministic.md       ← MOC, Sn, diffusion, CMFD, eigenvalue (k-eff)
    ├── sota-neutronics-montecarlo.md          ← OpenMC, variance reduction, criticality, RNG
    └── sota-thermohydraulics.md              ← two-phase models, implicit time stepping, pressure
```

## How it works

```
Step 0  Collect candidates (manual / cascade / AGENTS.md / auto-detect)
           Confirm list with user before proceeding
Step 1  Document the implementation
Step 2  Internal SOTA knowledge (from training + reference files)
Step 3  Literature search (arXiv, official docs, open-access benchmarks)
Step 4  Gap analysis — classify + assign Confidence rating:
           SOTA-GAP            superior method, no justification  [Confidence: high/medium only]
           SOTA-JUSTIFIED-UNDOC  deviation valid but undocumented
           SOTA-MISSING-BENCH  documented but no benchmark
           SOTA-CURRENT        aligned with or exceeds SOTA
           SOTA-UNCERTAIN      low confidence or insufficient evidence [always for Confidence: low]
Step 5  Write sota_report.md
Step 6  Produce migration sketches or benchmark templates for HIGH/MEDIUM findings
```

## Confidence rule

Every finding carries a `Confidence: high | medium | low` field.
`Confidence: low` → finding is forced to `SOTA-UNCERTAIN`.
This prevents false `SOTA-GAP` recommendations in specialised domains.

## Integration with code-review

`code-review`'s `SKILL.md` has a "SOTA-CHECK handoff" section that tags
findings when it recognises a hand-rolled implementation of a well-known
numerical method — matrix inversion, fixed-step ODE loop, unaccelerated
iterative solver, gradient descent with no line search, and a few
domain-specific patterns (neutronics, thermohydraulics, UQ). See that
section for the full trigger list — it is longer than the four examples
below and covers all domains in this skill's reference files.

This handoff is **manual, not automatic**: `code-review` never invokes
`sota-review` itself. The person reads the `[SOTA-CHECK]` tags in the
`code-review` report and explicitly runs the follow-up prompt below —
copied from `code-review`'s `launch-review.md`:

```
The code-review report flagged <ID> in <path/to/file> L<N> with [SOTA-CHECK]
(domain_hint: <domain>). Run a sota-review on that function.
```

## Installation

Ships as part of ocbox's team configuration — nothing to install by hand.
`opencode-config/skills/sota-review/` is bind-mounted read-only into every
sandbox (and linked into the config directory under `--no-sandbox`) as
`~/.config/opencode/skills/sota-review`; see the main
`opencode-config/skills/README.md` for how skill loading works.

## Domain coverage

| Domain | Reference file | Confidence level |
|--------|---------------|-----------------|
| Dense linear solve (structure-aware) | `sota-linear-algebra.md` | High |
| Sparse iterative + AMG preconditioner | `sota-linear-algebra.md` | High |
| Eigenvalue (LAPACK, ARPACK) | `sota-linear-algebra.md` | High |
| Explicit/adaptive ODE | `sota-ode-pde.md` | High |
| Stiff ODE (Radau, BDF, Sundials) | `sota-ode-pde.md` | High |
| Symplectic integrators | `sota-ode-pde.md` | High |
| FFT / NUFFT | `sota-ode-pde.md` | High |
| Unconstrained / constrained optimisation | `sota-optimization.md` | High |
| Nonlinear least squares | `sota-optimization.md` | High |
| Geometric + algebraic multigrid | `sota-multigrid.md` | High |
| PCE (sparse, non-intrusive) | `sota-uncertainty-quantification.md` | High |
| Gaussian process surrogate | `sota-uncertainty-quantification.md` | High |
| Sobol sensitivity indices | `sota-uncertainty-quantification.md` | High |
| Neutron diffusion + nodal methods | `sota-neutronics-deterministic.md` | Medium-High |
| Sn transport + DSA/CMFD acceleration | `sota-neutronics-deterministic.md` | Medium |
| MOC transport + CMFD | `sota-neutronics-deterministic.md` | Medium |
| MC criticality (k-eff) | `sota-neutronics-montecarlo.md` | Medium-High |
| MC variance reduction (CADIS) | `sota-neutronics-montecarlo.md` | Medium |
| Two-phase TH models (HEM, DFM, TFM) | `sota-thermohydraulics.md` | Medium |
| Implicit time integration for TH | `sota-thermohydraulics.md` | Medium-High |
