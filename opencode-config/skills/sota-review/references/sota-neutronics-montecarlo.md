# SOTA — Neutronics, Monte Carlo Methods

Reference for Step 2 and Step 4.
Domain: continuous-energy Monte Carlo transport, criticality calculations,
variance reduction, tallies, Doppler broadening. Primary reference code:
OpenMC (open source). Also relevant: Serpent 2, MCNP (closed).

---

## Table of contents
- [Random number generation](#rng)
- [Continuous energy vs multigroup](#energy)
- [Criticality calculations (k-eff)](#criticality)
- [Variance reduction](#vr)
- [On-the-fly Doppler broadening](#doppler)
- [Tallies and statistics](#tallies)
- [Parallel scaling](#parallel)
- [Common SOTA gaps](#gaps)

---

## Random number generation <a name="rng"></a>

The RNG is the foundation of every MC simulation. Choice matters for:
- Statistical quality (period length, uniformity)
- Performance (modern CPUs can generate 10⁸/s)
- Reproducibility in parallel (particle-wise seed assignment)

| Generator | Period | SOTA? | Notes |
|---|---|---|---|
| LCG (classic) | 2⁶³ | Baseline | Still used in legacy codes; acceptable |
| MT19937 (Mersenne Twister) | 2¹⁹⁹³⁷ | No | Slow, large state; fails some tests |
| PCG (Permuted Congruential) | 2¹²⁸ | **SOTA** | Fast, small state, excellent quality |
| Xoshiro256** | 2²⁵⁶ | SOTA | Used in Julia; very fast |
| Hash-based (multiply-with-carry) | — | SOTA | OpenMC default; particle-wise seeding |

**OpenMC approach (SOTA)**: hash-based particle seed derived from
`particle_id × stride + global_seed`. Ensures reproducibility regardless
of parallel decomposition and allows rerunning individual particles.

**SOTA gap**: MT19937 in a parallel MC code — thread-safety requires one
generator per thread (large memory), and k-way seeding is non-trivial.
Use PCG or hash-based approach instead.

**Reference**: O'Neill, "PCG: A Family of Simple Fast Space-Efficient
Statistically Good Algorithms for Random Number Generation" (2014).
Free: https://www.pcg-random.org/pdf/hmc-cs-2014-0905.pdf

---

## Continuous energy vs multigroup <a name="energy"></a>

| Approach | Accuracy | Cost | SOTA use case |
|---|---|---|---|
| Continuous energy (CE-MC) | Reference | High | Validation, precise spectra |
| Windowed multipole (WMP) | ≈ CE | Lower | On-the-fly Doppler; OpenMC default |
| Multigroup MC | Lower | ~10× faster | Shielding, scoping, coupling to deterministic |
| Hybrid CE + MG | — | Intermediate | Variance reduction via MG adjoint |

**SOTA for neutronics design calculations**: CE-MC with WMP Doppler broadening.
Multigroup MC is acceptable for shielding studies but should not be used
for reactivity coefficient calculations where resonance treatment matters.

**SOTA gap**: multigroup cross sections without self-shielding correction in
MC — introduces the same resonance treatment error as in deterministic codes.

---

## Criticality calculations (k-eff) <a name="criticality"></a>

### Fission source convergence

MC criticality requires converging both k-eff AND the fission source distribution
before beginning active batches. Poor convergence leads to biased statistics.

| Method | SOTA? | Notes |
|---|---|---|
| Standard power iteration (batch cycles) | Baseline | Monitor Shannon entropy |
| Wielandt method for MC | SOTA | Accelerates fission source convergence; fewer inactive batches |
| CMFD-accelerated MC | SOTA | Couples MC with coarse-mesh diffusion for source convergence |

**SOTA convergence diagnostics**:
- Shannon entropy H of fission source distribution must plateau before active batches
- Slope of k-eff running average must flatten
- Gelman-Rubin diagnostic (R̂ < 1.1) for multiple independent chains

**SOTA gap**: fixed number of inactive batches without Shannon entropy monitoring —
leads to biased k-eff estimate if the source has not converged.

### Uncertainty estimation

**SOTA**: batch statistics (central limit theorem over batches).
Inter-batch correlation must be accounted for when batches are strongly
correlated. Use:
- Minimum batch size ≥ mean free path / system size × several generations
- Autocorrelation analysis to verify statistical independence
- Multiple independent runs + combined estimate

**SOTA gap**: under-reporting uncertainty by ignoring batch-to-batch
correlation (treating all histories as independent when c ≈ 0).

---

## Variance reduction <a name="vr"></a>

For deep-penetration shielding and source-detector problems where analog MC
is inefficient (most histories contribute nothing to the tally).

### Methods

| Method | SOTA? | Use case |
|---|---|---|
| Geometry splitting + Russian roulette | Baseline | Manual, problem-specific |
| Weight windows | SOTA baseline | Automatically set importances |
| CADIS (Consistent Adjoint-Driven IS) | **SOTA** | Single detector response |
| FW-CADIS (Forward-Weighted CADIS) | **SOTA** | Multiple tallies, global |
| Hybrid MC/deterministic | SOTA | FW-CADIS uses Sn adjoint flux |

**CADIS workflow**:
1. Run fast Sn/diffusion calculation to get adjoint flux φ†(r,E)
2. Set weight windows and source biasing from φ†
3. Run MC with biased source → variance reduction factors of 10³-10⁶

**SOTA gap**: analog MC for deep-penetration problems (> 10 mean free paths
of attenuation) without variance reduction. Variance ∝ exp(2μx) → exponential
explosion of computational cost.

**Tools**: SCALE/MAVRIC implements FW-CADIS (closed source).
OpenMC has weight windows support (open); FW-CADIS setup requires external Sn solve.

**Reference**: Wagner & Haghighat, "Automated Variance Reduction of Monte Carlo
Shielding Calculations Using the Discrete Ordinates Adjoint Function" (1998).
Nucl. Sci. Eng. 128:186-208. DOI:10.13182/NSE98-2. (Original CADIS method)
Wagner, Peplow & Mosher, "FW-CADIS Method for Global and Regional Variance
Reduction of Monte Carlo Radiation Transport Calculations" (2014).
Nucl. Sci. Eng. 176:37-57. DOI:10.13182/NSE12-33. (Original FW-CADIS method)
Peplow, "Monte Carlo Shielding Analysis Capabilities with MAVRIC" (2011).
Nucl. Technol. 174:289-313. DOI:10.13182/NT174-289. (MAVRIC implementation —
reports FW-CADIS figure-of-merit gains of ~275× to ~21,000× on ITER shielding
cases, consistent with the order-of-magnitude range stated above)

---

## On-the-fly Doppler broadening <a name="doppler"></a>

Cross sections depend on fuel temperature (Doppler effect). Storing cross-section
tables at every temperature is memory-intensive.

| Method | SOTA? | Memory | Notes |
|---|---|---|---|
| Tabulated at fixed temperatures | Baseline | High | Linear interpolation between T |
| Windowed multipole (WMP) | **SOTA** | Low | Exact broadening at any T; OpenMC default. Current implementations assume no inelastic scattering in the resolved resonance region — usually true, not always (per OpenMC's own documentation) |
| Free-gas kernel (FGK) | SOTA for thermal | — | S(α,β) tables for thermal scattering |
| 0K + target motion sampling | SOTA | Very low | Exact, stochastic; slower |

**SOTA gap**: tabulated cross sections interpolated between coarse temperature
grid (e.g., 300K and 600K only) for fuel temperature coefficients — introduces
interpolation error in reactivity feedback calculations.
Use WMP (available in ENDF/B-VIII.0 and JEFF-3.3 libraries), subject to the
inelastic-scattering caveat above — verify it does not apply to the isotopes
and energy range of the case being analysed.

**Reference**: Josey, Ducru, Forget & Smith, "Windowed Multipole for Cross
Section Doppler Broadening" (2016). J. Comput. Phys. 307:715-727.
DOI:10.1016/j.jcp.2015.08.013. (No arXiv preprint found for this paper —
do not cite one.)

---

## Tallies and statistics <a name="tallies"></a>

**SOTA tally estimators**:

| Estimator | Variance | SOTA use case |
|---|---|---|
| Collision estimator | High in void | Flux in material regions |
| Track length estimator | SOTA for flux | Standard; low variance |
| Analog (absorption) | Highest | Capture rates in thin regions |
| Next-event estimator | SOTA for point detector | Flux at specific point; zero-variance limit |

**SOTA for reaction rates**: track-length estimator combined with
flux-to-reaction rate conversion. Do not use collision estimator in
regions with significant void fractions.

**Statistical checks** (mandatory for production results):
- Relative error < 10% for integral quantities, < 1% for safety parameters
- FOM (Figure of Merit = 1/(R² × T)) should be constant with increasing histories
- VOV (Variance of the Variance) < 0.1 for converged tally

---

## Parallel scaling <a name="parallel"></a>

**SOTA**: embarrassingly parallel over histories within each batch.
Communication only at end of batch: k-eff estimate, fission source bank update.

| Decomposition | SOTA? | Notes |
|---|---|---|
| History decomposition | SOTA | Each MPI rank runs N/P histories; minimal comm |
| Domain decomposition | Emerging | Needed for very large geometries > RAM |
| GPU offload | SOTA (2023+) | OpenMC GPU branch; Shift (ORNL); 10-50× speedup |

**OpenMC parallel SOTA**: history decomposition with asynchronous fission
bank sharing. Scales to thousands of cores.

**SOTA gap**: MC code with global synchronisation at every collision — scales
to ~10 cores maximum. Should synchronise only at batch boundaries.

---

## Common SOTA gaps <a name="gaps"></a>

1. **Mersenne Twister without per-thread seeding** — non-reproducible, potential correlation
2. **Fixed inactive batches without Shannon entropy check** — biased k-eff
3. **Analog MC for deep penetration (> 10 mfp)** — use CADIS/FW-CADIS
4. **Tabulated XS at coarse temperature grid** — use WMP for Doppler feedback
5. **Collision estimator in void regions** — use track-length estimator
6. **Batch statistics without autocorrelation check** — underestimated variance

**Reference (open access)**:
Romano et al., "OpenMC: A State-of-the-Art Monte Carlo Code for Research
and Development" (2015). Ann. Nucl. Energy 82:90-97.
DOI:10.1016/j.anucene.2014.07.048.
Leppanen et al., "The Serpent Monte Carlo code: Status, development and
applications in 2013" (2015). Ann. Nucl. Energy 82:142-150. (Check access)
