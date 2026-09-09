# Default skills

One folder per skill, each containing a `SKILL.md` - the filename is
uppercase, and the folder name is the skill name:

```
skills/git-release/SKILL.md
```

`SKILL.md` starts with YAML frontmatter. OpenCode recognises exactly five
fields and ignores any others:

```markdown
---
name: git-release              # required
description: Create consistent releases and changelogs   # required
license: MIT                   # optional
compatibility: opencode        # optional
metadata:                      # optional, string-to-string map
  audience: maintainers
---

## What I do

The body: instructions, examples, whatever the skill needs.
```

- `name` is 1-64 characters matching `^[a-z0-9]+(-[a-z0-9]+)*$` - lowercase
  alphanumerics with single hyphens, no leading, trailing or doubled `-` -
  and must equal the folder name.
- `description` is 1-1024 characters and is genuinely required. It is what
  the agent sees when deciding whether to load the skill, so make it say both
  what the skill does and when to reach for it.
- Skill names must be unique across every location OpenCode searches.

This directory is bind-mounted read-only into every sandbox at
`~/.config/opencode/skills`, the documented location for global skills
(<https://opencode.ai/docs/skills/>), which is why they load without any
`skills.paths` entry in the generated config. Agents work the same way, from
`../agents/`.

Skills are loaded on demand: agents see the list of names and descriptions and
pull in the full body through the native `skill` tool when they need it.
Access can be gated per pattern with `permission.skill` in your own
`~/.config/ocbox/opencode.jsonc`, or the tool disabled per agent with
`tools: {skill: false}`.

Verified against opencode 1.18.29: a probe skill placed here shows up in
`opencode debug skill` with its `location` pointing at the mounted path. If
one of yours doesn't appear, check the frontmatter has both `name` and
`description`, that the filename is `SKILL.md` in capitals, and that the name
doesn't collide with another skill - a skill OpenCode rejects is simply absent
from the list rather than reported as an error. This README has no
frontmatter and isn't in a skill folder, so it is correctly ignored.

Project-specific skills belong in the project's own `.opencode/skills/`
inside the mounted workspace instead of here.
