#!/usr/bin/env bash
# Link the main checkout's gitignored build inputs (lib/: the stdlib the mod
# links) and the sys submodule (LibHakkun) into a git worktree, so a branch
# builds the mod without touching the main tree. .env and the venvs stay out:
# run the MCP tools with the main checkout's mcp/.venv/bin/python.
#
#   tools/worktree_setup.sh [main-checkout]    # run inside the worktree
set -euo pipefail
main="${1:-$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')}"
here="$(git rev-parse --show-toplevel)"
[ "$main" != "$here" ] || { echo "run this inside a worktree, not the main checkout" >&2; exit 1; }
if [ -e "$main/lib" ] && [ ! -e "$here/lib" ]; then ln -s "$main/lib" "$here/lib" && echo "linked lib"; fi
# A link, not a checkout: never stage it (git status shows a typechange).
if [ -d "$main/sys" ] && [ -z "$(ls -A "$here/sys" 2>/dev/null)" ]; then
    rmdir "$here/sys" 2>/dev/null || true
    ln -s "$main/sys" "$here/sys" && echo "linked sys (submodule)"
fi
