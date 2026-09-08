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

This directory is bind-mounted read-only into every sandbox at
`~/.config/opencode/agent`, which is where OpenCode looks for global agents.
Unlike skills, there is no config key that points at an arbitrary agent
folder, so the mount location is what makes these load.

`build.md` and `plan.md` override OpenCode's built-in agents of the same
name. The override is a merge: fields present here win, everything else -
including the built-ins' permission rules, such as plan mode's edit denial -
is preserved. That's why neither file redeclares `permission`; hand-copying
those rules would risk weakening plan mode with no visible sign.

Verified against opencode 1.18.29: `opencode agent list` from inside a
sandbox shows what actually loaded, and `opencode debug agent <name>` shows
one agent's resolved configuration. A file OpenCode doesn't accept is simply
absent from the list rather than reported as an error - this README, for
instance, has no frontmatter and so is correctly ignored.
