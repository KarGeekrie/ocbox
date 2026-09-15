---
# Not an agent - this is the documentation for this directory. OpenCode loads
# every *.md here as an agent, this file included: without `disable`, it shows
# up in `opencode agent list` as an agent literally named "README", selectable
# and callable, with default (unrestricted) permissions. `disable: true` is
# what keeps it out - verified against a real container, before and after.
disable: true
---

# Default agents

One `<name>.md` per agent. The filename is the agent name, and the file is a
markdown document with YAML frontmatter:

```markdown
---
description: What the agent is for and when to reach for it.
mode: primary
permission:
  edit: deny
---

The body becomes the agent's prompt.
```

`mode` is `primary` (selectable as the main agent), `subagent` (callable by
other agents), or `all`. Other frontmatter fields OpenCode accepts: `model`,
`variant`, `hidden`, `color`, `steps`, `options`, `permission`, `disable`,
`temperature`, `top_p`. Don't put `prompt:` in the frontmatter - the body is
the prompt.

## What's here, and what isn't

This directory holds the team's additional agents: `chat`, for talking through
code without changing it, and `review`, for finding bugs in a change. Both are
`mode: primary`, so Tab cycles through them next to OpenCode's `build` and
`plan` - reviewing is meant to be one keystroke away, not buried behind a
subagent call. `review` can't change code by design (see below): the only file
it may write is `review_report.md`, the report `code-review` produces. It
reaches for the `code-review`/`sota-review` skills in `../skills/` for anything
beyond a small diff; applying the fixes those skills can propose needs `build`
instead.

`build` and `plan` are deliberately **not** here. They are OpenCode's own
built-in primary agents, used exactly as OpenCode ships them. A `build.md` or
`plan.md` in this directory would change them - OpenCode merges such a file
into the built-in agent of the same name - so leave those names alone.

Agent prompts describe a role, not an environment. Where the agent runs - a
sandbox without network, or the user's own machine - comes from the global
`AGENTS.md` ocbox composes for each mode (see the main README's "Workflow"),
so no agent file states something that is only true in one mode.

## Restricting what an agent can do

`permission` gates individual tools with `allow`, `ask` or `deny`, and covers
`edit` (all writes, patches and modifications), `bash` and `webfetch`. The
alternative, `tools: {edit: false}`, removes a tool outright.

**Denying `edit` alone does not make an agent read-only.** The default is
`*: allow`, so an agent that cannot use the edit tool can still rewrite files
through `bash` - `echo x > file` is not an edit as far as permissions are
concerned. `chat` therefore denies both; `review` denies `edit` except for its
report and sets `bash: ask`, so `git diff` stays available under the user's
approval.

`review`'s exception is written twice, as `review_report.md` and
`*/review_report.md`. OpenCode matches `edit` patterns against the path relative
to the project's worktree. In a git repository that is the file name itself, but
in a sandboxed project that isn't one it is `workspace/review_report.md`. The
second form also lets `review` write a file of that name in a subdirectory -
nothing else.

Both deny `webfetch`: they work from the code in front of them, and in a
sandbox, which has no network, a fetch could only fail.

## How ocbox loads them

In the sandboxed modes this directory is bind-mounted read-only at
`~/.config/opencode/agents`, the documented location for global agents
(<https://opencode.ai/docs/agents/>). With `--no-sandbox` it is linked into the
config directory ocbox hands OpenCode through `OPENCODE_CONFIG_DIR`. OpenCode
accepts the singular `agent/` too, but the plural is what the docs name.

`opencode agent list` shows what actually loaded, and
`opencode debug agent <name>` one agent's resolved configuration. A file
OpenCode doesn't accept is simply absent from the list rather than reported as
an error.

**Every `*.md` in this directory is loaded, including one with no frontmatter
at all.** An earlier version of this file claimed the opposite - that a
frontmatter-less README was "correctly ignored". It was not: it loaded as an
agent named `README`, in mode `all` (so both selectable and callable as a
subagent) with no permission restrictions. That is why this file now carries
`disable: true`. Any other documentation you drop in here needs the same, or
a name that doesn't end in `.md`.
