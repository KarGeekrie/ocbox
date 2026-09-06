# Default skills

Put one subdirectory per skill here (e.g. `skills/my-skill/`) with whatever
files OpenCode's skill format expects. This directory is bind-mounted
read-only into every sandbox alongside `agents.json`, so it's a good place
for skills you want available in every project without reconfiguring
OpenCode each time.

The exact directory/file layout OpenCode expects for custom skills hasn't
been verified against its docs yet - see the project plan's open question
#7. Until then, treat this as a template: ocbox mounts whatever is here
as-is, it doesn't interpret or validate skill contents.

Project-specific skills should live in the project's own OpenCode config
inside the mounted workspace instead of here.
