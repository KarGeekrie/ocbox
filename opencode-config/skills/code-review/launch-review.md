# Review Launch Prompts

> **When to use this skill vs `/review` stock**
> For a quick diff-only check on a small change (pre-commit, single-function edit),
> opencode's built-in `/review` is lighter and sufficient.
> Use this skill for full audits: language-specific checklists, test gap detection,
> and automated fix application across Python, C++, and Fortran projects.

> **Why every prompt below starts with `/code-review`**: opencode can also
> load this skill automatically when a prompt matches its description, but
> auto-matching is a guess — it can miss, or pick a different skill if
> descriptions overlap. `/code-review` at the start of a message forces this
> skill specifically, every time. That's what a copy-paste launch prompt
> should do reliably, so all prompts here use it.

> **Fix mode in ocbox**: prompts below say "apply automatable fixes" or "do
> NOT apply fixes". Whether that request can actually be honored depends on
> which agent you're running it from — `review` is read-only (edit denied)
> and always reports instead of fixing, however the prompt is worded; `build`
> can do either. See `opencode-config/agents/review.md`.

---

## Report format (all prompts)

Every prompt below produces `review_report.md` at the project root.
The report is designed to be pasted directly into a PR review and includes:
- Executive summary (3–5 sentences, overall quality + top issues)
- All findings with file, line, quoted code, explanation, and fix recommendation
- Severity breakdown (CRITICAL / HIGH / MEDIUM / LOW)
- Test gaps for every unfixed CRITICAL and HIGH finding
- "Not flagged" section explaining suspicious-but-correct patterns
- Automated fixes applied (table of ID / file / change)

---

## Standard — full review + auto-fix

```
/code-review
Review the code in this repository.
Project root: .
Apply automatable fixes when done.
Write the full review_report.md.
```

---

## Read-only — review without touching the code

```
/code-review
Review the code in this repository.
Project root: .
Do NOT apply any fixes.
Write the full review_report.md.
```

---

## Single file

```
/code-review
Review only <path/to/file>.
Apply automatable fixes.
Write the full review_report.md.
```

---

## Binding layer focus

```
/code-review
Review the pybind11 binding layer in this project.
Focus on the Python ↔ C++ boundary only:
array layout, ownership, GIL, type widths, exception propagation.
Do NOT apply fixes.
Write the full review_report.md.
```

---

## Correctness only — fast pre-commit

```
/code-review
Check only correctness issues across the entire project.
Skip design checks.
Apply automatable fixes.
Write the full review_report.md.
```

---

## Post-refactor

```
/code-review
I just refactored <file1> and <file2>.
Review only these two files for correctness and design regressions
introduced by the refactor.
Apply automatable fixes.
Write the full review_report.md.
```

---

## HPC / performance review

```
/code-review
Review the code in this repository.
Project root: .
Focus on performance: memory access patterns, cache efficiency, vectorization
inhibitors, OpenMP correctness, and scientific Python bottlenecks.
Do NOT apply fixes — findings may require architectural decisions.
Write the full review_report.md.
```

---

## Follow-up — hand a SOTA-CHECK finding to sota-review

> Use this after a standard review reports findings tagged `[SOTA-CHECK]`.
> This skill flags the pattern; it does not judge algorithmic currency —
> that assessment is `sota-review`'s job, done as a separate, explicit step.
> Note the `/sota-review` prefix here, not `/code-review` — this prompt
> hands off to the *other* skill.

```
/sota-review
The code-review report flagged <ID> in <path/to/file> L<N> with [SOTA-CHECK]
(domain_hint: <domain>). Run a sota-review on that function.
```

---

## GitLab MR review

> **Prerequisite**: `glab auth status` must show authenticated against your
> GitLab instance (`glab auth login --hostname <your-gitlab-host>`).
> The repository must be a GitLab remote (`git remote -v` to verify).

