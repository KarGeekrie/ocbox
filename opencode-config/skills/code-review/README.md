# code-review

High-quality code review skill for opencode.
Python · C++ · Fortran — with pybind11 Python ↔ C++ binding layer support.

## Design rationale

Built on two empirical findings:

- **Tran & Kiela 2026** (arXiv:2604.02460): at equal token budget, single-agent
  matches or beats multi-agent. Architectural separation of passes does not add
  value; checklist-forced coverage does.
- **SWR-Bench 2025** (Zeng et al.): the +43% F1 gain comes from multiple
  independent runs of the same prompt + LLM aggregation, not from specialised
  sub-agents. The single-pass design here captures the checklist-coverage
  benefit without the token cost of multiple runs.

**Consequence**: one structured pass with language-specific checklists > two
separated passes at double the token cost.

## File layout

```
code-review/
├── SKILL.md                      ← skill definition
├── launch-review.md              ← copy-paste prompts
├── README.md
├── agents/
│   └── fix-applicator.md         ← applies one fix safely (revert on failure)
└── references/
    ├── checklist-python.md        ← correctness + design + scientific numpy + binding
    ├── checklist-cpp.md           ← correctness + design + performance + binding (C++)
    ├── checklist-fortran.md       ← correctness + design + performance (Fortran)
    ├── checklist-hpc.md           ← HPC performance (loaded when OpenMP/MPI/numpy detected)
    ├── patterns-hpc.md            ← HPC anti-patterns with corrections (loaded on demand)
    ├── severity-guide.md          ← CRITICAL/HIGH/MEDIUM/LOW calibration examples
    ├── patterns-python.md         ← anti-pattern catalogue, loaded on demand
    ├── patterns-cpp.md            ← anti-pattern catalogue, loaded on demand
    └── patterns-fortran.md        ← anti-pattern catalogue, loaded on demand
```

## Flow

```
Step 0  detect languages + detect HPC indicators + load checklists + read AGENTS.md
Step 1  single structured pass — correctness, design, performance, pybind11 binding
        (tags findings [SOTA-CHECK] when a hand-rolled numerical method is detected)
Step 2  test gap check (grep only, no extra code reading)
Step 2b documentation accuracy check (docstring vs. code, on CRITICAL/HIGH findings)
Step 3  write review_report.md
Step 4  apply automatable fixes with compile/test safety net (Python/C++/Fortran) —
        only when the running agent can edit; see "Scope and fix mode in ocbox" below
Step 5  print summary
```

## vs /review stock

| | `/review` stock | This skill |
|---|---|---|
| Language-specific checklists | ✗ | ✓ (Python · C++ · Fortran) |
| C++/Fortran domain knowledge | ✗ | ✓ (`implicit none`, kind suffix, pybind11 lifetime…) |
| HPC performance review | ✗ | ✓ (cache, vectorization, OpenMP, scientific Python) |
| Fix application | ✗ | ✓ with revert guard |
| Test gap detection | ✗ | ✓ |
| Documentation accuracy check | ✗ | ✓ (docstring vs. code, for CRITICAL/HIGH findings) |
| Algorithmic-currency tagging | ✗ | ✓ (`[SOTA-CHECK]` handoff to `sota-review`) |
| Token cost vs stock | 1× | ~1.2× (same pass + grep) |
| AGENTS.md | ✓ | ✓ |

## Installation

Ships as part of ocbox's team configuration — nothing to install by hand.
`opencode-config/skills/code-review/` is bind-mounted read-only into every
sandbox (and linked into the config directory under `--no-sandbox`) as
`~/.config/opencode/skills/code-review`; see the main
`opencode-config/skills/README.md` for how skill loading works.

**Optional — GitLab MR review mode only**: needs the `glab` CLI on the host,
authenticated against your own GitLab instance:

```bash
glab auth login --hostname <your-gitlab-host>
```

Everything else in this skill needs nothing beyond what ocbox already
provides.

## Scope and fix mode in ocbox

This skill separates two independent choices, both selected by the prompt
you launch it with (see `launch-review.md` for the exact templates):

- **Scope**: the whole project, a single file, a commit, a branch against a
  base branch, a GitLab MR, or a Tuleap/other-tracker PR (Step 0e resolves
  commit/branch scope; the launch prompts drive the MR/PR modes).
- **Fix mode**: report-only, apply fixes directly to the working tree, or
  apply fixes on a dedicated branch and leave the original untouched.

The fix mode you can actually get depends on which agent runs the skill:
`review` (`opencode-config/agents/review.md`) denies the edit tool, so it
always ends up report-only regardless of what the prompt asks for; `build`
has full edit/bash access and can apply fixes or work on a dedicated branch.
See `opencode-config/agents/review.md` for the reasoning.

## First use — project setup

Run `/init` in opencode at the root of the project to review. It generates an
`AGENTS.md` with project-specific context that the skill reads before every run.
Without it the skill falls back to generic checklists — which still works, but
AGENTS.md gives better-targeted findings (architecture rules, focus areas,
severity overrides, files off-limits for auto-fix).

## Finding IDs

`<LANG>-<NNN>` — e.g. `PY-001`, `CPP-003`, `F90-007`, `TST-001`

## Integration with sota-review

This skill checks correctness, design, and performance - not whether the
*algorithm* implemented is the current state of the art. When it recognises
a hand-rolled implementation of a well-known numerical method (manual matrix
inversion, fixed-step ODE loop, unaccelerated iterative solver, etc.), it
tags the finding `[SOTA-CHECK]` with a `domain_hint` field. See the
"SOTA-CHECK handoff" section in `SKILL.md` for the full trigger list.

This is the only mechanism that connects the two skills - `sota-review`
never runs automatically; the person reviews the tagged findings and
explicitly asks for a SOTA review as a follow-up (prompt in
`launch-review.md` → "Follow-up - hand a SOTA-CHECK finding to sota-review").
