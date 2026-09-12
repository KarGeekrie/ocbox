# Fortran Anti-Patterns — Reference Catalogue

Quick lookup during the review pass for Fortran files.
Each entry: bad pattern → why → correct form.
Focus: scientific/HPC Fortran 2003/2008/2018 + iso_c_binding / f2py.

## Table of contents
- [Implicit typing](#implicit)
- [Array and index errors](#arrays)
- [Numerical precision](#numerical)
- [Memory lifecycle](#memory)
- [Module structure and interfaces](#modules)
- [Legacy patterns](#legacy)
- [Binding layer (iso_c_binding / f2py)](#binding)

---

## Implicit typing <a name="implicit"></a>

### I-01 Missing implicit none — the most critical Fortran anti-pattern
```fortran
! WRONG — typo creates a new undeclared variable; result is silently wrong
subroutine update(alpha, x, y, n)
  real :: alpha, x(n), y(n)
  integer :: n, i
  do i = 1, n
    y(i) = alpah * x(i) + y(i)   ! typo: 'alpah' is a new real variable, value = undefined (garbage)
  end do
end subroutine

! RIGHT
subroutine update(alpha, x, y, n)
  implicit none
  real,    intent(in)    :: alpha
  real,    intent(in)    :: x(n)
  real,    intent(inout) :: y(n)
  integer, intent(in)    :: n
  integer :: i
  do i = 1, n
    y(i) = alpha * x(i) + y(i)
  end do
end subroutine
```
Every program unit (program, module, subroutine, function, block data)
must start with `implicit none`. No exceptions.

---

## Array and index errors <a name="arrays"></a>

### A-01 Undocumented array index base
```fortran
! WRONG — caller assumes 1-based, declaration is 0-based; silent wrong results
real, dimension(0:N-1) :: grid
! ... called from Python with 1-based indexing expectation

! RIGHT — document the base explicitly in the declaration comment
real, dimension(0:N-1) :: grid   ! 0-based: grid(0) = x_min, grid(N-1) = x_max
```

### A-02 Assumed-shape vs explicit-shape mismatch
```fortran
! WRONG — passing assumed-shape array to explicit-shape dummy arg
! causes descriptor mismatch; compiler may accept but runtime is wrong
subroutine fill(a, n)
  implicit none
  integer, intent(in)  :: n
  real,    intent(out) :: a(n)   ! explicit-shape
  ...
end subroutine

real, allocatable :: data(:)
allocate(data(100))
call fill(data, 100)   ! OK here, but fragile

! RIGHT — use assumed-shape consistently in modern Fortran
subroutine fill(a)
  implicit none
  real, intent(out) :: a(:)   ! assumed-shape — requires explicit interface
  ...
end subroutine
! Must be in a module or have an interface block to use assumed-shape
```

### A-03 Loop over wrong dimension order (cache thrashing)
```fortran
! WRONG — j is the inner loop; Fortran stores A column-by-column so A(i,j)
! and A(i+1,j) are adjacent in memory, but A(i,j) and A(i,j+1) are N apart.
! Iterating with j inner means every access jumps N elements — cache-unfriendly.
do i = 1, M        ! outer loop over first index
  do j = 1, N      ! inner loop over second index — strides N in memory
    A(i, j) = ...
  end do
end do

! RIGHT — i is the inner loop: consecutive A(i,j), A(i+1,j) are adjacent in memory
do j = 1, N        ! outer loop over second index (columns in math notation)
  do i = 1, M      ! inner loop over first index (rows) — unit stride
    A(i, j) = ...
  end do
end do
! Rule: in Fortran, the leftmost index must be in the innermost loop.
```

---

## Numerical precision <a name="numerical"></a>

### N-01 Hardcoded kind=8 instead of named parameter
```fortran
! WRONG — kind=8 is not guaranteed to be 64-bit on all compilers
real(kind=8) :: x

! RIGHT — define a named kind parameter in a module
module precision
  implicit none
  integer, parameter :: sp = kind(1.0)       ! single precision
  integer, parameter :: dp = kind(1.0d0)     ! double precision
  integer, parameter :: qp = selected_real_kind(33)   ! quad if available
end module

! Then in all code:
use precision, only: dp
real(dp) :: x
```

### N-02 Literal without kind suffix in double-precision routine
```fortran
! WRONG — 1.0 is default real (single precision on most compilers)
use precision, only: dp
real(dp) :: x, y
y = x + 1.0        ! 1.0 is sp; promotes, but precision of literal is lost

! RIGHT
y = x + 1.0_dp     ! explicit double-precision literal
! or
y = x + real(1, dp)
```

### N-03 Integer division where real result expected
```fortran
! WRONG — dx is declared real(dp) but L and N are integers;
! integer division happens before the assignment, discarding the remainder
integer  :: L, N
real(dp) :: dx
L = 10 ; N = 3
dx = L / N         ! evaluates to 3 (integer), then converts to 3.0_dp — wrong

! Also wrong in a different way:
integer :: N, half
N = 7
half = N / 2       ! half = 3, not 3.5 — only a bug if a fractional result was intended

! RIGHT
real(dp) :: dx
dx = real(L, dp) / real(N, dp)   ! = 3.333...
```

### N-04 Default real for accumulation
```fortran
! WRONG — sum of large single-precision array loses precision
real :: total
do i = 1, huge_n
  total = total + array(i)
end do

! RIGHT
real(dp) :: total
total = 0.0_dp
do i = 1, huge_n
  total = total + real(array(i), dp)
end do
```

### N-05 Real-valued DO loop index (Fortran 95+ incompatible)
```fortran
! WRONG — removed in Fortran 95; many compilers still accept but behaviour varies
real :: x
do x = 0.0, 1.0, 0.1   ! float steps accumulate error; count is unreliable

! RIGHT — use integer counter, compute real value inside
integer :: i
real(dp) :: x, dx
dx = 0.1_dp
do i = 0, 9
  x = i * dx
  ...
end do
```

---

## Memory lifecycle <a name="memory"></a>

### M-01 Using allocatable without checking allocation status
```fortran
! WRONG
real, allocatable :: workspace(:)
workspace(1) = 0.0   ! crashes or silent corruption if not allocated

! RIGHT
if (.not. allocated(workspace)) allocate(workspace(N))
workspace(1) = 0.0

! For pointers:
real, pointer :: p(:) => null()
if (.not. associated(p)) allocate(p(N))
```

### M-02 Memory leak — allocate without deallocate on all paths
```fortran
! WRONG — error path leaks workspace
subroutine solve(A, b, x, info)
  real, allocatable :: work(:)
  allocate(work(N))
  call lapack_routine(A, b, x, work, info)
  if (info /= 0) return   ! leaks work
  deallocate(work)
end subroutine

! RIGHT
subroutine solve(A, b, x, info)
  real, allocatable :: work(:)
  allocate(work(N))
  call lapack_routine(A, b, x, work, info)
  deallocate(work)         ! always reached; info checked by caller
end subroutine
! Or use a local allocatable — automatic deallocation on scope exit (F2003+)
```

### M-03 Pointer not initialised
```fortran
! WRONG — uninitialised pointer has undefined status; associated() is unreliable
real, pointer :: p(:)
if (.not. associated(p)) ...   ! undefined behaviour

! RIGHT
real, pointer :: p(:) => null()
if (.not. associated(p)) ...   ! safe
```

---

## Module structure and interfaces <a name="modules"></a>

### MD-01 Subroutine outside a module (no explicit interface)
```fortran
! WRONG — free-floating subroutine has implicit interface;
! compiler cannot check argument types or shapes
subroutine heavy_compute(A, n, result)
  ...
end subroutine

! RIGHT — place in a module
module compute_mod
  implicit none
contains
  subroutine heavy_compute(A, n, result)
    implicit none
    ...
  end subroutine
end module
! Callers: use compute_mod, only: heavy_compute
```

### MD-02 use module without only clause
```fortran
! WRONG — imports everything; hides what the code actually depends on
use big_physics_module

! RIGHT
use big_physics_module, only: rk4_integrate, GRAVITY_CONST, ParticleType
```

### MD-03 Missing intent on dummy arguments
```fortran
! WRONG — compiler cannot enforce read/write discipline; harder to optimise
subroutine scale(x, alpha, n)
  real    :: x(n), alpha
  integer :: n
  x = x * alpha

! RIGHT
subroutine scale(x, alpha, n)
  implicit none
  real,    intent(inout) :: x(n)
  real,    intent(in)    :: alpha
  integer, intent(in)    :: n
  x = x * alpha
end subroutine
```

---

## Legacy patterns <a name="legacy"></a>

### L-01 COMMON blocks
```fortran
! AVOID — global mutable state; no type safety across program units
COMMON /physics/ mass, charge, potential(1000)

! MODERN ALTERNATIVE — module variable (private by default, use accessor)
module physics_state
  implicit none
  private
  real, protected :: mass, charge
  real, allocatable :: potential(:)
  public :: set_mass, get_mass, ...
end module
```
Flag COMMON blocks as HIGH unless AGENTS.md marks them as intentional legacy
for linker compatibility.

### L-02 EQUIVALENCE
```fortran
! AVOID — memory aliasing; almost always a bug in new code
real    :: a
integer :: b
EQUIVALENCE (a, b)   ! a and b share the same memory location

! RIGHT — if type punning is needed, use transfer() or iso_c_binding
integer :: bits
bits = transfer(a, bits)
```

### L-03 GOTO (non-error-handling use)
```fortran
! ACCEPTABLE — error-handling goto to a cleanup label at end of routine
allocate(work(N), stat=ierr)
if (ierr /= 0) goto 999
...
999 continue
if (allocated(work)) deallocate(work)

! NOT ACCEPTABLE — spaghetti control flow
goto 200
100 x = x + 1
    goto 300
200 if (x > 0) goto 100
300 continue
```

---

## Binding layer — iso_c_binding / f2py <a name="binding"></a>

### BI-01 Missing bind(C) on exported procedure
```fortran
! WRONG — Fortran name mangling is compiler-specific; C/Python cannot find it
subroutine compute(x, n, result)

! RIGHT
subroutine compute(x, n, result) bind(C, name="compute")
  use iso_c_binding, only: c_int, c_double
  implicit none
  integer(c_int),  intent(in)  :: n
  real(c_double),  intent(in)  :: x(n)
  real(c_double),  intent(out) :: result
```

### BI-02 Raw Fortran types in C-facing interface
```fortran
! WRONG — type widths are not guaranteed
subroutine compute(x, n) bind(C, name="compute")
  real    :: x(n)   ! width depends on compiler default
  integer :: n

! RIGHT — use C-interoperable types from iso_c_binding
subroutine compute(x, n) bind(C, name="compute")
  use iso_c_binding, only: c_double, c_int
  implicit none
  real(c_double), intent(inout) :: x(n)
  integer(c_int), intent(in)    :: n
```

### BI-03 Array layout mismatch at Python boundary
```fortran
! Context: Fortran is column-major — the leftmost index varies fastest in memory.
! For A(i,j), elements A(1,j), A(2,j), A(3,j)... are contiguous (i varies fastest).
! NumPy default is C (row-major) — the rightmost index varies fastest.
! A Python array a[i,j] has a[i,1], a[i,2], a[i,3]... contiguous (j varies fastest).
!
! Consequence: a Fortran A(M,N) corresponds to a Python array of shape (N,M)
! in C order, OR shape (M,N) in Fortran order (np.asfortranarray).
!
! Document the expected layout in the subroutine comment:
! Expects A in Fortran (column-major) order: shape (M,N) with Fortran strides.
! Python caller: A_f = np.asfortranarray(A_c)  or  A_f = np.array(A_c, order='F')
subroutine matmul_wrapper(A, B, C, m, n, k) bind(C, name="matmul_wrapper")
```

### BI-04 f2py intent directive mismatch
```fortran
! WRONG — f2py will copy in the wrong direction
subroutine fill(output, n)
  implicit none
  integer, intent(in)  :: n
  real,    intent(out) :: output(n)
  ! Missing f2py directive; f2py may treat output as input
  output = 0.0

! RIGHT — add explicit f2py intent directives
subroutine fill(output, n)
  implicit none
  integer, intent(in)  :: n
  real,    intent(out) :: output(n)
  !f2py intent(out) output
  !f2py intent(hide) n
  output = 0.0
end subroutine
```

### BI-05 Work array exposed to Python caller
```fortran
! WRONG — Python caller must allocate and manage a workspace
subroutine solve(A, b, x, work, lwork, n)
  !f2py intent(in)  A, b, n, lwork
  !f2py intent(out) x
  !f2py intent(hide,cache) work  ! wrong: cache doesn't work reliably

! RIGHT — hide work array completely
subroutine solve(A, b, x, n)
  implicit none
  integer, intent(in)  :: n
  real,    intent(in)  :: A(n,n), b(n)
  real,    intent(out) :: x(n)
  real, allocatable    :: work(:)
  !f2py intent(in)  A, b, n
  !f2py intent(out) x
  !f2py intent(hide) n
  allocate(work(4*n))
  call internal_solve(A, b, x, work, 4*n, n)
  deallocate(work)
end subroutine
```
