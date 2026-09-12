# SOTA — Neutronics, Deterministic Methods

Reference for Step 2 and Step 4.
Domain: neutron transport and diffusion, multigroup energy treatment,
eigenvalue solvers for criticality, spatial discretisation, acceleration.
Covers codes like DRAGON5, DONJON5, OpenMOC, OpenSn.

---

## Table of contents
- [Problem hierarchy](#hierarchy)
- [Multigroup energy treatment](#multigroup)
- [Diffusion solvers](#diffusion)
- [Transport — discrete ordinates (Sn)](#sn)
- [Transport — method of characteristics (MOC)](#moc)
- [Eigenvalue solvers for criticality (k-eff)](#eigenvalue)
- [Acceleration schemes](#acceleration)
- [Common SOTA gaps](#gaps)

---

## Problem hierarchy <a name="hierarchy"></a>

The neutron transport equation has multiple levels of approximation:

```
Exact transport (Boltzmann)
    ↓ P1/SP3/SPN approximation
Multi-group diffusion (most lattice codes)
    ↓ homogenisation / condensation
Few-group nodal diffusion (core codes like DONJON)
```

**SOTA gap signal**: using a lower level of approximation (diffusion) in a
region where transport effects are significant (near reflectors, strong absorbers,
control rods) without documented justification. Transport-diffusion equivalence
should be explicitly validated.

---

## Multigroup energy treatment <a name="multigroup"></a>

**SOTA**: self-shielding via subgroup method or probability tables for
resolved resonance range. Unresolved resonance range via probability tables.

| Method | SOTA? | Notes |
|---|---|---|
| Narrow resonance (NR) | Baseline | Overestimates shielding for wide resonances |
| Wide resonance (WR) | Better | More accurate for U-238 first resonance |
| Subgroup method | SOTA | Used in DRAGON5; exact for self-shielding |
| Probability tables | SOTA | Unresolved range; used in NJOY, CALENDF |
| Stoker-Weiss (IR approximation) | SOTA baseline | Intermediate resonance |

**SOTA gap**: using simplified NR approximation where subgroup data is
available in the library — leads to errors in fuel temperature coefficient
calculations (Doppler effect).

**Energy group structure**: fine-group (172-group VITAMIN-J, 281-group,
1968-group XMAS) for lattice calculations; few-group (2-8 groups) after
condensation for core calculations. Flag if a coarse group structure is used
for lattice-level calculations.

---

## Diffusion solvers <a name="diffusion"></a>

The multigroup diffusion equation discretised on a mesh gives a linear system
or eigenvalue problem per energy group (with group-to-group coupling).

### Spatial discretisation

| Scheme | Order | SOTA? | Use case |
|---|---|---|---|
| Finite difference (FD) | 2 | Baseline | Structured mesh, simple |
| Finite element (FEM) | 2-4 | Yes | Unstructured mesh |
| Nodal expansion method (NEM) | ~4 | SOTA | Hex/square assemblies, fast |
| Analytic nodal method (ANM) | ~6 | SOTA | 2-group, very fast |
| Coarse mesh finite difference (CMFD) | 2 | SOTA as accelerator | See acceleration |

**SOTA gap**: fine-mesh finite difference for full-core diffusion where
nodal methods (NEM, INEN) are available — 10-100× slower for same accuracy.

### Linear system solution

Within each outer iteration, the within-group diffusion equation is:
(-∇·D∇ + Σ_a) φ_g = S_g (source from other groups + fission)

This is an elliptic PDE → use AMG-preconditioned CG (see `sota-multigrid.md`).

**SOTA gap**: source iteration (Gauss-Seidel over spatial unknowns) for
within-group equations without acceleration — O(N²) convergence for fine meshes.
Use Krylov + AMG preconditioning.

---

## Transport — discrete ordinates (Sn) <a name="sn"></a>

### Angular discretisation

| Method | SOTA? | Notes |
|---|---|---|
| Gauss-Legendre-Chebyshev (GLC) | SOTA | Symmetric, positive weights, level-symmetric |
| Level-symmetric (LQn) | SOTA | Standard in PARTISN, Denovo |
| Simplified SPN | SOTA for reactor | Much cheaper than full Sn; good approximation |

### Spatial sweep

**SOTA**: Koch-Baker-Alcouffe (KBA) parallel sweep for distributed memory.
For single-node: standard diamond difference or step characteristic.

| Scheme | Order | SOTA? | Notes |
|---|---|---|---|
| Step characteristic | 1 | Baseline | Positive, monotone but diffusive |
| Diamond difference (DD) | 2 | SOTA baseline | May give negative fluxes |
| Linear discontinuous FEM (LDFEM) | 2 | SOTA | Positive, accurate |
| Exponential discontinuous | 2 | SOTA for optically thick | |

**SOTA gap**: step characteristic in optically thin regions (streaming) —
excessive numerical diffusion. Use linear discontinuous FEM.

### Source iteration acceleration

Plain source iteration converges with spectral radius ρ ≈ c = Σ_s/Σ_t (the
scattering ratio) for optically thick, diffusive problems — this is the
standard result (Adams & Larsen, "Fast iterative methods for discrete-ordinates
particle transport calculations", Prog. Nucl. Energy 40(1):3-159, 2002,
DOI:10.1016/S0149-1970(01)00023-3 — verified). For
thick problems, ρ → 1 and convergence becomes arbitrarily slow.

**SOTA acceleration**:
- DSA (Diffusion Synthetic Acceleration): SOTA for homogeneous/weakly heterogeneous
- CMFD (Coarse Mesh Finite Difference): SOTA for heterogeneous problems
- NDA (Nonlinear Diffusion Acceleration): SOTA for highly heterogeneous

**SOTA gap**: source iteration without DSA/CMFD on a problem with large
scattering ratios (c = Σ_s/Σ_t > 0.9) — may require thousands of iterations.

---

## Transport — method of characteristics (MOC) <a name="moc"></a>

MOC integrates along characteristic lines through the geometry. SOTA for
2D lattice-level transport with explicit pin-cell geometry.

### SOTA implementations
- **OpenMOC** (MIT): open source, GPU-capable
- **DRAGON5** (Polytechnique Montreal): open source, mature
- **MPACT** (Michigan/ORNL): production, multi-level MOC

### SOTA algorithmic choices

**Ray density**: 20-50 azimuthal angles + 3-5 polar angles for 2D MOC is
SOTA for LWR pin-cell accuracy. Flag if ray density appears insufficient
(< 8 azimuthal) without documented convergence study.

**Cyclic tracking**: MOC with modular ray tracing + cyclic boundary conditions
is SOTA for assembly-level calculations — avoids remapping rays at boundaries.

**SOTA gap for MOC acceleration**: unaccelerated MOC (pure inner iterations)
on a multi-group problem without CMFD acceleration. CMFD reduces outer
iterations by 5-20× for typical LWR problems.

**Memory**: full 3D MOC stores tracks × groups × unknowns. For large 3D
problems, 2D/1D method (2D MOC + 1D axial diffusion) is the current SOTA
balance between accuracy and cost.

---

## Eigenvalue solvers for criticality (k-eff) <a name="eigenvalue"></a>

The criticality problem is a generalised eigenvalue: A φ = (1/k) B φ where
A = transport/diffusion operator, B = fission source operator.

| Method | SOTA? | Notes |
|---|---|---|
| Power iteration (PI) | Baseline | Converges as ratio of dominant eigenvalues |
| Wielandt shift | SOTA | Shifts spectrum, dramatically accelerates PI |
| Arnoldi / GMRES-based | SOTA | For k closest to 1; used in JFNK frameworks |
| JFNK (Jacobian-Free Newton-Krylov) | SOTA | Couples fission and transport; faster |
| Krylov-Schur | SOTA for multiple modes | When α-modes or prompt modes needed |

**SOTA gap**: unaccelerated power iteration without Wielandt shift — convergence
rate ρ = k₁/k₀ (ratio of first to dominant eigenvalue) can be very close to 1
for nearly-critical systems or systems with control rods.

```
Wielandt shift: replace k with μ = k - σ where σ ≈ k_eff_estimated
→ New convergence rate: (k₁-σ)/(k₀-σ) ≪ k₁/k₀
SOTA: σ chosen adaptively from Rayleigh quotient estimate
```

**Alpha eigenvalue** (time-dependent criticality): requires specialised solvers
(shift-invert with complex arithmetic). Flag if power iteration is used for
α-mode calculations.

---

## Acceleration schemes <a name="acceleration"></a>

### CMFD (Coarse Mesh Finite Difference)

SOTA acceleration for both MOC and Sn. Solves a coarse-mesh diffusion
problem at the end of each transport sweep to accelerate spatial flux
convergence.

**Two-level CMFD**:
1. Fine transport sweep (MOC or Sn)
2. Compute homogenised CMFD coefficients from transport solution
3. Solve coarse-mesh diffusion problem (fast — small matrix)
4. Use CMFD flux as improved source for next transport sweep

**SOTA gap**: MOC or Sn without CMFD on a multigroup problem — 10-50× slower
convergence for problems with strong spatial heterogeneity.

**Nonlinear CMFD (pCMFD)**: uses a nonlinear diffusion coefficient correction
(Kopp et al.). SOTA for heterogeneous problems where standard CMFD diverges.

---

## Common SOTA gaps <a name="gaps"></a>

1. **Manual LU inversion of the within-group matrix** — use CG + AMG
2. **Gauss-Seidel source iteration without DSA/CMFD** — for c > 0.9, slow
3. **Fixed-step power iteration without Wielandt shift** — for nearly-critical
4. **NR self-shielding in resolved resonance range** — use subgroup method
5. **Step characteristic in optically thin regions** — use LDFEM
6. **Full 3D MOC without 2D/1D approximation option** — memory and cost

**Reference (open access)**:
Hébert, "Applied Reactor Physics", 3rd ed., Presses Polytechnique (2020).
Partially available at: https://www.polymtl.ca/phyapp/
Smith, "Nodal diffusion methods: history, insights and future prospects" (2017).
Prog. Nucl. Energy 101:13-31. Available on ResearchGate (check access).