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
code without changing it, and `review`, for finding bugs in a change. `review`
is read-only by design (see below) and reaches for the `code-review`/
`sota-review` skills in `../skills/` for anything beyond a small diff;
applying the fixes those skills can propose needs `build` instead, since
`review` can't edit.

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
concerned. `chat` therefore denies both; `review` denies `edit` and sets
`bash: ask`, so `git diff` stays available under the user's approval.

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
an error - this README, for instance, has no frontmatter and so is correctly
ignored.
