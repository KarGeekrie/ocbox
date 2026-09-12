# Fortran Review Checklist

Covers correctness and design in one pass.
Targets Fortran 2003/2008/2018 in scientific/HPC contexts.
For anti-pattern code examples: `references/patterns-fortran.md`.

---

## Correctness

Grep before reading: `grep -in "implicit\|common\|equivalence\|intent\|kind=\|real(\|allocat\|nullify\|associated\|goto" <file>`

### Implicit typing — #1 source of silent bugs
- [ ] **Missing `implicit none`** in every program unit (program, module, subroutine,
      function, block data). Without it, undeclared variables get default types
      (i–n = integer, rest = real), hiding typos silently. **CRITICAL if absent.**

### Arrays
- [ ] **Index base undocumented** — if an array is declared `A(0:N-1)`, document it;
      flag any caller that uses a mismatched base
- [ ] **Loop dimension order** — Fortran is column-major; the leftmost (first)
      index must be in the innermost loop for cache efficiency.
      `do j; do i; A(i,j)` is correct — `A(i,j)` and `A(i+1,j)` are adjacent in memory.
      `do i; do j; A(i,j)` is wrong — strides N elements per iteration.
- [ ] **Assumed-shape vs explicit-shape mismatch** — `A(:)` passed to `A(N)` dummy
      argument; must have explicit interface (put in module)
- [ ] **Shape mismatch in assignment** — incompatible array shapes assigned silently

### Intent
- [ ] **Missing `intent`** on dummy arguments — all args need `intent(in/out/inout)`;
      absence hides mutation and blocks optimisation
      (default MEDIUM; raise to HIGH per AGENTS.md if project mandates full intent)
- [ ] **`intent(in)` aliasing** — same variable passed as both in and out arg → UB

### Numerical precision
- [ ] **`kind=8` hardcoded** — not portable; define `dp = kind(1.0d0)` in a module
- [ ] **Literal without kind suffix** — `1.0` is default real; use `1.0_dp` in dp routines
- [ ] **Integer division where real expected** — `N/2` truncates; use `real(N,dp)/2.0_dp`
- [ ] **Accumulation in wrong precision** — summing dp array into sp accumulator
- [ ] **DO loop with real index** (Fortran 95+ removed) — use integer counter

### Memory
- [ ] **Allocatable used without `allocated()` check**
- [ ] **`allocate` without `stat=`** — a failed allocation without `stat=ierr` triggers
      an unrecoverable runtime error with no user-defined message; use:
      `allocate(x(N), stat=ierr, errmsg=msg); if (ierr /= 0) error stop msg`
- [ ] **Memory leak** — `allocate` without `deallocate` on all paths including error exits
- [ ] **Pointer not initialised** — declare with `=> null()` or call `nullify()`

### Legacy (flag, do not auto-fix)
- [ ] **`COMMON` blocks** — global mutable state; flag HIGH unless AGENTS.md marks intentional
- [ ] **`EQUIVALENCE`** — memory aliasing; flag HIGH
- [ ] **`GOTO`** — flag spaghetti use; cleanup-label gotos at routine end are acceptable

## Design
- [ ] **Subroutine/function > 80 lines** — decompose into named sub-procedures
- [ ] **Free-floating subroutine outside module** — no explicit interface; compiler cannot
      type-check callers; move into a module
- [ ] **`use module` without `only`** — imports everything; use `use mod, only: sym1, sym2`
- [ ] **Undocumented array shape convention** — assumed `(:)` vs explicit `(N)`: document which and why
- [ ] **Magic numbers** — define `parameter` constants with explanatory comment
- [ ] **Mixed kind style** — some routines use `kind=8`, others `dp`; standardise on named parameter
- [ ] Any design focus from AGENTS.md

## Performance

For projects with OpenMP or large numerical kernels, also load
`references/checklist-hpc.md`. Items below are Fortran-specific.

Grep: `grep -in "do concurrent\|contiguous\|pure \|elemental" <file>`

- [ ] **Missing `contiguous` attribute on assumed-shape array** — without it the
      compiler generates strided-load code even when the caller always passes
      contiguous data. Add `contiguous` to hot dummy arguments:
      `real(dp), contiguous, intent(in) :: a(:)`
- [ ] **`do` loop where `do concurrent` is valid** — if loop iterations are
      independent (no iteration reads a value written by another), use
      `do concurrent (i = 1:N)`. Signals parallelizability to compiler and runtime.
- [ ] **`pure` / `elemental` missing on referentially transparent functions** —
      `pure` functions have no side effects (no I/O, no global state mutation);
      the compiler can reorder, inline, and eliminate redundant calls freely.
      `elemental` additionally allows the function to be applied element-wise
      to array arguments. Both enable more aggressive optimisation.
- [ ] **Wrong loop order for multi-dimensional arrays** — innermost loop must
      iterate over the first (leftmost) index. See `patterns-hpc.md` and
      `checklist-hpc.md` for details.
- [ ] Any performance focus from AGENTS.md
