---
name: code-review
description: >
  Perform a high-quality, checklist-driven code review of Python, C++, and
  Fortran projects, then apply safe fixes automatically. Use this skill for any
  request to review, audit, analyse, or improve code — "review my code", "find
  bugs in my project", "audit this package", "apply review recommendations".
  Loads language-specific checklists and project context from AGENTS.md, runs
  a single structured pass covering correctness, design, HPC performance, and
  binding-layer concerns, checks for test gaps, writes a prioritised report,
  and applies automatable fixes with a compile/test safety net. Automatically
  loads the HPC performance checklist when OpenMP, MPI, or NumPy/SciPy
  indicators are detected.
---

# Code Review Skill

One structured pass. Language-specific checklists. Fixes applied safely.

**In ocbox**: this skill only decides *how* to review — scope and checklists.
Whether it may also *apply* fixes depends on which agent runs it: `review`
denies the edit tool (read-only, so Step 4 below is skipped and every finding
is reported instead), `build` has full edit/bash access and can carry Step 4
through. See `launch-review.md` for the exact prompts, and
`opencode-config/agents/review.md` for why the split exists.

---

## Step 0 — Context

**0a. AGENTS.md** — look for it at the repo root (also AGENT.md).
Read it fully before anything else if found. It overrides all defaults:
architecture rules, focus areas, severity overrides, files off-limits for
auto-fix. Absent = fine, proceed with generic checklists.

**0b. Detect languages**
```bash
find . -not \( -path "*/\.*" -o -path "*/build/*" -o -path "*/__pycache__/*" \) \
  \( -name "*.py" -o -name "*.cpp" -o -name "*.cxx" -o -name "*.cc" \
     -o -name "*.hpp" -o -name "*.h" \
     -o -name "*.f90" -o -name "*.f95" -o -name "*.f03" -o -name "*.f08" \
     -o -name "*.F90" -o -name "*.for" -o -name "*.f" -o -name "*.F" \) \
  | sed 's/.*\.//' | sort | uniq -c
```
Note which languages are present. A project may have several. `.f`/`.F` are
legacy fixed-form Fortran 77 — common in older nuclear codes; do not skip them.

**0c. Build context** — read the top-level build file:
- Python  : `pyproject.toml` / `setup.py` / `requirements*.txt`
- C++     : `CMakeLists.txt` / `Makefile` / `meson.build`
- Fortran : same build files

Note: compiler standard, binding layer (pybind11 between Python and C++ only),
target platform (HPC, local, embedded).

**0d. Load checklists** — load now, before reading any source file:
- Python  → `references/checklist-python.md`
- C++     → `references/checklist-cpp.md`
- Fortran → `references/checklist-fortran.md`

**HPC/scientific project detection** — scan for performance-critical indicators:
```bash
grep -rl "omp\.h\|omp_lib\|MPI_Init\|#pragma omp\|!\$omp" . \
     --include="*.cpp" --include="*.hpp" --include="*.f90" --include="*.F90" \
     | head -3
grep -l "numpy\|scipy\|from numpy\|import numpy" \
     $(find . -name "requirements*.txt" -o -name "pyproject.toml") 2>/dev/null
grep -rl "do concurrent\|!DIR\$ SIMD\|!GCC\$ ivdep" . \
     --include="*.f90" --include="*.F90" | head -3
```
If any indicator is found, also load `references/checklist-hpc.md`.
Apply the HPC checklist to all languages present in the project.

Load the anti-pattern file for a language only when you encounter a finding
and need the corrected code form:
- `references/patterns-python.md`
- `references/patterns-cpp.md`
- `references/patterns-fortran.md`
- `references/patterns-hpc.md`  (when HPC checklist is loaded)

**0e. Scope resolution — commit or branch mode**

Use this when the user asks to review a specific commit or branch instead of
the whole project. This mode is narrower than a full review but wider than a
raw diff: it reviews complete functions touched by the change, not just the
changed lines, so the reviewer has the context needed to catch bugs a
line-level diff would miss (e.g. a changed line that breaks an invariant used
elsewhere in the same function).

**Step 1 — get the changed line ranges**

```bash
# Commit mode
git diff <commit>^..<commit> --unified=0 -- '*.py' '*.cpp' '*.hpp' '*.f90' '*.F90' '*.f' '*.F'

# Branch mode (compare against a base branch)
git diff <base_branch>...<branch> --unified=0 -- '*.py' '*.cpp' '*.hpp' '*.f90' '*.F90' '*.f' '*.F'
```
`--unified=0` gives exact changed-line ranges per file (`@@ -a,b +c,d @@` hunks)
without extra context lines cluttering the output.

**Step 2 — get the changed file list**

```bash
git diff <commit>^..<commit> --name-only          # commit mode
git diff <base_branch>...<branch> --name-only     # branch mode
```

