# C++ Review Checklist

Covers correctness, design, and binding layer in one pass.
Targets C++17/20, scientific/HPC and pybind11 contexts.
For anti-pattern code examples: `references/patterns-cpp.md`.

---

## Correctness

Grep before reading: `grep -n "new \|delete\|nullptr\|reinterpret_cast\|memcpy\|push_back\|==.*float\|==.*double" <file>`

### Memory
- [ ] **Raw owning pointer** — `new` without RAII; prefer `unique_ptr` / `vector`
- [ ] **Use-after-free** — pointer/reference used after owning container is destroyed or resized
- [ ] **Dangling reference** — returning reference to local; holding ref to container element after `push_back`
- [ ] **Double free** — raw pointer `delete`d twice; watch copy constructors
- [ ] **Missing Rule of Five** — custom destructor without copy/move constructor and assignment

### Undefined behaviour
- [ ] **Signed integer overflow** — `int` arithmetic that wraps; use `int64_t` or check limits
- [ ] **Null pointer dereference** — pointer used without nullptr check
- [ ] **Type punning via `reinterpret_cast`** — strict aliasing violation; use `memcpy` or `std::bit_cast`
- [ ] **Shift by negative or ≥ width** — UB if `n < 0` or `n >= sizeof(x)*8`

### Numerical (HPC)
- [ ] **Float equality `==`** — use `std::abs(a-b) < eps` with documented epsilon
- [ ] **Accumulation in wrong precision** — summing `float` array into `float` accumulator; use `double`
- [ ] **Integer division where real expected** — `int/int` truncates; cast one operand
- [ ] **Loop index `int` for large data** — use `size_t` or `ptrdiff_t` for N > 2³¹

### STL
- [ ] **Iterator invalidation** — modifying container during iteration
- [ ] **`std::string_view` dangling** — view outliving the string it points into
- [ ] **`std::map::operator[]` on read** — inserts default value if key absent; use `find()`
- [ ] **Narrowing conversion** — implicit `double → float` or `int64 → int32`; make explicit

## Design

- [ ] **Function > 60 lines** — decompose
- [ ] **Nesting > 3 levels** — extract or use early return/continue
- [ ] **Raw pointer in public API** — unclear ownership; prefer smart pointer or `std::span`
- [ ] **Magic number** — unnamed literal; use `constexpr` with explanatory comment
- [ ] **Missing `const`** — non-mutating methods and by-ref parameters should be const
- [ ] **Missing `noexcept`** — move constructor and destructor should be noexcept
- [ ] **Boolean flag argument** — `f(data, true)` is opaque; use enum or two functions
- [ ] **Missing direct `#include`** — relying on transitive includes is fragile
- [ ] Any design focus from AGENTS.md

## Performance

For projects with OpenMP, SIMD, or large numerical kernels, also load
`references/checklist-hpc.md`. Items below are C++-specific performance
issues not covered there.

Grep: `grep -n "virtual\|std::function\|new \|\.push_back" <file>`

- [ ] **Virtual dispatch in inner loop** — virtual function call in the
      innermost loop prevents inlining and SIMD. Use templates or devirtualize
      the hot path. See `patterns-hpc.md` V-03.
- [ ] **`std::function` in hot path** — type erasure overhead (~5–10ns per call).
      Fix: use a template parameter (zero-overhead, inlined at compile time).
      `std::function_ref` (C++26) or `tl::function_ref` (third-party) for
      non-owning callable references without heap allocation.
- [ ] **`std::vector::push_back` in loop without `reserve`** — may trigger
      repeated reallocations. Call `vec.reserve(expected_size)` before the loop.
- [ ] **`alignas` missing on SIMD-hot data** — hot arrays processed with AVX/AVX-512
      should be `alignas(32)` / `alignas(64)` to avoid split loads.
- [ ] Any performance focus from AGENTS.md

## Binding layer — C++ side (pybind11 / C API)

- [ ] **GIL not released** — CPU-intensive function holds GIL; use `py::gil_scoped_release`
- [ ] **Array layout not enforced** — accept only `py::array::c_style` or `f_style` explicitly;
      do not silently accept non-contiguous arrays
- [ ] **Lifetime not guaranteed** — Python wrapper outliving C++ object;
      use `py::keep_alive` or document the contract
- [ ] **Exception not translated** — uncaught C++ exception crashes the Python interpreter;
      pybind11 translates `std::exception` subclasses automatically, document what can throw
- [ ] **Type width mismatch** — C++ `int` is 32-bit; Python `int` is unbounded;
      document and match with `np.int32` on the Python side
