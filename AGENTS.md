# Working in FairySkills

- A skill is a mechanism: `skills/<name>/SKILL.md` says how the agent works; `packages/<name>/` is the code it runs.
  Project paths, server addresses, dataset names and deck lists never appear here; they live in the project that uses the skill.
- Each package keeps its own `AGENTS.md` / `CONTRIBUTING.md` invariants (see `packages/fairyview/AGENTS.md`).
- `install.sh` is the only entry: editable installs plus symlinks into `~/.claude/skills`.
- Documentation is Chinese or English as the package already is; a config key is documented where it is read.
