# SOTA Review Launch Prompts

> **Why every prompt below starts with `/sota-review`**: opencode can also
> load this skill automatically when a prompt matches its description, but
> auto-matching is a guess — it can miss, or pick a different skill (e.g.
> `code-review`) if descriptions overlap. `/sota-review` at the start of a
> message forces this skill specifically, every time.

---

> **Scope discipline**: SOTA review is expensive. Always target specific
> functions or modules — never a full project without filtering candidates first.

---

## Manual — specific function

```
/sota-review
Run a sota-review on the function <function_name> in <path/to/file>.
```

---

## Manual — module or directory

```
/sota-review
Run a sota-review on all algorithmic functions in <path/to/module/>.
Identify candidates first and ask for confirmation before analysing.
```

---

## Manual — known algorithm

```
/sota-review
Run a sota-review on <path/to/file> focusing on the time integration scheme.
I suspect it is a fixed-step RK4 applied to a Hamiltonian system.
```

---

## Cascade — from code-review finding

```
/sota-review
The code-review flagged <CPP-A-007> in <path/to/file> L<N> with [SOTA-CHECK].
Run a sota-review on that function.
```

---

## From AGENTS.md declarations

```
/sota-review
Run a sota-review on all targets declared in AGENTS.md under
"SOTA review targets".
```

---

## Full project scan (use sparingly)

```
/sota-review
Scan the project for algorithmic candidates using the detection patterns
in references/candidate-detection.md.
Present the candidate list for confirmation before running any analysis.
Do not start analysis without explicit confirmation.
```

---

## What the report includes

Every run produces `sota_report.md` at the project root with:
- Summary table (function, domain, category, severity)
- Per-finding: what is implemented, SOTA alternative, gap, sources consulted
- Concrete recommendation: adopt SOTA / add benchmark / add documentation
- Migration sketch or benchmark template for each HIGH/MEDIUM finding
- Access status for every source cited
