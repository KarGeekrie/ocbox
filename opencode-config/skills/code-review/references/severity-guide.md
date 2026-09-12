# Severity Calibration Guide

Use these examples to anchor severity judgements consistently across projects.

---

## CRITICAL — must fix before any deployment

The code will produce incorrect results, crash under normal use, or expose
a vulnerability exploitable without special conditions.

Examples:
- Mutable default argument on an object shared across sessions
  → all users silently corrupt each other's state.
- Resource X must always be released before resource Y; the code reverses
  the order → requests are dropped silently.
- Index into a query result without checking if the result is empty
  → IndexError at runtime on every edge-case call.
- yaml.load() on user-supplied input → arbitrary code execution.

---

## HIGH — fix in the current sprint

Incorrect behaviour under specific but realistic conditions, OR a significant
maintainability time-bomb that will cause a production incident.

Examples:
- HTTP call without timeout → hangs forever if the remote is unresponsive,
  blocks the calling thread.
- `datetime.utcnow()` instead of `datetime.now(tz=timezone.utc)` → returns a
  naive datetime; mixing with timezone-aware datetimes raises TypeError.
  Deprecated since Python 3.12.
- Function exceeds project length limit (Python: 50 lines, C++: 60 lines,
  Fortran: 80 lines) with mixed concerns → untestable, change-averse.
- A core invariant (e.g. chunk_size > overlap) not enforced → downstream
  component receives invalid input and fails opaquely.

---

## MEDIUM — fix in the next sprint or before the feature ships

Correctness edge case requiring unusual input, OR a design smell that
compounds over time.

Examples:
- Missing type annotation on a public function → no IDE autocomplete,
  bugs hide at module boundaries.
- Magic number with no comment explaining its origin or tradeoff.
- Exception caught but only pass-ed, not logged → impossible to debug
  when it silently swallows errors in production.
- Test suite covers only the happy path for a function with 4 branches.

---

## LOW — fix when convenient

Cosmetic or theoretical issues with no realistic path to production impact.

Examples:
- Missing docstring on a private helper function.
- A variable named tmp in a 4-line function where intent is obvious.
- Unused import in a test file.

---

## Calibration notes

When in doubt between two levels, ask:
"If this went to production unfixed, what is the realistic worst case?"
- Data corruption or crash on normal input → CRITICAL
- Hang, wrong output on edge input, or debugging nightmare → HIGH
- Annoyance, tech debt, subtle misuse possible → MEDIUM
- Cosmetic, style, purely theoretical → LOW

**Performance findings** (Category: Performance) calibrate on measured or
estimable impact, not elegance:
- Data race in an OpenMP reduction (wrong results, not just slow) → CRITICAL
  (correctness masquerading as performance)
- Wrong loop order / false sharing in the dominant hot loop of the code
  (>2× measured or clearly estimable slowdown) → HIGH
- Missing `reserve`, missing `out=`, temporary allocation in a warm but
  non-dominant loop → MEDIUM
- Vectorization opportunity in cold code, micro-optimisation with no
  measurable path to total-runtime impact → LOW

Apply any project-level overrides from AGENTS.md after this initial
calibration.