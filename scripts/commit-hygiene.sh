#!/bin/sh
# Rejects AI-tool attribution in commits, PR titles and PR descriptions:
#   - Co-Authored-By trailers naming an AI tool (Claude, Anthropic, Copilot,
#     ChatGPT/OpenAI/Codex, Cursor, Gemini, Devin, Aider), with any address
#   - Claude-Session trailers and Claude session URLs
#   - the "Generated with/by Claude (Code)" footer, plain, emoji or link form
#   - Claude model identifiers (claude-opus-..., claude-sonnet-..., claude-3-...)
#   - the cloud default identity Claude <noreply@anthropic.com>, any letter case
# The owner removed these from the whole history on 2026-11-20; see
# docs/engineering-standards.md, "Commit hygiene".
#
#   commit-hygiene.sh msg <file>           one commit message (the commit-msg hook)
#   commit-hygiene.sh range <base> <head>  every commit in base..head (CI)
#   commit-hygiene.sh body [label]         text on stdin, e.g. a PR title or
#                                          description (CI)
#
# It scans message text only, never file contents. Trailers and footers are
# matched where they stand (start of a line), so prose that names the rule,
# "Update CLAUDE.md" or a path under .claude/ still passes.
#
# POSIX sh so it also runs from Git for Windows; CR from CRLF input is stripped.
set -eu

FORBIDDEN_IDENTITY='noreply@anthropic.com'
AI_TOOLS='claude|anthropic|copilot|chatgpt|openai|codex|cursor|gemini|devin|aider'
# One extended regex per line, matched case-insensitively.
PATTERNS="^[[:space:]]*Claude-Session[[:space:]]*:
^[[:space:]]*Co-Authored-By[[:space:]]*:[^<]*($AI_TOOLS)
^[[:space:]]*Co-Authored-By[[:space:]]*:.*@(anthropic\\.com|openai\\.com)
claude\\.ai/code/session
^[^[:alnum:]]*Generated (with|by) \\[?Claude
Generated (with|by) \\[Claude Code\\]\\(
(^|[^[:alnum:]])claude-(opus|sonnet|haiku|fable|instant|[0-9])"

found=0

scan_text() { # $1 = label, text on stdin
  text=$(tr -d '\r')
  printf '%s\n' "$PATTERNS" | while IFS= read -r p; do
    # C locale: every pattern is ASCII, and Git for Windows' grep in a UTF-8
    # locale fails to match a 4-byte emoji (the footer's robot) as [^[:alnum:]].
    hit=$(printf '%s\n' "$text" | LC_ALL=C grep -E -i -n -- "$p" || true)
    if [ -n "$hit" ]; then
      printf '%s: forbidden attribution:\n%s\n' "$1" "$hit" >&2
      echo x
    fi
  done
}

is_forbidden_identity() { # $1 = "name <email>" text; case-insensitive
  lowered=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$lowered" in
    *"$FORBIDDEN_IDENTITY"*) return 0 ;;
  esac
  return 1
}

case "${1:-}" in
  msg)
    # Comment lines are stripped by git before the commit is made.
    out=$(grep -v '^#' "$2" | scan_text "commit message")
    [ -n "$out" ] && found=1
    for var in GIT_AUTHOR_IDENT GIT_COMMITTER_IDENT; do
      ident=$(git var "$var")
      if is_forbidden_identity "$ident"; then
        echo "$var is '$ident'. Set git user.name/user.email to a person before committing." >&2
        found=1
      fi
    done
    ;;
  range)
    for c in $(git rev-list "$2..$3"); do
      out=$(git log -1 --format=%B "$c" | scan_text "commit $c")
      [ -n "$out" ] && found=1
      who=$(git log -1 --format='%an <%ae> / %cn <%ce>' "$c")
      if is_forbidden_identity "$who"; then
        echo "commit $c: author/committer is $who" >&2
        found=1
      fi
    done
    ;;
  body)
    out=$(scan_text "${2:-description}")
    [ -n "$out" ] && found=1
    ;;
  *)
    echo "usage: $0 msg <file> | range <base> <head> | body [label] < text" >&2
    exit 2 ;;
esac

if [ "$found" -ne 0 ]; then
  echo "Remove the attribution above (see CLAUDE.md, 'Commit and PR messages')." >&2
  exit 1
fi