**Step 3 — expand each changed line range to its enclosing function**

For every hunk, find the function/method/subroutine that contains it — do
not review isolated changed lines out of context:
- Python: scan upward from the first changed line for the nearest `def ` or
  `class ` at a lower or equal indentation level; scan downward to the next
  line at that same (or lower) indentation level to find the function end.
- C++: scan upward for the nearest function signature (return type + name +
  `(`); scan downward matching braces `{ }` to find the closing brace.
- Fortran: scan upward for `subroutine`/`function`; scan downward for the
  matching `end subroutine`/`end function`.

Read each enclosing function in full — this is the actual review scope, not
just the diff hunk.

**Step 4 — build the effective file list**

The set of files to review in Step 1 (main review pass) is the changed-file
list from Step 2. Within each file, prioritise the expanded functions from
Step 3, but you may read more of the file for context if a changed function
calls or is called by another function in the same file.

**Do NOT** silently fall back to a full-project review if this mode is
requested — if the commit/branch cannot be resolved (bad SHA, unknown
branch), stop and report the error instead of reviewing everything.

---

## Step 1 — Review pass

If commit/branch scope mode (Step 0e) was used, restrict this pass to the
effective file list and prioritise the expanded functions identified there.
Otherwise, review the full project.

Work file by file. For each file, use the grep from the loaded checklist
(each checklist starts with the appropriate grep command) before reading in
full — it is faster and more reliable than blind reading:

```bash
# C++ (from checklist-cpp.md)
grep -n "new \|delete\|nullptr\|reinterpret_cast\|memcpy\|push_back\|==.*\." <file>
# Fortran (from checklist-fortran.md)
grep -in "implicit\|common\|equivalence\|intent\|kind=\|real(\|allocat" <file>
```

Apply every checklist item for each language present. For the **pybind11 binding layer** (Python ↔ C++ only), apply the binding
section of both `checklist-python.md` and `checklist-cpp.md` to the relevant
files, even if the file is in the other language (e.g. a `.py` file that
calls a C++ routine via pybind11).

### Finding format

Every finding:

```
ID         : <LANG-NNN>   e.g. PY-001, CPP-003, F90-007
             (F90 prefix covers ALL Fortran, including legacy .f/.F fixed-form)
File       : relative/path/to/file
Line       : <exact integer — verified by grep, never from memory>
Language   : Python | C++ | Fortran
Category   : Correctness | Design | Binding | Performance | Documentation
Severity   : CRITICAL | HIGH | MEDIUM | LOW
Title      : ≤ 80 chars
Detail     : what is wrong and why it matters
Quote      : literal offending code ≤ 5 lines — mandatory, no quote = no finding
Fix        : concrete recommendation
Automatable: yes | no | partial
Test coverage: <filled in Step 2 — "covered by <test file>" or "no test found";
               leave blank during Step 1>
```

Two additional fields, present **only** when the finding matches a
SOTA-CHECK trigger (see below):
```
sota_check     : true
domain_hint    : linear-algebra | ode-pde | optimization | multigrid |
                 uncertainty-quantification | neutronics-deterministic |
                 neutronics-montecarlo | thermohydraulics
algorithm_hint : <one-line description of what appears to be implemented>
```

**Hard rules:**
- **AGENTS.md is the final authority.** Any default in this skill that conflicts
  with AGENTS.md is overridden by AGENTS.md — without exception. When in doubt,
  follow AGENTS.md.
- Quote must be copied from the actual file. Grep the line number to verify.
- One finding = one problem.
- Never flag patterns AGENTS.md marks as intentional.
- When unsure (especially UB in C++, subtle Fortran), say so in Detail rather
  than inventing a problem.
- Consult `references/severity-guide.md` for calibration.
- Consult `references/checklist-hpc.md` for performance findings (when HPC detected).

---

## SOTA-CHECK handoff (integration with the `sota-review` skill)

This skill checks correctness, design, and performance. It does **not**
judge whether the *algorithm itself* is the right choice — that is
`sota-review`'s job. When a finding involves a hand-rolled implementation of
a well-known numerical method (not a bug, an algorithmic choice), tag it so
the person can hand it to `sota-review` instead of guessing.

**Trigger patterns** — append `[SOTA-CHECK]` to the Title and add the two
extra fields above when a function matches any of these:

