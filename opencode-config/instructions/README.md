# Default instructions

**Unverified** - see AGENTS.md's "Verification history" and, if you can,
confirm the mechanism below with `opencode debug config` after your first
real run, since this is the one piece of `opencode-config/` ocbox hasn't
checked against a real OpenCode binary yet (network to opencode.ai is
blocked in the sandbox this repo was developed in).

Unlike agents and skills, instructions aren't believed to be auto-discovered
from this directory alone - they have to be listed explicitly as glob
patterns in `opencode.jsonc`'s own `instructions` array:

```jsonc
{
  "instructions": ["instructions/*.md"]
}
```

`opencode-config/opencode.jsonc` already has this. Each `.md` file here is
plain markdown - no frontmatter, no naming convention - whose content is
believed to be added to every session's context, unconditionally, unlike a
skill (loaded on demand, when an agent decides it's relevant) or an agent
(a whole selectable persona/prompt). Use it for standing rules you want
followed regardless of which agent is active.

Mounted read-only at `~/.config/opencode/instructions` (same mechanism as
`../agents/`/`../skills/`), so the relative glob above resolves the same way
whether `opencode.jsonc` itself is this mount (web/`--tui`) or, in
`--no-sandbox` mode, the real `~/.config/opencode/opencode.jsonc` symlink -
either way, `instructions/` sits right next to it.

If a file here doesn't show up under `opencode debug config`, the key name,
the glob, or the whole mechanism may not match OpenCode's real schema -
report back so this README (and the mount it documents) can be fixed rather
than left silently wrong.
