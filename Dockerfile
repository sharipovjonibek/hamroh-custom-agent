# Your agent image = the hamroh framework image + your identity baked on top.
# The base image (hamroh-base) must be built first from the submodule:
#   docker build -t hamroh-base ./framework
# `make up` does that step for you, then builds this.
FROM hamroh-base

# Bake every framework prompt file (system.md, subagents.md, and any the
# framework adds later) straight from the pinned submodule — no cherry-picking
# — then overlay your persona on top. project.md isn't in the submodule
# (gitignored there), so the framework copy never clobbers yours.
COPY framework/prompts/ /app/prompts/
COPY prompts/project.md /app/prompts/project.md

# Bake the complete skill tree as a standalone-image fallback. Compose overlays
# this path with the same host directory so deployed skill edits persist.
COPY skills/ /app/skills/