| Pattern | domain_hint |
|---|---|
| Explicit matrix inversion (`inv()`, manual Gauss-Jordan) | `linear-algebra` |
| Manual iterative solver (Jacobi/Gauss-Seidel/CG) with no preconditioner | `linear-algebra` or `multigrid` |
| Fixed-step, non-adaptive ODE integrator (manual RK4 loop) | `ode-pde` |
| Manual gradient descent with no line search or convergence criterion | `optimization` |
| Manual DFT/convolution loop where FFT would apply | `ode-pde` |
| Manual power iteration used for anything beyond the dominant eigenvalue | `linear-algebra` |
| Random Monte Carlo sampling where LHS/quasi-MC/PCE would apply, in a UQ context | `uncertainty-quantification` |
| Manual neutron transport sweep, source iteration, or power iteration for k-eff | `neutronics-deterministic` |
| Manual RNG or fission-source convergence logic in a Monte Carlo transport loop | `neutronics-montecarlo` |
| Explicit two-phase flow closure or manual pressure solve in a thermal-hydraulics context | `thermohydraulics` |

This list is a starting point, not exhaustive — use judgement for anything
that looks like "a textbook algorithm implemented by hand" even if it
doesn't match a row above.

**What this tag does NOT do:**
- Does not change `Automatable` — algorithmic choice is never auto-fixed here.
- Does not change `Severity` — this skill's severity still reflects
  correctness/design/performance impact, not algorithmic currency.
- Does not run `sota-review` itself — it only produces the routing hint.
  Running `sota-review` on flagged findings is a separate, explicit step
  the person takes afterward (see `launch-review.md` for the handoff prompt).

Add a one-line pointer at the end of the report when any `[SOTA-CHECK]`
finding exists:
```
N finding(s) flagged [SOTA-CHECK] — algorithmic choice not evaluated here.
Run sota-review on: <ID list> for a state-of-the-art assessment.
```

---

## Step 2 — Test gap check

This step reads **test files only** — no re-reading of source files already
covered in Step 1.

```bash
find . \( -name "test_*.py" -o -name "*_test.py" \
          -o -name "*test*.cpp" -o -name "test_*.cpp" \
          -o -name "*test*.cc" -o -name "*test*.cxx" \
          -o -name "*test*.f90" -o -name "test_*.f90" \
          -o -name "*test*.f" -o -name "*test*.F" -o -name "*test*.for" \) | sort
```

Also check for a CTest registration (`enable_testing()` / `add_test(` in
CMakeLists.txt) — C++/Fortran test executables are sometimes named without
"test" in the filename but registered there.

If **no test suite exists at all**: emit one finding `TST-001 | CRITICAL |
"No test suite — none of the findings below would have been caught automatically"`.

For every **CRITICAL** and **HIGH** finding from Step 1:
- Search for the function/variable name involved in any test file.
- Found → note `covered by <file>` next to the finding.
- Not found → emit `TST-NNN | HIGH | "No test covers <title>"`.

Also flag obvious structural gaps:
- Public function/subroutine with no mention in any test file.
- Test file with only happy-path cases (no error, boundary, or edge tests).

Test gap findings: `Quote` = `"no test found"`, `Automatable` = `no`.

---

## Step 2b — Documentation accuracy check

Works from the code already read in Step 1 — no extra file reading required.
Scope: every function/subroutine/method that contains a CRITICAL or HIGH finding,
plus any function modified by an auto-fix in Step 4.

For each in-scope function, read its docstring/header comment and verify:

**All languages**
- Does the docstring still describe what the function actually does? Flag if
  the description is stale (e.g. says "returns None on error" but code now raises).
- Are all current parameters documented? Flag any parameter present in the
  signature but absent from the docs.
- Are removed/renamed parameters still mentioned in the docs? Flag ghost entries.
- Is the return value described? Flag if the function returns a non-trivial value
  with no description.
- Are exceptions/error conditions documented? Flag if the code raises or returns
  an error code with no mention in the docs.

**Scientific code (C++, Fortran, numerical Python)**
- Are physical units documented for numerical parameters? Flag unqualified
  scalars in physics/simulation functions (e.g. `double dt` with no unit comment).
- Are valid input ranges or preconditions documented? Flag if the code has a
  guard (`if (dt <= 0) error stop`) but the docs don't mention the constraint.
- Are output conventions documented (e.g. column-major array, 1-based index,
  half-open interval)?

**Doc finding format**

```
ID         : DOC-NNN
File       : relative/path/to/file
Line       : line of the docstring or function signature
Category   : Documentation
Severity   : MEDIUM (stale/inaccurate doc) | LOW (missing unit/range note)
Title      : ≤ 80 chars
Detail     : what is wrong between code and documentation
Fix        : concrete correction (quote the suggested text if short)
Automatable: partial (if the fix is a one-line addition) | no
```

Do NOT emit DOC findings for:
- Private helpers (`_` prefix in Python, `private` in Fortran modules) unless
  AGENTS.md mandates full documentation.
- Functions with zero public callers.
- Files listed in AGENTS.md "Out of scope for auto-fix" (already exempted).

---

## Step 3 — Report

Write `review_report.md` at the repository root.

