# Literature Search Guide

Used in Step 3 to plan and execute the literature search.
Covers accessible sources, search strategy, and how to handle paywalled content.

---

## Access tiers

**Caveat on citations pre-populated in this skill's `sota-*.md` reference
files**: those "Reference" entries were authored by an LLM, not copied
field-by-field from primary sources. An internal audit of this skill found
that author, year, and general topic were reliably correct, but exact journal
name, volume, and page numbers — and especially appended arXiv IDs — were
wrong in roughly a third of spot-checked cases (the arXiv ID is where
fabrication is most likely: it looks precise but is the easiest detail to
invent). **Before asserting any exact journal/volume/page/arXiv detail from
a `sota-*.md` file in a report, verify it with a search.** Treat the paper's
existence and general claim as reliable; treat the citation string's exact
punctuation as unverified until checked.

### Tier 1 — Fully accessible (fetch and read)
- **arXiv** (arxiv.org) — preprints in math, physics, CS, statistics
  Most numerical methods papers appear here 6–12 months before or after journal publication.
  Fetch the abstract page and the PDF.
- **JOSS** (joss.theoj.org) — Journal of Open Source Software, fully open
- **PLoS Computational Biology** — fully open
- **SIAM Open Access** — selected SIAM papers, growing list
- **Official documentation sites**: netlib.org, sundials.readthedocs.io,
  scipy.org, numpy.org, docs.petsc.org, fftw.org, suitesparse.com
- **GitHub repositories** with bundled papers (look for `paper.md` or `docs/`)
- **Zenodo** — open research deposits
- **HAL** (hal.science) — French open archive, many applied maths papers

### Tier 2 — Abstract accessible (read abstract, flag as partial)
- **DOI landing pages** — abstract and metadata only, full text behind paywall
- **IEEE Xplore** — abstract free, full text paywalled
- **ACM Digital Library** — abstract free
- **Web of Science / Scopus** — indexing only
- **Springer / Elsevier / Wiley** — almost always paywalled for full text
- **SIAM** journals — partially open, partly paywalled

### Tier 3 — Likely paywalled (do not claim to read)
- Nature, Science, Cell
- Journal of Computational Physics (Elsevier)
- Computer Methods in Applied Mechanics and Engineering (CMAME, Elsevier)
- Journal of Fluid Mechanics (Cambridge)
- SIAM Journal on Scientific Computing (mixed: some open, some not)
- Most commercial publisher content after 2015

**Rule**: if only the abstract is accessible, write:
`[abstract only] Title (Year). Abstract states: "…". Full text not verified.`

**Never** claim to have verified results from a paper you could only access
by abstract.

---

## Search strategy

### Step 1 — Internal knowledge first
Consult the relevant `sota-*.md` reference file. This avoids searching for
well-known results that are already in training data.
Document what is known and from what source (training data, specific reference).

### Step 2 — arXiv search for recent results
arXiv search URL: `https://arxiv.org/search/?query=<terms>&searchtype=all`
Also use web_search with: `<algorithm name> arXiv <year>`

Priority search terms per domain:
- Linear algebra: `"preconditioned iterative" OR "randomized algorithm" matrix`
- ODE: `"adaptive step size" OR "symplectic integrator" ODE solver benchmark`
- Optimisation: `"large-scale" nonlinear optimization benchmark comparison`
- PDE: `"high-order" scheme conservation law benchmark`

### Step 3 — Reference implementation documentation
Always check whether a SOTA library has been updated or superseded:
```
scipy release notes        : https://docs.scipy.org/doc/scipy/release/
LAPACK news                : https://www.netlib.org/lapack/
Sundials releases          : https://computing.llnl.gov/projects/sundials
PETSc changes              : https://petsc.org/release/changes/
```

### Step 4 — Benchmark papers
Search specifically for papers comparing methods on relevant problem classes:
`<domain> solver comparison benchmark <recent year>`

Reliable benchmark sources:
- SciPy benchmark suite (open on GitHub)
- Julia DifferentialEquations.jl benchmarks: diffeq.sciml.ai (fully open)
- Trilinos, PETSc, hypre comparison papers (typically on arXiv)

---

## Search query templates

Copy and adapt:

```
# General SOTA check
"<algorithm name>" state of the art <year> site:arxiv.org

# Library comparison
"<scipy function>" vs "<alternative>" benchmark comparison

# Recent advances
<problem class> "recent advances" <year> numerical method

# Open implementations
"<method name>" implementation open source github

# Physical domain specific
"<physics domain>" <algorithm class> solver comparison
```

---

## How to handle training cutoff

Query your own actual configured knowledge cutoff date — check your system
prompt or documentation. **Never hardcode a specific date in this process**:
this guide is used across model versions and deployments with different
cutoffs, and a hardcoded date will silently become wrong.

For any finding, document:
```
Internal knowledge date: <your actual configured cutoff>
Web search date: <today>
Delta note: <any post-cutoff results found>
```

If a method was emerging near the cutoff and active research continues:
- Search arXiv for papers from 2024–present
- Flag as `[rapidly evolving — verify independently]`
- Do NOT assert SOTA for cutting-edge methods without a recent open-access source

---

## Citing sources in the report

Format for each source cited:
```
[open]           arXiv:1808.06736 — Barnett et al. (2019), FINUFFT
                 Key result: NUFFT achieves O(n log n) with accuracy to 1e-14
[abstract only]  DOI:10.1016/j.jcp.2021.110345 — Author et al. (2021)
                 Abstract states: "proposed method is 3× faster than baseline"
                 [full text not verified]
[paywalled]      J. Fluid Mech. 900 (2020) — Title — not read
[training data]  Hairer & Wanner (1996), "Solving ODEs II" — well-established reference
                 [from training, pre-cutoff]
[doc site]       https://sundials.readthedocs.io — official Sundials IDA documentation
                 [accessed <date>]
```