```
/code-review

Use the `code-review` skill to review this GitLab merge request: <MR_ID>

Run these steps in order:

1. Verify authentication:
   glab auth status

2. Fetch MR metadata to get the target and source branches:
   glab mr list
   Find the MR by its number (e.g., `!3` for MR 3). The output looks like:
     !3      <group>/<project>!3      title (master) ← (feature/some-branch)
   Extract branches from this format: `target_branch ← source_branch`
   Store them as: TARGET_BRANCH=<target> and SOURCE_BRANCH=<source>
   Do NOT use `glab mr view` — it does not show branch info on this glab version.
   (Note: `glab mr show` is an alias for `view`. Do NOT use `--json` — not supported. Do NOT use `glab mr info` — does not exist.)
   If you ever need to use the REST API instead, use:
     glab api "projects/<namespace%2Fproject>/merge_requests/<MR_ID>"
   The response fields are `target_branch` (not `target_branch_name`) and `source_branch`.

3. Checkout the MR branch locally:
   git stash        # save any local changes first
   git fetch origin
   If already on the correct branch (git branch --show-current matches $SOURCE_BRANCH), skip checkout.
   Otherwise:
     git checkout "$SOURCE_BRANCH" 2>/dev/null || git checkout -b "$SOURCE_BRANCH" "origin/$SOURCE_BRANCH" 2>/dev/null || git checkout "$SOURCE_BRANCH"

4. List only the files changed in this MR:
   git diff origin/<target_branch>...HEAD --name-only
   View the diff:
   git diff origin/<target_branch>...HEAD -- <file>
   (Note: `glab mr diff` shows the full diff but does not support `--stat`.)

5. Review ONLY the files from step 4.
   Project root: .
   Do NOT apply fixes automatically.
   Instead, list every fix as a "Suggested fix" block in review_report.md
   with the exact before/after code so the MR author can apply it.
   Write the full review_report.md.

6. Post the report as an MR comment:
   glab mr note create <MR_ID> --message "$(cat review_report.md)"
   (Note: `glab mr note -m` is deprecated. Use `glab mr note create` instead.)
   (Note: Do NOT use `-F` — not supported.)

7. Return to your original branch:
   git checkout -
   git stash pop    # restore local changes if any
```

> **Note on comment length**: GitLab MR comments support up to ~1 MB.
> If `review_report.md` exceeds ~500 lines, consider posting only the
> executive summary + CRITICAL/HIGH findings and attaching the full report
> as a file upload or wiki page.

> **Note on fixes**: fixes are NOT applied to the branch automatically.
> Each fix appears in the report as a before/after diff for the MR author
> to review and apply. This preserves the author's ownership of the branch.

---

## GitLab MR review — fixes on a dedicated branch

> **Prerequisite**: `glab auth status` must show authenticated against your
> GitLab instance. The repository must be a GitLab remote (`git remote -v`
> to verify).

```
/code-review

Use the `code-review` skill to review this GitLab merge request: <MR_ID>

Apply automatable fixes to a dedicated review branch.

Run these steps in order:

1. Verify authentication:
   glab auth status

2. Fetch MR metadata to get the target and source branches:
   glab mr list
   Find the MR by its number (e.g., `!3` for MR 3). The output looks like:
     !3      <group>/<project>!3      title (master) ← (feature/some-branch)
   Extract branches from this format: `target_branch ← source_branch`
   Store them as: TARGET_BRANCH=<target> and SOURCE_BRANCH=<source>
   Do NOT use `glab mr view` — it does not show branch info on this glab version.
   (Note: `glab mr show` is an alias for `view`. Do NOT use `--json` — not supported. Do NOT use `glab mr info` — does not exist.)
   If you ever need to use the REST API instead, use:
     glab api "projects/<namespace%2Fproject>/merge_requests/<MR_ID>"
   The response fields are `target_branch` (not `target_branch_name`) and `source_branch`.

3. Checkout the MR branch locally:
   git stash        # save any local changes first
   git fetch origin
   If already on the correct branch (git branch --show-current matches $SOURCE_BRANCH), skip checkout.
   Otherwise:
     git checkout "$SOURCE_BRANCH" 2>/dev/null || git checkout -b "$SOURCE_BRANCH" "origin/$SOURCE_BRANCH" 2>/dev/null || git checkout "$SOURCE_BRANCH"

4. List only the files changed in this MR:
   git diff origin/<target_branch>...HEAD --name-only
   View the diff:
   git diff origin/<target_branch>...HEAD -- <file>

5. Create a review-fixes branch from the MR branch:
   git checkout -b review-fixes/mr-<MR_ID>

6. Review ONLY the files from step 4.
   Project root: .
   Apply ALL automatable fixes directly to the working tree.
   Write the full review_report.md.

7. Commit the fixes and the report:
   git add -A
   git commit -m "code-review: automated fixes for MR <MR_ID>

   Applied by code-review skill. Each fix is tagged with its finding ID
   (review-fix <ID>) in the source. Review individually before merging.
   See review_report.md for the full findings and manual items."

8. Push the fix branch:
   git push origin review-fixes/mr-<MR_ID>

9. Post a comment on the MR with the report + branch reference:
   glab mr note create <MR_ID> --message "$(cat review_report.md)"
   (Note: `glab mr note -m` is deprecated. Use `glab mr note create` instead.)
   (Note: Do NOT use `-F` — not supported.)

10. Return to your original branch:
    git checkout -
    git stash pop    # restore local changes if any
```

