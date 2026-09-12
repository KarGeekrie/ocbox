# Python Review Checklist

Covers correctness, design, and binding layer in one pass.
For anti-pattern code examples: `references/patterns-python.md`.

---

## Correctness

Grep before reading: `grep -n "except\|default=\|open(\|None\|utcnow\|yaml\|pickle\|requests\|subprocess" <file>`

- [ ] **Bare `except:`** — catches SystemExit/KeyboardInterrupt; hides all errors
- [ ] **Swallowed exception** — `except ...: pass` with no log or re-raise
- [ ] **Mutable default arg** — `def f(x=[])` or `def f(cfg={})`: shared across all calls
- [ ] **Unchecked None return** — result used without guard
- [ ] **Type mismatch** — int/float coercion, str/bytes confusion
- [ ] **Off-by-one** — slice bounds, range limits, loop indices
- [ ] **Resource leak** — `open()`, socket, DB connection outside `with`
- [ ] **Blocking call in async** — `requests.get`, `time.sleep`, `open` inside `async def`
- [ ] **Race condition** — shared mutable state across threads without lock
- [ ] **Naive datetime** — `datetime.utcnow()` returns tz-naive; use `datetime.now(tz=timezone.utc)`
- [ ] **Dict mutation during iteration** — `for k in d: del d[k]` → RuntimeError
- [ ] **`yaml.load` on untrusted input** — use `yaml.safe_load`
- [ ] **`pickle` on untrusted input** — arbitrary code execution
- [ ] **`requests` without `timeout=`** — hangs indefinitely (default MEDIUM; raise to HIGH per AGENTS.md for UI/server threads)
- [ ] **`subprocess` with `shell=True`** — shell injection if any argument contains user input; use `shell=False` with a list
- [ ] Any correctness focus from AGENTS.md

## Design

- [ ] **Function > 50 lines** — decompose into named helpers
- [ ] **Nesting > 3 levels** — extract or use early return
- [ ] **SRP violation** — function does more than one thing; name mismatch is the signal
- [ ] **Duplicated logic** — same block ≥ 2 times; extract
- [ ] **Magic number/string** — unnamed literal in logic
- [ ] **Missing type annotation** on public function
- [ ] **Missing docstring** on public function (one line minimum)
- [ ] **Circular import** or import-time side effect
- [ ] **`import *`** from non-`__init__` module
- [ ] Any design focus from AGENTS.md

## Scientific Python (NumPy / SciPy)

Any file importing numpy/scipy triggers HPC detection in `SKILL.md` Step 0
(the trigger greps for "numpy\|scipy" in dependency files), which loads
`references/checklist-hpc.md` — that file's "Scientific Python" section is
the complete, authoritative checklist for NumPy/SciPy performance patterns
(loop-vectorization, `np.matrix`, copy semantics, `out=`, manual linalg,
pybind11 array contiguity). Nothing to duplicate here.

## Binding layer — Python side (pybind11 / cffi)

Apply when Python calls into C++ via pybind11 or cffi:

- [ ] **Array layout** — pass `np.ascontiguousarray(x)` (C-contiguous / row-major)
      before crossing the pybind11 boundary; C++ expects contiguous memory by default
- [ ] **Type width** — `int` in Python is unbounded; use `np.int32` / `np.int64` explicitly
- [ ] **Error propagation** — C++ exceptions must surface as Python exceptions; uncaught = crash
- [ ] **Ownership** — document whether Python or C++ owns the memory; flag if unclear
