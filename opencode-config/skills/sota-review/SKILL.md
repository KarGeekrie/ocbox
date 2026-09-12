---
name: sota-review
description: >
  Verify that implemented algorithms are consistent with the state of the art
  for scientific computing and physical system modelling. Use this skill when
  the user asks to audit algorithmic choices, verify that a numerical method
  is current, or check whether a manual implementation should use an existing
  library. Also triggered (optionally) by code-review findings tagged
  [SOTA-CHECK]. The skill identifies the algorithm in use, queries internal
  knowledge and open-access literature, assesses any gap, and produces a
  prioritised report with concrete upgrade or documentation recommendations.
---

# SOTA Review Skill

Algorithmic-level review: is the method implemented the best known approach
for this class of problem, given the project's constraints?

---

## Scope and trigger modes

### Manual trigger
The user names a specific function, class, or module:
```
Run a sota-review on src/solver/lu_decomp.cpp
Run a sota-review on the time integration in src/integrator/
```

### Cascade trigger (from code-review)
When `code-review` emits a finding tagged `[SOTA-CHECK]`, run this skill on
the flagged function. This tag is produced by the "SOTA-CHECK handoff"
section in `code-review`'s `SKILL.md` — not automatic; the person passes it
across explicitly (see `code-review`'s `launch-review.md` for the exact
handoff prompt). The finding carries:
- `file` and `line` of the function entry point
- `domain_hint` : which `sota-*.md` reference file to load first
- `algorithm_hint` : what the reviewer suspects is implemented

### AGENTS.md declarations
AGENTS.md may declare explicit SOTA review targets:
```markdown
## SOTA review targets
- src/solver/linear_system.f90 :: solve_banded  # custom banded solver
- src/integrator/rk4.cpp       :: step          # fixed-step RK4
```
Process all declared targets at every run of the skill.

---

## Step 0 — Collect candidates

1. Read AGENTS.md "SOTA review targets" if present.
2. If triggered manually: use the specified scope.
3. If triggered by cascade: use the code-review finding list.
4. If no scope given and no declarations: run candidate detection.
   Load `references/candidate-detection.md` and scan the project for
   algorithmic functions matching the patterns defined there.
5. Present the candidate list to the user and confirm before proceeding
   (SOTA analysis is expensive — do not run silently on 30 functions).

---

## Step 1 — Document the implementation

For each candidate function:

1. Read the function in full.
2. Identify:
   - **Algorithm name** if named in comments or docstring
   - **Paper or textbook reference** if cited
   - **Mathematical operation class** (linear solve, eigenvalue, ODE step, etc.)
   - **Structural properties exploited** (symmetric, banded, sparse, positive
     definite, stiff, Hamiltonian, etc.)
   - **Complexity** if assessable from code (loop structure, recursion)
3. Write a one-paragraph plain-language description of what the code does.
4. Note explicitly:
   - Is there a documented reason for not using a standard library?
   - Is there a benchmark comparing this implementation to alternatives?
   - Are the assumptions (e.g., matrix structure) validated at runtime?

---

## Step 2 — Internal SOTA knowledge

Before searching, state what is known from training data.
Load the relevant domain reference from `references/`:
- Linear algebra (solvers, decompositions, eigenvalues, inversion)
  → `references/sota-linear-algebra.md`
- ODE/DAE time integration, PDE discretisation, spectral methods
  → `references/sota-ode-pde.md`
- Optimisation, least squares, root finding, inverse problems
  → `references/sota-optimization.md`
- Multigrid (geometric and algebraic, AMG, BoomerAMG, AGMG, MueLu)
  → `references/sota-multigrid.md`
- Uncertainty quantification (PCE, Gaussian process, Sobol, OpenTURNS)
  → `references/sota-uncertainty-quantification.md`
- Neutronics — deterministic (MOC, Sn, diffusion, CMFD, eigenvalue)
  → `references/sota-neutronics-deterministic.md`
- Neutronics — Monte Carlo (OpenMC, variance reduction, criticality)
  → `references/sota-neutronics-montecarlo.md`
- Thermohydraulics — two-phase transient (HEM, drift-flux, two-fluid)
  → `references/sota-thermohydraulics.md`

Write for each candidate:
```
Domain         : <e.g., Dense symmetric linear solve>
Known SOTA     : <method, library, reference — from training>
Known since    : <approximate year>
Cutoff caveat  : Knowledge as of <state your own actual configured knowledge
                 cutoff date here — check your system prompt, do not guess
                 or copy a date from this skill file>. Newer results may exist.
```

---

## Step 3 — Literature search

