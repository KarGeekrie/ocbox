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

## Restricting what an agent can do

`permission` gates individual tools with `allow`, `ask` or `deny`, and covers
`edit` (all writes, patches and modifications), `bash` and `webfetch`. The
alternative, `tools: {edit: false}`, removes a tool outright.

**Denying `edit` alone does not make an agent read-only.** The default is
`*: allow`, so an agent that cannot use the edit tool can still rewrite files
through `bash` - `echo x > file` is not an edit as far as permissions are
concerned. `chat` therefore denies both; `review` denies `edit` and sets
`bash: ask`, so `git diff` stays available under the user's approval.

Every agent here denies `webfetch`: the sandbox has no network, so it can only
ever fail, and denying it stops the agent burning turns on retries.

This directory is bind-mounted read-only into every sandbox at
`~/.config/opencode/agents`, the documented location for global agents
(<https://opencode.ai/docs/agents/>). Unlike skills, there is no config key
that points at an arbitrary agent folder, so the mount location is what makes
these load. OpenCode accepts the singular `agent/` too, but the plural is what
the docs name.

`build.md` and `plan.md` override OpenCode's built-in agents of the same
name. The override is a merge, and permissions merge *per key*: naming
`webfetch` in `plan.md` leaves plan mode's three built-in `edit` rules exactly
as they were. That is why neither file redeclares `edit` - hand-copying those
rules would risk weakening plan mode with no visible sign, and there is
nothing to gain since the built-ins already survive.

Verified against opencode 1.18.29: `opencode agent list` from inside a
sandbox shows what actually loaded, and `opencode debug agent <name>` shows
one agent's resolved configuration. A file OpenCode doesn't accept is simply
absent from the list rather than reported as an error - this README, for
instance, has no frontmatter and so is correctly ignored.
