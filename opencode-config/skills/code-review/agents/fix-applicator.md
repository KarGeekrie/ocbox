# Fix Applicator Agent

Apply a single automated fix from the review report. One finding at a time.

## Inputs

- **finding**: the full finding JSON object
- **project_root**: repository root path
- **agents_md_out_of_scope**: list of files/patterns from AGENTS.md that must
  not be edited (empty list if no AGENTS.md)

## Process

### 1. Check out-of-scope guard
If finding.file matches any pattern in agents_md_out_of_scope, return:
  { "id": finding.id, "status": "skipped", "reason": "out of scope per AGENTS.md" }

### 2. Re-read the file
Read the entire file at finding.file. Do not rely on memory or the quote
field alone — the file may have been modified by a previous fix.

### 3. Locate the exact code
Find the lines matching finding.quote near finding.line.
If the quote is no longer present, return:
  { "status": "skipped", "reason": "quote not found — may already be fixed" }

### 4. Scope check
If the fix requires changing more than 5 lines, return:
  { "status": "skipped", "reason": "fix too broad — requires human review" }

### 5. Apply the minimal fix
- Change only what finding.fix describes.
- Do not refactor beyond the finding scope.
- Add a trailing comment on the changed line matching the file language:
    Python  : # review-fix <finding.id>: <one-line reason>
    C++     : // review-fix <finding.id>: <one-line reason>
    Fortran : ! review-fix <finding.id>: <one-line reason>
  Omit for pure deletions.

### 6. Syntax / compile check

**First verify the tool exists** (`which gfortran` / `which cmake` / `which g++`).
If the required compiler is not installed, do NOT apply the fix unverified:
return `{ "status": "skipped", "reason": "verification toolchain unavailable (<tool>)" }`.

Run the appropriate check for the file language:

```bash
# Python
python -m py_compile <file>

# Fortran (f90 and later)
gfortran -fsyntax-only -std=f2008 <file>
# Fortran legacy fixed-form .f/.F — omit -std (F77 predates f2008)
gfortran -fsyntax-only <file>

# C++ — recompile the target that includes this file
cmake --build build --target <target> 2>&1 | tail -20
# fallback if no CMake:
g++ -std=c++17 -fsyntax-only <file>
```

On failure: revert to original, return `{ "status": "reverted", "reason": "syntax/compile error" }`

### 7. Run tests if available
```bash
# Python
cd <project_root> && python -m pytest --tb=short -q 2>&1 | tail -20

# C++ / Fortran — use the project's own test runner
cd <build_dir> && ctest --output-on-failure 2>&1 | tail -30
# or: make test 2>&1 | tail -30
```
If tests fail AND the failure is plausibly caused by this fix, revert and
return { "status": "reverted", "reason": "test failure: <test name>" }.
If no test suite exists, skip this step.

## Output

```json
{
  "id": "PY-001",
  "file": "src/foo.py",
  "line": 42,
  "status": "applied",
  "change_summary": "Replaced bare except: with except Exception as e:",
  "syntax_ok": true,
  "tests_passed": true,
  "tests_run": 17
}
```

status values: "applied" | "reverted" | "skipped"
Include "reason" field when status is not "applied".