Load `references/literature-guide.md` for search strategy and
access-status rules before issuing any query.

For each candidate, run the following searches in order:

**Search 1 — arXiv (open access)**
```
Query: <algorithm class> state of the art <year> arXiv
Fetch: top 3 relevant abstracts
```

**Search 2 — Reference implementations**
```
Query: <LAPACK | PETSc | Sundials | SciPy | ...> <operation> documentation
Fetch: official docs page
```

**Search 3 — Benchmark / comparison papers**
```
Query: comparison <method A> vs <method B> <domain> performance benchmark
```

For every source found, record:
```
Title  :
URL    :
Access : open | abstract-only | likely-paywalled
Year   :
Key finding :
```

Be explicit when a key paper is likely paywalled. Do not claim to have read
a paper you could only access by abstract. State what the abstract says and
flag `[abstract only]`.

---

## Step 4 — Gap analysis

For each candidate, compare Step 1 (what's implemented) against Steps 2–3
(SOTA). First assign a **Confidence** rating (see below), then classify.

The finding format gains one field:

```
ID         : SOTA-NNN
File       : relative/path/to/file
Line       : line of function signature
Domain     : <e.g., Dense symmetric linear solve>
Category   : SOTA-GAP | SOTA-JUSTIFIED-UNDOC | SOTA-MISSING-BENCH |
             SOTA-CURRENT | SOTA-UNCERTAIN
Confidence : high | medium | low
Severity   : HIGH | MEDIUM | LOW | INFO (INFO for SOTA-CURRENT / SOTA-UNCERTAIN)
Title      : ≤ 80 chars
Implementation: brief description of what is in the code
SOTA_alt   : best known alternative with reference
Gap        : quantified gap if possible (complexity, accuracy order, stability)
Justification: what the code/docs say about the chosen approach
Recommendation: adopt SOTA | add benchmark | add documentation | no action
Sources    : list of references with access tier
```

| Category | Definition |
|---|---|
| `SOTA-GAP` | A clearly superior method exists, is applicable to this problem structure, has a mature implementation, and the current code offers no documented justification for the deviation |
| `SOTA-JUSTIFIED-UNDOC` | The deviation appears technically motivated (special structure, real-time constraint, legacy coupling) but is NOT documented in the code |
| `SOTA-MISSING-BENCH` | Deviation is documented ("we use X because Y") but no benchmark or reference comparison validates the claim |
| `SOTA-CURRENT` | Implementation matches or exceeds known SOTA for this problem class |
| `SOTA-UNCERTAIN` | Insufficient open-access information to make a confident assessment; flag for domain-expert review |

**Confidence rating** — assign before finalising the category:

```
Confidence: high   — well-known problem class, consensus SOTA documented in
                     standard references and training data, independently
                     verifiable (e.g. LAPACK for dense solve, RK45 for non-stiff ODE)
Confidence: medium — familiar problem class but context-dependent (specific
                     sparsity structure, domain constraints, problem scale)
Confidence: low    — specialised domain, limited open-access literature found,
                     or active research area near training cutoff
```

**Hard rule**: `Confidence: low` → category is forced to `SOTA-UNCERTAIN`.
Do NOT emit `SOTA-GAP`, `SOTA-JUSTIFIED-UNDOC`, or `SOTA-MISSING-BENCH` when
confidence is low. A wrong SOTA-GAP recommendation costs more than a honest
SOTA-UNCERTAIN finding.

**Gap quantification** — express the gap in concrete terms when possible:
- Complexity: `O(n³)` vs `O(n² log n)`
- Accuracy order: `O(h²)` vs `O(h⁴)`
- Energy conservation: non-symplectic vs symplectic
- Conditioning: standard LU vs structure-exploiting Cholesky (2× faster, better stability)

---

## Step 5 — Report

Write `sota_report.md` at the project root.

```markdown
# SOTA Review Report

**Project**: <name>
**Date**: <ISO>
**Candidates reviewed**: N
**Search cutoff**: <the agent's own actual configured knowledge cutoff — read
it from your system prompt, never hardcode a date> internal knowledge +
live search <date>

---

## Summary

| ID | Function | File | Category | Severity |
|----|----------|------|----------|----------|
| SOTA-001 | solve_banded | solver.f90 L42 | SOTA-GAP | HIGH |
...

---

## Findings

### SOTA-001 — <Title>

**File**: `path/file.ext` L<N>
**Function**: `<name>`
**Domain**: <e.g., Banded linear system solver>

#### What is implemented
<Plain-language description from Step 1>

#### SOTA for this problem class
<Best known method, library, reference>

#### Gap
<Concrete gap description — complexity, accuracy order, stability>

#### Justification in code
<Quote from comments/docstring, or "None found">

#### Benchmark
<Exists / Missing / Partial>

#### Sources consulted
- [open] arXiv:XXXX.XXXXX — <title> — <key finding>
- [abstract only] DOI:XX.XXXX — <title> — <what abstract says>
- [paywalled] <journal> — <title> — not read

#### Recommendation
<One of: Adopt SOTA | Add benchmark | Add documentation | No action>

**Automatable**: no (architectural decision required)

---
```

Severity scale for SOTA findings:
- **HIGH**: gap has measurable production impact (stability, accuracy, or runtime > 2×) and no justification
- **MEDIUM**: gap is real but impact is bounded, or justification exists but is undocumented
- **LOW**: implementation is acceptable but not optimal; documentation improvement only

`SOTA-CURRENT` and `SOTA-UNCERTAIN` findings do not carry a HIGH/MEDIUM/LOW
severity — severity measures the size of a gap, and these two categories
have no gap to size. Use `Severity: INFO` for both. Do not omit them from
the summary table; they still count toward "Candidates reviewed" and are
often the most reassuring part of the report.

---

## Step 6 — Recommendations

For each HIGH and MEDIUM finding, produce one of:

**Adopt SOTA** — provide a concrete migration sketch:
```python
# BEFORE
result = manual_lu_solve(A, b)

# AFTER (scipy.linalg — LAPACK dgesv, partial pivoting, stable)
from scipy.linalg import solve
result = solve(A, b)  # or solve(A, b, assume_a='sym') for symmetric A
```

**Add benchmark** — provide a ready-to-run test template. Both sides must be
measured the same way: warm-up run excluded, same number of trials, median
(robust to outliers) rather than a single measurement:
```python
import numpy as np, time
from scipy.linalg import solve as scipy_solve

def _time(fn, *args, trials=10):
    fn(*args)                       # warm-up (JIT, caches, lazy imports) — excluded
    t = []
    for _ in range(trials):
        t0 = time.perf_counter()
        result = fn(*args)
        t.append(time.perf_counter() - t0)
    return np.median(t), result     # median: robust to scheduler noise

def benchmark(n=500, trials=10):
    rng = np.random.default_rng(42)          # fixed seed: reproducible
    A = rng.standard_normal((n, n)); A = A @ A.T + n * np.eye(n)  # SPD, well-conditioned
    b = rng.standard_normal(n)

    t_custom, x_custom = _time(custom_solve, A, b, trials=trials)
    t_ref,    x_ref    = _time(lambda A, b: scipy_solve(A, b, assume_a='pos'),
                               A, b, trials=trials)

    print(f"Custom : {t_custom*1000:.2f} ms (median of {trials})")
    print(f"LAPACK : {t_ref*1000:.2f} ms (median of {trials})")
    print(f"Max diff: {np.max(np.abs(x_custom - x_ref)):.2e}")
    # Accuracy criterion, not just speed: relative error vs a tight tolerance
    rel_err = np.linalg.norm(x_custom - x_ref) / np.linalg.norm(x_ref)
    print(f"Rel err : {rel_err:.2e}  ({'OK' if rel_err < 1e-10 else 'FAIL'})")
```

**Add documentation** — provide the comment block to insert:
```fortran
! Algorithm: <name> — chosen over <SOTA> because <reason>.
! Reference: <author, title, year>
! Validation: see tests/bench_<function>.py
! Known limitation: <what SOTA would improve>
```

---

## Quality rules

- Never assert a paper's conclusions you could only access by abstract.
  Write "Abstract states: …" and flag `[not fully verified]`.
- **Never assert an exact journal name, volume, page range, or arXiv ID from
  a `sota-*.md` reference file without verifying it via search first.** Those
  citations were LLM-authored and are not guaranteed accurate — see the
  caveat at the top of `references/literature-guide.md`. The paper's
  existence and general finding are usually reliable; the exact bibliographic
  string is not.
- Never recommend a library without checking it is actually available in
  the project's dependency environment (check `pyproject.toml`, `CMakeLists.txt`).
- A `SOTA-CURRENT` finding is a positive result — emit it explicitly.
  It documents that the algorithmic choice was reviewed and validated.
- Do not flag a deviation as `SOTA-GAP` if the code comments explain a
  valid constraint (real-time budget, legacy ABI, specific matrix structure).
  That is `SOTA-JUSTIFIED-UNDOC` only if the explanation is absent.
- `SOTA-UNCERTAIN` is a valid outcome. Honest uncertainty is better than
  a confident wrong claim.
