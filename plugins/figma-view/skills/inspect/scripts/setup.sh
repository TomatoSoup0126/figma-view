#!/usr/bin/env bash
# Prepare jev-ultrafast (browser-harness + the TypeSafe client) for figma-view.
# Idempotent. The last line printed is the clone path, for `uv run --project`.
# Exit 2 on any failure, with the reason on stderr.
set -euo pipefail

fail() { echo "figma-view setup: $*" >&2; exit 2; }
command -v git >/dev/null || fail "git not found"
command -v uv >/dev/null || fail "uv not found (https://docs.astral.sh/uv/)"

REPO_URL="https://github.com/browser-use/jev-ultrafast.git"
# Same pin as galleon's ux-review, so both skills can share one clone.
PINNED_COMMIT="1231850a0bf1a0c0341fe408ef1668dbbfdfac46"
JEV_DIR="${JEV_DIR:-$HOME/.cache/jev-ultrafast}"

if [ ! -d "$JEV_DIR/.git" ]; then
  git clone --quiet "$REPO_URL" "$JEV_DIR" || fail "clone of $REPO_URL failed (network?)"
fi
if [ "$(git -C "$JEV_DIR" rev-parse HEAD)" != "$PINNED_COMMIT" ]; then
  git -C "$JEV_DIR" fetch --quiet origin || fail "fetch failed (network?)"
  git -C "$JEV_DIR" checkout --quiet "$PINNED_COMMIT" || fail "checkout $PINNED_COMMIT failed (uncommitted changes in $JEV_DIR?)"
fi
uv sync --quiet --project "$JEV_DIR" || fail "uv sync failed"

# Needed only for --find (Jev). Never print the value.
[ -n "${TYPESAFE_API_KEY:-}" ] || echo "figma-view setup: TYPESAFE_API_KEY is not set; only node-id mode will work" >&2
echo "$JEV_DIR"
