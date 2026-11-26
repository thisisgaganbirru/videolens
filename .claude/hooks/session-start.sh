#!/bin/bash
# Cloud sessions only. Two things, both cheap and idempotent:
#  1. Turn on the repo's commit-msg hook (.githooks/), which rejects AI-tool
#     attribution in commit messages and the Claude identity below.
#  2. Cloud containers commit as "Claude <noreply@anthropic.com>" by default.
#     That identity was scrubbed from the whole history on 2026-11-20; commit
#     as the owner instead. Only replaced when it is that default, so a
#     deliberately set identity is left alone.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

git config core.hooksPath .githooks

if [ "$(git config user.email || true)" = "noreply@anthropic.com" ]; then
  git config user.name "gaganbirru"
  git config user.email "gagansai9090@gmail.com"
fi
