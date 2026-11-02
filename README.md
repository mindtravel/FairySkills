# FairySkills

Skills are mechanisms; projects keep only configuration. Each skill here is a `SKILL.md` (what the agent follows) backed
by a pip-installable package (what the commands run). Nothing in this repository names a project path.

| skill | package | what it does |
|---|---|---|
| [fairyview](skills/fairyview/SKILL.md) | [packages/fairyview](packages/fairyview) | self-contained HTML pages to review rows of a dataset, cleaning output or model comparison |
| [fairyppt](skills/fairyppt/SKILL.md) | [packages/fairyppt](packages/fairyppt) | data-driven beamer decks: generators compute every number, `fairyppt build` makes the PDF |

```bash
bash install.sh      # pip install -e packages/*; symlink skills/* into ~/.claude/skills
```

A project using a skill keeps its configs (review configs, deck generators, score specs) in its own tree and installs
this repository once.
