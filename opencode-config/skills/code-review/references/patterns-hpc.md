# HPC / Scientific Computing Anti-Patterns

Quick lookup during the HPC performance review pass.
Each entry: bad pattern → why → correct form.

## Table of contents
- [Memory layout — AoS vs SoA](#layout)
- [Loop order and cache](#loops)
- [Vectorization inhibitors](#vectorization)
- [OpenMP](#openmp)
- [Scientific Python](#python)

---

## Memory layout — AoS vs SoA <a name="layout"></a>

### L-01 AoS with single-field inner loop (C++)
```cpp
// Context: particle simulation, inner loop only uses position
struct Particle {
    double x, y, z;    // position
    double vx, vy, vz; // velocity
    double mass;
};
std::vector<Particle> particles(N);

// WRONG — inner loop loads 7 doubles (56 bytes) per particle but uses only 3
// Cache line = 64 bytes → 1 particle per line → poor utilisation
for (size_t i = 0; i < N; ++i)
    force[i] = compute_force(particles[i].x, particles[i].y, particles[i].z);

// RIGHT — SoA: inner loop accesses contiguous x[], y[], z[] arrays
struct ParticlesSoA {
    std::vector<double> x, y, z;    // positions — each is contiguous
    std::vector<double> vx, vy, vz; // velocities — separate, not loaded
    std::vector<double> mass;
};
for (size_t i = 0; i < N; ++i)
    force[i] = compute_force(soa.x[i], soa.y[i], soa.z[i]);
// Now each cache line holds 8 consecutive x values → 8× better utilisation
// AND the compiler can auto-vectorize (unit stride, no aliasing)
```

### L-02 AoS with single-field inner loop (Fortran)
```fortran
! WRONG — derived type in hot loop; only one field accessed
type :: Particle
  real(dp) :: x, y, z, vx, vy, vz, mass   ! 56 bytes per particle
end type
type(Particle), allocatable :: p(:)

do i = 1, N
  force(i) = compute_force(p(i)%x, p(i)%y, p(i)%z)   ! loads 56 bytes, uses 24
end do

! RIGHT — structure of arrays
real(dp), allocatable :: px(:), py(:), pz(:)   ! contiguous per component
real(dp), allocatable :: pvx(:), pvy(:), pvz(:)
real(dp), allocatable :: pmass(:)

do i = 1, N
  force(i) = compute_force(px(i), py(i), pz(i))   ! unit stride, SIMD-friendly
end do
```

### L-03 Temporary allocation in hot loop
```cpp
// WRONG — new allocation per iteration
for (int step = 0; step < N_STEPS; ++step) {
    std::vector<double> tmp(N);   // malloc every step
    compute(data, tmp);
    apply(tmp, data);
}

// RIGHT — pre-allocate once
std::vector<double> tmp(N);
for (int step = 0; step < N_STEPS; ++step) {
    compute(data, tmp);
    apply(tmp, data);
}
```

---

## Loop order and cache <a name="loops"></a>

### O-01 Wrong loop order C++ (row-major)
```cpp
// C++ stores A[i][j] in row-major order: A[i][0], A[i][1], A[i][2]... are contiguous.
// Rule: for A[i][j], j must be in the INNERMOST loop (unit stride).

// WRONG — i is inner; accesses A[0][j], A[1][j], A[2][j]... separated by M elements
for (int j = 0; j < M; ++j)
    for (int i = 0; i < N; ++i)
        B[i][j] = A[i][j] * x[j];   // i inner → stride M in B and A → cache thrashing

// RIGHT — j is inner; accesses A[i][0], A[i][1], A[i][2]... contiguous (stride 1)
for (int i = 0; i < N; ++i)
    for (int j = 0; j < M; ++j)
        B[i][j] = A[i][j] * x[j];   // j inner → unit stride → SIMD-friendly
```

### O-02 Cache blocking for large matrices
```cpp
// WRONG — naive matrix multiply; working set >> L2 for large N
for (int i = 0; i < N; ++i)
    for (int k = 0; k < N; ++k)
        for (int j = 0; j < N; ++j)
            C[i][j] += A[i][k] * B[k][j];

// RIGHT — tiled (blocked) multiply; tile fits in L2 (~256 KB)
// Block size: sqrt(L2/3) / sizeof(double) ≈ 32 for 256 KB L2
constexpr int BS = 32;
for (int ii = 0; ii < N; ii += BS)
  for (int kk = 0; kk < N; kk += BS)
    for (int jj = 0; jj < N; jj += BS)
      for (int i = ii; i < std::min(ii+BS, N); ++i)
        for (int k = kk; k < std::min(kk+BS, N); ++k)
          for (int j = jj; j < std::min(jj+BS, N); ++j)
            C[i][j] += A[i][k] * B[k][j];
// NOTE: for production, use BLAS dgemm — it handles tiling automatically.
// Only implement manual tiling for custom kernels without BLAS equivalent.
```

---

## Vectorization inhibitors <a name="vectorization"></a>

### V-01 Pointer aliasing in C++ kernel
```cpp
// WRONG — compiler assumes a and b may overlap → no SIMD
void scale_add(double* a, const double* b, double alpha, int n) {
    for (int i = 0; i < n; ++i)
        a[i] += alpha * b[i];
}

// RIGHT — __restrict__ tells compiler: a and b never overlap
void scale_add(double* __restrict__ a, const double* __restrict__ b,
               double alpha, int n) {
    for (int i = 0; i < n; ++i)
        a[i] += alpha * b[i];
}
// Verify with: -fopt-info-vec (GCC) or -qopt-report (Intel)
```

### V-02 Branch in inner loop
```cpp
// WRONG — conditional prevents auto-vectorization
for (int i = 0; i < N; ++i) {
    if (data[i] > threshold)
        result[i] = std::sqrt(data[i]);
    else
        result[i] = 0.0;
}

// BETTER — ternary is a hint to the optimizer (not a guarantee of branchless code)
// Most modern compilers will generate a SIMD blend/select for this pattern
for (int i = 0; i < N; ++i)
    result[i] = (data[i] > threshold) ? std::sqrt(data[i]) : 0.0;
// Verify with: -fopt-info-vec (GCC) or -qopt-report=5 (Intel)
// If the compiler still generates branches, use explicit masking:
// double mask = (data[i] > threshold) ? 1.0 : 0.0;
// result[i] = mask * std::sqrt(std::abs(data[i]));  // always computes sqrt, masks result
```

### V-03 Virtual dispatch in inner loop
```cpp
// WRONG — virtual call prevents inlining → no SIMD, branch misprediction
for (int i = 0; i < N; ++i)
    result[i] = kernel->compute(data[i]);   // virtual dispatch every iteration

// RIGHT — template or devirtualize the hot path
template<typename Kernel>
void apply(const Kernel& kernel, const double* data, double* result, int n) {
    for (int i = 0; i < n; ++i)
        result[i] = kernel.compute(data[i]);   // inlined, vectorizable
}
```

### V-04 Fortran contiguous attribute
```fortran
! WRONG — assumed-shape without contiguous: compiler may assume non-contiguous
! strides → generates strided load code, inhibits SIMD
subroutine update(a, b, n)
  implicit none
  real(dp), intent(inout) :: a(:)
  real(dp), intent(in)    :: b(:)
  integer,  intent(in)    :: n
  integer :: i
  do i = 1, n
    a(i) = a(i) + b(i)
  end do
end subroutine

! RIGHT — contiguous attribute: unit stride guaranteed → auto-vectorization
subroutine update(a, b, n)
  implicit none
  real(dp), contiguous, intent(inout) :: a(:)
  real(dp), contiguous, intent(in)    :: b(:)
  integer,  intent(in)                :: n
  integer :: i
  do i = 1, n
    a(i) = a(i) + b(i)
  end do
end subroutine
```

---

## OpenMP <a name="openmp"></a>

### OMP-01 Missing reduction clause (data race)
```cpp
// WRONG — sum is shared by all threads → data race and wrong result
double sum = 0.0;
#pragma omp parallel for
for (int i = 0; i < N; ++i) {
    double tmp = heavy_compute(data[i]);
    sum += tmp;   // data race: multiple threads write sum simultaneously
}

// RIGHT — reduction clause: each thread gets a private sum, combined at the end
double sum = 0.0;
#pragma omp parallel for reduction(+:sum)
for (int i = 0; i < N; ++i) {
    double tmp = heavy_compute(data[i]);   // loop-local: implicitly private
    sum += tmp;
}
// Note: variables declared inside the parallel region (like tmp) are
// automatically private — no need to list them in a private() clause.
```

### OMP-02 False sharing in per-thread buffer
```cpp
// WRONG — partial[t] and partial[t+1] share a 64-byte cache line
// (8 doubles per cache line; 8 threads → 1 cache line for all)
double partial[MAX_THREADS];
#pragma omp parallel
{
    int t = omp_get_thread_num();
    for (int i = t; i < N; i += omp_get_num_threads())
        partial[t] += data[i];   // write to adjacent cache line slots → false sharing
}

// RIGHT — pad to cache line boundary (64 bytes = 8 doubles)
struct alignas(64) PaddedDouble { double val; char pad[56]; };
PaddedDouble partial[MAX_THREADS];
// OR: use thread-local scalar + final atomic add
double total = 0.0;
#pragma omp parallel reduction(+:total)
{
    double local = 0.0;
    #pragma omp for
    for (int i = 0; i < N; ++i) local += data[i];
    total += local;
}
```

### OMP-03 Fortran OpenMP missing clauses
```fortran
! WRONG — acc is shared → race condition on accumulation
real(dp) :: acc
acc = 0.0_dp
!$omp parallel do
do i = 1, N
  acc = acc + f(i)   ! data race
end do
!$omp end parallel do

! RIGHT
real(dp) :: acc
acc = 0.0_dp
!$omp parallel do reduction(+:acc)
do i = 1, N
  acc = acc + f(i)
end do
!$omp end parallel do
```

### OMP-04 do concurrent for compiler-parallelizable loops (Fortran 2008+)
```fortran
! OK but misses parallelization opportunity
do i = 1, N
  result(i) = expensive_f(data(i))   ! iterations are independent
end do

! BETTER — do concurrent signals independence to compiler + OpenMP runtime
do concurrent (i = 1:N)
  result(i) = expensive_f(data(i))
end do
! Compiler can vectorize and/or parallelize automatically.
! Requires: no iteration reads a value written by another iteration.
```

---

## Scientific Python <a name="python"></a>

### PY-01 Python for-loop over NumPy array
```python
# WRONG — Python interpreter overhead per element, GIL held, no SIMD
result = np.empty(N)
for i in range(N):
    result[i] = np.sqrt(data[i]) + offset   # 35-200x slower than vectorized

# RIGHT — vectorized: runs in C, SIMD-enabled, GIL released internally
result = np.sqrt(data) + offset
```

### PY-02 Python math module on arrays
```python
import math

# WRONG — math.sqrt is scalar-only; calling it on an array raises TypeError
# or forces a Python-level loop
result = [math.sqrt(x) for x in data]   # Python loop + no SIMD

# RIGHT
import numpy as np
result = np.sqrt(data)   # vectorized, SIMD-accelerated
```

### PY-03 np.append / np.concatenate in loop
```python
# WRONG — each append allocates a new array: O(N²) total memory operations
result = np.array([])
for chunk in data_chunks:
    result = np.append(result, process(chunk))   # copies entire result each time

# RIGHT — collect then stack once
parts = []
for chunk in data_chunks:
    parts.append(process(chunk))
result = np.concatenate(parts)   # single allocation
```

### PY-04 np.array() copy vs np.asarray() view
```python
# WRONG — np.array() always copies, even if input is already a numpy array
def kernel(data):
    arr = np.array(data)    # unnecessary copy if data is already ndarray
    return np.sum(arr ** 2)

# RIGHT — np.asarray() returns a view if possible
def kernel(data):
    arr = np.asarray(data)  # view if compatible dtype/layout, copy only if needed
    return np.sum(arr ** 2)
```

### PY-05 Missing out= for intermediate arrays in hot loop
```python
# WRONG — np.multiply allocates a temporary every iteration
tmp = np.empty(N)
for step in range(N_STEPS):
    result = np.multiply(a, b)       # new allocation each step
    result += c

# RIGHT — pre-allocate and use out= parameter
tmp = np.empty(N)
for step in range(N_STEPS):
    np.multiply(a, b, out=tmp)       # writes into pre-allocated buffer
    tmp += c
```

### PY-06 Manual linear algebra instead of scipy.linalg
```python
# WRONG — manual Gaussian elimination or Python loop matrix multiply
def solve_system(A, b):
    # ... manual implementation ... very slow

# RIGHT — LAPACK via scipy (threaded, optimised, numerically stable)
from scipy.linalg import solve, lu_factor, lu_solve
x = solve(A, b)                      # DGESV — full solve
lu, piv = lu_factor(A)               # factorize once
x1 = lu_solve((lu, piv), b1)        # solve for multiple right-hand sides
x2 = lu_solve((lu, piv), b2)
```
