# C++ Anti-Patterns — Reference Catalogue

Quick lookup during the review pass for C++ files.
Each entry: bad pattern → why → correct form.

## Table of contents
- [Memory management](#memory)
- [Undefined behaviour](#ub)
- [Numerical / HPC](#numerical)
- [Standard library pitfalls](#stdlib)
- [Design](#design)
- [Binding layer (pybind11)](#binding)

---

## Memory management <a name="memory"></a>

### M-01 Raw owning pointer
```cpp
// WRONG
int* data = new int[n];
process(data);
delete[] data;   // skipped if process() throws

// RIGHT
auto data = std::make_unique<int[]>(n);
process(data.get());
// freed automatically when data goes out of scope
```

### M-02 Returning reference to local variable
```cpp
// WRONG
const std::string& get_label() {
    std::string s = compute();
    return s;   // dangling: s destroyed on return
}

// RIGHT
std::string get_label() {
    return compute();   // NRVO applies; no copy in practice
}
```

### M-03 Vector iterator/reference invalidation
```cpp
// WRONG
auto& front = vec[0];
vec.push_back(value);   // may reallocate → front is dangling
use(front);

// RIGHT — re-acquire after mutation
vec.push_back(value);
auto& front = vec[0];
use(front);

// OR — reserve first if size is known
vec.reserve(expected_size);
auto& front = vec[0];   // safe: no reallocation will happen
vec.push_back(value);
```

### M-04 std::string_view dangling
```cpp
// WRONG
std::string_view get_view() {
    std::string s = "hello";
    return s;   // s destroyed; view dangles
}

// WRONG (subtler)
std::string_view sv = std::string("hello");   // temporary destroyed immediately

// RIGHT
// string_view is a non-owning view — caller must ensure the string outlives it
std::string owner = "hello";
std::string_view sv = owner;   // safe: owner lives in same scope
```

### M-05 Missing Rule of Five
```cpp
// WRONG — custom destructor but no copy/move
class Buffer {
    double* data_;
public:
    ~Buffer() { delete[] data_; }
    // implicit copy does shallow copy → double free
};

// RIGHT
class Buffer {
    double* data_;
    size_t  size_;
public:
    ~Buffer()                          { delete[] data_; }
    Buffer(const Buffer& o)            : data_(new double[o.size_]), size_(o.size_)
                                         { std::copy(o.data_, o.data_+size_, data_); }
    Buffer& operator=(const Buffer& o) { Buffer tmp(o); std::swap(*this, tmp); return *this; }
    Buffer(Buffer&& o) noexcept        : data_(o.data_), size_(o.size_)
                                         { o.data_ = nullptr; o.size_ = 0; }
    Buffer& operator=(Buffer&& o) noexcept { std::swap(data_, o.data_);
                                             std::swap(size_, o.size_); return *this; }
};
// OR: just use std::vector<double> and get all five for free
```

---

## Undefined behaviour <a name="ub"></a>

### U-01 Signed integer overflow
```cpp
// WRONG — overflow is UB for signed int; compiler may optimise assuming it never happens
int a = INT_MAX;
int b = a + 1;   // UB

// RIGHT
int64_t a = INT_MAX;
int64_t b = a + 1;   // defined
// OR check before operating:
if (a > INT_MAX - 1) { /* handle */ }
```

### U-02 Type punning via reinterpret_cast
```cpp
// WRONG — strict aliasing violation, UB
float f = 3.14f;
int  bits = *reinterpret_cast<int*>(&f);

// RIGHT — use memcpy; compilers optimise it away
int bits;
std::memcpy(&bits, &f, sizeof(bits));
// C++20: std::bit_cast<int>(f)
```

### U-03 Shift by negative or oversized amount
```cpp
// WRONG
int x = 1;
int n = -1;
int y = x << n;   // UB if n < 0 or n >= 32

// RIGHT
assert(n >= 0 && n < 32);
int y = x << n;
```

### U-04 Null pointer dereference
```cpp
// WRONG
Widget* w = find_widget(id);
w->render();   // crashes if find returns nullptr

// RIGHT
Widget* w = find_widget(id);
if (!w) { throw std::runtime_error("widget not found: " + id); }
w->render();
// BETTER: return std::optional<Widget> or a reference
```

---

## Numerical / HPC <a name="numerical"></a>

### N-01 Float equality comparison
```cpp
// WRONG
if (result == 0.0) { ... }
if (a == b) { ... }

// RIGHT
constexpr double EPS = 1e-12;   // tune to problem scale
if (std::abs(result) < EPS) { ... }
if (std::abs(a - b) < EPS * std::max(std::abs(a), std::abs(b))) { ... }
```

### N-02 Accumulation in wrong precision
```cpp
// WRONG — catastrophic cancellation for large arrays
float sum = 0.0f;
for (float v : large_array) sum += v;

// RIGHT — use double accumulator
double sum = 0.0;
for (float v : large_array) sum += static_cast<double>(v);
```

### N-03 Integer division where real expected
```cpp
// WRONG
int N = 5, M = 2;
double ratio = N / M;   // truncates to 2.0

// RIGHT
double ratio = static_cast<double>(N) / M;
```

### N-04 Array index type for large data
```cpp
// WRONG — wraps around silently if n > 2^31
for (int i = 0; i < n; ++i) { data[i] = ...; }

// RIGHT
for (std::size_t i = 0; i < n; ++i) { data[i] = ...; }
// or use ptrdiff_t for signed arithmetic
```

### N-05 Magic literals for physical/mathematical constants
```cpp
// WRONG — unnamed, easy to mistype; 'E' shadows std::numbers::e in C++20
double E = 2.718281828;
double PI = 3.14159;

// RIGHT (C++17 and earlier) — named constexpr in a namespace
namespace constants {
    constexpr double euler     = 2.718281828459045;
    constexpr double pi        = 3.141592653589793;
    constexpr double boltzmann = 1.380649e-23;   // J/K
}

// RIGHT (C++20) — prefer std::numbers for standard mathematical constants
#include <numbers>
double circ = 2.0 * std::numbers::pi * radius;
double exp1 = std::numbers::e;
// std::numbers also provides: sqrt2, ln2, log2e, phi, etc.
```

---

## Standard library pitfalls <a name="stdlib"></a>

### S-01 Modifying container during range-for
```cpp
// WRONG — UB: iterator invalidated mid-loop
for (auto& item : vec) {
    if (should_remove(item)) vec.erase(...);
}

// RIGHT — erase-remove idiom
vec.erase(std::remove_if(vec.begin(), vec.end(), should_remove), vec.end());
// C++20: std::erase_if(vec, should_remove);
```

### S-02 std::map::operator[] creates default entry
```cpp
// WRONG — inserts a default value if key missing; hides bugs
if (map[key] == expected) { ... }

// RIGHT
auto it = map.find(key);
if (it != map.end() && it->second == expected) { ... }
```

### S-03 Narrowing conversion (silent)
```cpp
// WRONG — double silently truncated to float
double x = compute();
float  y = x;          // implicit narrowing

// RIGHT — make it explicit and document why it's safe
float y = static_cast<float>(x);   // precision loss acceptable here: range is [0,1]
```

---

## Design <a name="design"></a>

### D-01 Missing const on non-mutating method
```cpp
// WRONG
class Solver {
    double norm() { return std::sqrt(dot(*this, *this)); }   // should be const
};

// RIGHT
class Solver {
    double norm() const { return std::sqrt(dot(*this, *this)); }
};
```

### D-02 Raw pointer in public API (unclear ownership)
```cpp
// WRONG — caller can't tell if they own the pointer
double* get_data();

// RIGHT — be explicit
std::unique_ptr<double[]> take_data();   // transfer ownership
std::span<double>         view_data();   // non-owning view (C++20)
const double*             data() const;  // non-owning, document it
```

### D-03 Boolean flag argument
```cpp
// WRONG — what does true mean here?
void process(Matrix& m, bool transpose);

// RIGHT — use enum or two separate functions
enum class Layout { Normal, Transposed };
void process(Matrix& m, Layout layout);
```

---

## Binding layer — pybind11 <a name="binding"></a>

### B-01 Blocking call without GIL release
```cpp
// WRONG — holds GIL during heavy computation; blocks other Python threads
double compute_norm(py::array_t<double> arr) {
    return heavy_norm(arr);
}

// RIGHT
double compute_norm(py::array_t<double> arr) {
    py::gil_scoped_release release;
    return heavy_norm(arr);
}
```

### B-02 Non-contiguous array accepted silently
```cpp
// WRONG — accepts any array, including non-contiguous slices
m.def("dot", [](py::array_t<double> a, py::array_t<double> b) { ... });

// RIGHT — force C-contiguous layout at the boundary
m.def("dot", [](py::array_t<double, py::array::c_style | py::array::forcecast> a,
                py::array_t<double, py::array::c_style | py::array::forcecast> b) { ... });
```

### B-03 C++ exception escaping to Python
```cpp
// WRONG — custom type not derived from std::exception:
//   uncaught → Python SystemError or interpreter crash
struct MyError { std::string msg; };
m.def("solve", [](Matrix& m) {
    if (!m.is_valid()) throw MyError{"bad matrix"};
    return m.solve();
});

// ALSO WRONG — std::exception subclass, but undocumented in the Python API:
m.def("solve", [](Matrix& m) {
    return m.solve();  // may throw std::invalid_argument — caller doesn't know
});

// RIGHT — register custom types; document what can throw
py::register_exception<MyError>(m, "MyError");   // MyError → Python MyError

m.def("solve", [](Matrix& m) -> py::array_t<double> {
    return m.solve();
}, "Solve Ax=b.\n\nRaises ValueError if the matrix is singular.");
```
pybind11 automatically translates **only** `std::exception` subclasses:
`std::runtime_error` → `RuntimeError`, `std::invalid_argument` → `ValueError`, etc.
Any other C++ type thrown (including non-standard exceptions) produces a
`SystemError` or crashes the interpreter. Always use `py::register_exception`
for custom types and document raises in the docstring.

### B-04 Lifetime issue — Python object outliving C++ object
```cpp
// WRONG — Python View holds reference to C++ Buffer that may be destroyed
m.def("get_view", [](Buffer& buf) {
    return py::array_t<double>({buf.size()}, buf.data());
});

// RIGHT — keep Buffer alive as long as the array is alive
m.def("get_view", [](py::object buf_obj) {
    Buffer& buf = buf_obj.cast<Buffer&>();
    return py::array_t<double>({buf.size()}, buf.data(),
                               buf_obj);   // keep-alive: array holds ref to buf_obj
});
// OR use py::keep_alive<return, 1> in the def
```