> **What the MR author sees**:
> - A comment with the full `review_report.md` (all findings, severities, test gaps)
> - A ready-to-use branch `review-fixes/mr-<MR_ID>` with one commit per
>   automatable fix, each tagged `# review-fix <ID>` in the source
> - Manual findings remain in the report for the author to handle

---

## Tuleap PR review

> **Prerequisite**: `./identification.md` must contain a valid Tuleap access
> key. The repository must be cloned locally with `origin` pointing to the
> Tuleap project. Replace `<tuleap-host>` below with your Tuleap instance's
> hostname.

```
/code-review

Use the `code-review` skill to review this Tuleap pull request: <PR_ID>

Run these steps in order:

1. Read the Tuleap access key from ./identification.md:
    KEY=$(grep -oP 'Tuleap key\s*:\s*\K.*' ./identification.md | tr -d '[:space:]')
    curl -s -H "X-Auth-AccessKey: $KEY" \
      "https://<tuleap-host>/api/v1/pull_requests/<PR_ID>"
    Extract the target branch from the response: `"branch_dest":"main"`
    Store it as: TARGET_BRANCH=<extracted_name>
    Verify the response is valid (HTTP 200).

2. Verify the repository is cloned and the correct branch is checked out:
    git status --short
    git branch --show-current
    (You are already inside the cloned repo directory.)

3. Analyse the diff against the target branch:
    git log --oneline origin/<target_branch>..HEAD
    git diff origin/<target_branch>..HEAD --stat
    git diff origin/<target_branch>..HEAD -- <changed_files>

4. Fetch existing comments for context:
    curl -s -H "X-Auth-AccessKey: $KEY" \
      "https://<tuleap-host>/api/v1/pull_requests/<PR_ID>/comments"

5. Review ONLY the changed files from step 3.
   Project root: .
   Do NOT apply fixes automatically.
   Instead, list every fix as a "Suggested fix" block in review_report.md
   with the exact before/after code so the PR author can apply it.
   Write the full review_report.md.

6. Post the report as a PR comment:
    Use python3 to safely encode the content as JSON (avoids control character errors):
    CONTENT=$(python3 -c "import json,sys; print(json.dumps({'content': sys.stdin.read()}))" < review_report.md)
    curl -s -H "X-Auth-AccessKey: $KEY" \
         -H "Content-Type: application/json" \
         -d "$CONTENT" \
         "https://<tuleap-host>/api/v1/pull_requests/<PR_ID>/comments"
    (Do NOT use `$(cat review_report.md)` directly in the curl payload — it will fail with control character errors.)
```

## Tuleap PR review — fixes on a dedicated branch

> **Prerequisite**: `./identification.md` must contain a valid Tuleap access
> key. The repository must be cloned locally with `origin` pointing to the
> Tuleap project. Replace `<tuleap-host>` below with your Tuleap instance's
> hostname.

