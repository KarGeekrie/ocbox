# HPC / Scientific Computing Performance Checklist

Loaded in addition to the language checklist when HPC patterns are detected
(OpenMP, MPI, numerical compute kernels, NumPy/SciPy, large array operations).
For anti-pattern code examples: `references/patterns-hpc.md`.

---

## Memory access patterns — highest impact

Cache misses dominate runtime on modern CPUs. Fix these before anything else.

- [ ] **Non-unit stride in inner loop** — the innermost loop must iterate over
      contiguous memory. In C++/Fortran, the index that varies fastest in memory
      must be the inner loop variable.
      C++ (row-major): `for j { for i { A[i][j] }}` is wrong — stride N.
      Fortran (column-major): `do i { do j { A(i,j) }}` is wrong — stride N.
      Grep: any 2D array access where the *wrong* index is in the inner loop.

- [ ] **AoS hot field access** — if the inner loop accesses only one or two fields
      of a struct/derived-type, AoS causes each cache line load to bring in unused
      fields. Flag with `[PERF-AoS]`; note the fields actually used.
      Fix: SoA (separate arrays per field) or AoSoA (blocked SoA, group of 8).
      Do NOT flag if all fields are used together — AoS is correct there.

- [ ] **Temporary array allocation in hot loop** — `std::vector<>` construction,
      `allocate` inside a do-loop, `np.zeros(N)` inside a Python loop.
      Pre-allocate outside the loop and reuse.

- [ ] **Unnecessary copy of large array** — check for implicit copies:
      C++: passing `std::vector` by value; Fortran: non-`contiguous` assumed-shape
      passed to explicit-shape dummy (triggers copy-in/copy-out);
      Python/NumPy: `np.array(x)` always copies, `np.asarray(x)` does not.

- [ ] **False sharing** — two threads writing to different variables that share
      a cache line (64 bytes). Common in reduction arrays:
      `partial_sum[thread_id]` where partial_sum is `double[]` — 8 bytes per
      element, 8 elements per cache line → threads 0–7 share one line.
      Fix: pad to cache line size or use thread-local scalars + final reduction.

- [ ] **Cache blocking missing** — nested loops over 2D/3D arrays where the
      working set exceeds L2 cache (~256 KB typical). Should be tiled.
      Flag when: loop bounds > ~1000 × 1000 double elements AND no tiling visible.

---

## Vectorization

- [ ] **Branch in inner loop** — `if` / `switch` inside the innermost loop
      prevents auto-vectorization. Extract branch outside loop or use masked
      operations (`np.where`, `std::transform` with predicate, `where` construct).

- [ ] **Function call in inner loop** — non-inlined function call breaks
      vectorization. Check: virtual function, `std::function`, `std::bind`,
      any function defined in another translation unit without LTO.

- [ ] **Pointer aliasing** — compiler assumes pointers may alias → no SIMD.
      C++: add `__restrict__` to pointer arguments of compute kernels.
      Fortran: `contiguous` + `intent` suffices (Fortran standard forbids aliasing
      of `intent(in)` and `intent(out)` already).

- [ ] **Indirect indexing in inner loop** — `A[index[i]]` generates gather
      instruction; slower than unit-stride by 4-8×. Flag all gather patterns
      in inner loops.

- [ ] **Loop trip count too small** — auto-vectorization ineffective for N < 8
      (AVX2) or N < 16 (AVX-512) elements. Flag vectorization pragma on loops
      with statically known small bounds.

- [ ] **Mixed precision in same loop** — `float` and `double` operations mixed
      cause the compiler to generate scalar code or expensive conversion sequences.
      Use consistent precision throughout a kernel.

---

## OpenMP

Grep: `#pragma omp\|!\$omp\|omp_` before reading files with parallel regions.

- [ ] **Missing `private` clause** — loop variable or temporary used inside
      `parallel do/for` without `private(var)` → data race. Every variable
      written inside the parallel region must be `private` or `reduction`.

- [ ] **Missing `reduction` clause** — accumulator updated from multiple threads
      without `reduction(+:sum)` → data race and wrong result.

- [ ] **False sharing in reduction buffer** — `partial[omp_get_thread_num()] += x`
      where `partial` is a plain array → all threads share cache lines.

- [ ] **`critical` section in hot loop** — serialises all threads; throughput
      limited to single-thread performance. Replace with `reduction` or
      thread-local accumulation.

- [ ] **Too fine-grained parallel region** — OpenMP thread launch overhead is
      ~1–5 µs. Parallelising a loop whose serial time < 50 µs makes it slower.
      Flag parallel regions inside frequently-called functions.

- [ ] **`schedule(static)` on irregular work** — if iterations have very
      different cost (adaptive mesh, sparse matrix), `schedule(dynamic)` or
      `schedule(guided)` avoids load imbalance.

- [ ] **Nested parallel regions** — `#pragma omp parallel` inside another
      parallel region is usually disabled by default (`OMP_MAX_ACTIVE_LEVELS=1`).
      Flag when present; document intent.

---

## Scientific Python (NumPy / SciPy)

Grep: `for.*in.*range\|\.append\|math\.\|list(` in Python files that import numpy.

- [ ] **Python for-loop over array elements** — `for i in range(len(a)): b[i] = f(a[i])`
      is 35–200× slower than equivalent NumPy array operations.
      Fix: rewrite using NumPy broadcasting and ufuncs (`b = np.sqrt(a)`,
      `b = a * scale + offset`). For complex element-wise logic that cannot be
      expressed as a NumPy expression, use Numba (`@numba.njit`) — NOT
      `np.vectorize`, which provides convenience syntax only and is no faster
      than a Python loop (NumPy docs: "provided for convenience, not performance").
      Flag every explicit loop that operates element-by-element on a NumPy array.

- [ ] **Python `math` module on arrays** — `math.sqrt(x)` is scalar-only;
      `np.sqrt(x)` operates on the full array. Flag `import math` in scientific
      numerical files.

- [ ] **`np.matrix` usage** — deprecated since NumPy 1.15, scheduled for removal.
      Replace with `np.ndarray` and the `@` operator for matrix multiplication.

- [ ] **Unnecessary array copy** — `np.array(x)` always copies;
      `np.asarray(x)` returns a view if x is already a compatible array.
      Flag `np.array(existing_array)` in hot paths.

- [ ] **`np.concatenate` / `np.append` in loop** — each call allocates a new
      array; O(N²) total allocations. Pre-allocate with `np.empty` and fill by
      slice, or collect into a list then call `np.array(list)` once.

- [ ] **Linear algebra via manual loops** — `scipy.linalg` wraps LAPACK/BLAS
      (DGEMM, DGESV, etc.). Manual matrix multiply or solve in Python is orders
      of magnitude slower.

- [ ] **Missing `out=` parameter** — NumPy ufuncs accept `out=arr` to write
      results into a pre-allocated buffer, avoiding temporary allocation.
      Flag missing `out=` in hot loops: `np.multiply(a, b, out=c)`.

- [ ] **Non-contiguous array passed to pybind11** — see checklist-python.md
      binding section; non-contiguous slices trigger a copy inside pybind11
      even when `forcecast` is not set.