```markdown
# Code Review Report

**Project**: <name>
**Date**: <ISO>
**Languages**: <detected>
**Findings**: N total — Critical: N · High: N · Medium: N · Low: N
**Test gaps**: N
**Doc gaps**: N

---

## Executive Summary

<3–5 sentences: what the project does, overall quality, top 2–3 fixes.>

---

## Findings

### CRITICAL

#### PY-001 — <Title>
- **File**: `path/file.py` L<N>
- **Category**: Correctness
- **Quote**: `<code>`
- **Detail**: <explanation>
- **Fix**: <recommendation>
- **Automatable**: yes / no / partial
- **Test coverage**: covered by test_foo.py / no test found

### HIGH
...

### MEDIUM
...

### LOW
...

---

## Test gaps

<TST-NNN findings, or "None identified.">

---

## Documentation accuracy

<DOC-NNN findings (stale, missing, or physically under-specified docstrings),
or "None identified.">

---

## Flagged for SOTA review

<Findings tagged `[SOTA-CHECK]`, listed as: ID, Title, domain_hint. Or
"None identified." This skill does not judge algorithmic currency — hand
these IDs to the `sota-review` skill for that assessment.>

---

## Not flagged (and why)

<1–3 patterns that looked suspicious but are correct or intentional.
Shows the review was not superficial.>

---

## Automated fixes applied

| ID | File | Change |
|----|------|--------|
<!-- populated in Step 4 -->
```

---

## Step 4 — Apply fixes

Only reachable when the running agent can edit — see the note at the top of
this file. Skip this step entirely (leave every `Automatable: yes/partial`
finding unapplied in the report) when it cannot; that is not a failure, it is
`review`'s normal, read-only mode.

For every finding where `Automatable: yes` or `partial`:

1. Re-read the exact lines (never edit from memory).
2. Apply the minimal fix — do not refactor beyond the finding.
3. Add a trailing comment on the changed line:
   - Python  : `# review-fix <ID>: <reason>`
   - C++     : `// review-fix <ID>: <reason>`
   - Fortran : `! review-fix <ID>: <reason>`
   (omit for pure deletions)
4. Verify — **check tool availability first** (`which gfortran`, `which cmake`);
   these are not guaranteed present in every environment:
   ```bash
   python -m py_compile <file>                           # Python syntax
   gfortran -fsyntax-only -std=f2008 <file>              # Fortran syntax (f2008+ files)
   gfortran -fsyntax-only <file>                         # legacy .f/.F (no -std flag:
                                                         #  F77 code predates f2008)
   cmake --build build --target <target> 2>&1 | tail -20 # C++ compile
   python -m pytest --tb=short -q 2>&1 | tail -20        # Python tests
   cd <build_dir> && ctest --output-on-failure 2>&1 | tail -30 # C++/Fortran tests
   ```
   If the required compiler is **not installed**: do NOT apply the fix
   unverified, and do NOT silently skip it. Mark the finding
   `Automatable: no — verification toolchain unavailable (<tool>)` and leave
   it for the human. An unverified automated edit to numerical code is worse
   than no edit.
5. If verify fails: revert, mark `Automatable: no — build/test failure`.

See `agents/fix-applicator.md` for the subagent protocol when running in
parallel.

Update the report table with each applied fix.

---

## Step 5 — Output

```
Review complete.
  Languages : <list>
  Findings  : N total (N critical · N high · N medium · N low)
  Test gaps : N
  Doc gaps  : N
  SOTA-CHECK: N (see "Flagged for SOTA review" in the report)
  Auto-fixed: N
  Manual    : N require human decision
  Report    : review_report.md
```

Print every CRITICAL and HIGH finding by ID + title.
If any finding is tagged `[SOTA-CHECK]`, print those IDs separately with a
one-line note suggesting the `sota-review` skill.

---

## AGENTS.md

If no `AGENTS.md` exists at the project root, run `/init` in opencode — it
analyses the codebase and generates one automatically.

Once generated, you can optionally extend it with these review-specific
sections to get better-targeted findings:

```markdown
## Architecture rules
<!-- Patterns that look like bugs but are intentional. Not flagged.
Example: subprocess with shell=False and hardcoded args in scripts/ is intentional. -->

## Focus areas
<!-- Where bugs have bitten before. Skill prioritises these.
Example: src/solver.cpp: result buffer must be zeroed before each call. -->

## Severity overrides
| Pattern | Default | Override |
|---------|---------|----------|
| requests without timeout | MEDIUM | HIGH |

## Out of scope for auto-fix
<!-- Files/dirs the skill must never edit automatically.
Example: legacy/old_solver.f -->

## SOTA review targets
<!-- Optional. Read by the companion sota-review skill, not by this one.
     Declare algorithmic functions whose state-of-the-art status should be
     audited whenever sota-review runs on this project.
Example:
- src/solver/linear_system.f90 :: solve_banded  # custom banded solver
- src/integrator/rk4.cpp       :: step          # fixed-step RK4 -->
```