```
/code-review

Use the `code-review` skill to review this Tuleap pull request: <PR_ID>

Apply automatable fixes to a dedicated review branch.

Run these steps in order:

1. Read the Tuleap access key from ./identification.md:
    KEY=$(grep -oP 'Tuleap key\s*:\s*\K.*' ./identification.md | tr -d '[:space:]')
    curl -s -H "X-Auth-AccessKey: $KEY" \
      "https://<tuleap-host>/api/v1/pull_requests/<PR_ID>"
    Extract the target branch from the response: `"branch_dest":"main"`
    Store it as: TARGET_BRANCH=<extracted_name>
    Verify the response is valid (HTTP 200).

2. Verify the repository is cloned and the correct branch is checked out:
    git status --short
    git branch --show-current
    (You are already inside the cloned repo directory.)

3. Checkout the PR branch locally:
    git stash        # save any local changes first
    git fetch origin
    # Ensure the PR's source branch is available locally
    git checkout -b pr-<PR_ID> "origin/<source_branch>" 2>/dev/null || \
    git fetch origin "<source_branch>:pr-<PR_ID>" && git checkout pr-<PR_ID> || \
    git checkout "<source_branch>"

4. List only the files changed in this PR:
    git diff origin/<target_branch>..HEAD --name-only
    View the diff:
    git diff origin/<target_branch>..HEAD -- <file>

5. Create a review-fixes branch from the PR branch:
    git checkout -b review-fixes/pr-<PR_ID>

6. Review ONLY the files from step 4.
   Project root: .
   Apply ALL automatable fixes directly to the working tree.
   Write the full review_report.md.

7. Commit the fixes and the report:
    git add -A
    git commit -m "code-review: automated fixes for PR <PR_ID>

    Applied by code-review skill. Each fix is tagged with its finding ID
    (review-fix <ID>) in the source. Review individually before merging.
    See review_report.md for the full findings and manual items."

8. Push the fix branch:
    git push origin review-fixes/pr-<PR_ID>

9. Post a comment on the PR with the report + branch reference:
    Use python3 to safely encode the content as JSON (avoids control character errors):
    CONTENT=$(python3 -c "import json,sys; print(json.dumps({'content': sys.stdin.read()}))" < review_report.md)
    curl -s -H "X-Auth-AccessKey: $KEY" \
         -H "Content-Type: application/json" \
         -d "$CONTENT" \
         "https://<tuleap-host>/api/v1/pull_requests/<PR_ID>/comments"
    (Do NOT use `$(cat review_report.md)` directly in the curl payload — it will fail with control character errors.)

10. Return to your original branch:
    git checkout -
    git stash pop    # restore local changes if any
```

> **What the PR author sees**:
> - A comment with the full `review_report.md` (all findings, severities, test gaps)
> - A ready-to-use branch `review-fixes/pr-<PR_ID>` with one commit per
>   automatable fix, each tagged `# review-fix <ID>` in the source
> - Manual findings remain in the report for the author to handle

> **Note on comment length**: Tuleap PR comments support up to ~1 MB.
> If `review_report.md` exceeds ~500 lines, consider posting only the
> executive summary + CRITICAL/HIGH findings and attaching the full report
> as a file upload or wiki page.

> **Note on fixes**: fixes are NOT applied to the PR branch automatically.
> Each fix appears in the dedicated branch so the PR author can cherry-pick
> or merge them individually. This preserves the author's ownership of the PR.

---

## Commit review — function-level scope, no MR needed

> Reviews the full functions touched by a commit, not just the changed lines.
> Wider than a raw diff (catches context bugs), narrower than a full project scan.

```
/code-review
Review commit <SHA>.
Use commit/branch scope mode: restrict the review to the files changed in
this commit, and expand each change to its enclosing function so the
reviewer has full context — not just the diff lines.
Do NOT apply fixes automatically.
Write the full review_report.md.
```

---

## Branch review — function-level scope, vs a base branch

> Same principle as commit review, but compares an entire branch against a
> base branch. Useful before opening an MR, or for reviewing a long-lived
> feature branch without waiting for an MR to exist.

```
/code-review
Review branch <branch_name> against <base_branch>.
Use commit/branch scope mode: restrict the review to files changed between
<base_branch> and <branch_name>, and expand each change to its enclosing
function for full context.
Do NOT apply fixes automatically.
Write the full review_report.md.
```

> **If the branch doesn't exist locally**: run `git fetch origin
> <branch_name>` first, or `glab mr checkout !<MR_ID>` if it's tied to an MR.

> **Choosing this over diff-only tools**: a raw `git diff` shows only changed
> lines, which can hide bugs introduced by interaction with unchanged code in
> the same function (e.g. a modified early-return that skips validation logic
> a few lines below, unchanged). This mode always reads complete functions.
