# Default skills

Put one subdirectory per skill here, each containing a `SKILL.md`:

```
skills/my-skill/SKILL.md
```

`SKILL.md` needs YAML frontmatter with `name` and `description`:

```markdown
---
name: my-skill
description: What it does and when to use it - front-load the trigger words.
---

Body of the skill, in markdown.
```

`name` is lowercase-hyphenated, up to 64 characters, and matches the folder
name. `description` is effectively required: OpenCode filters out skills
without one and never surfaces them to the model.

This directory is bind-mounted read-only into every sandbox at
`/etc/ocbox/skills`, and ocbox registers it via `skills.paths` in the
`opencode.json` it generates, so skills you drop here are available in every
project without reconfiguring OpenCode each time.

Layout verified against opencode 1.18.29: a probe skill placed here shows up
in `opencode debug skill` with its `location` pointing at the mounted path.
That command is the way to check your own - a skill OpenCode doesn't like is
simply absent from the list rather than reported as an error.

Project-specific skills should live in the project's own OpenCode config
inside the mounted workspace instead of here.
