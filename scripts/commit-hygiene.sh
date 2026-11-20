#!/bin/sh
# Rejects AI-tool attribution in commits and PR bodies: session URLs,
# Claude-Session / Co-Authored-By: Claude trailers, the "Generated with
# Claude Code" footer, and the cloud default identity Claude <noreply@anthropic.com>.
# The owner removed these from the whole history on 2026-11-20; see
# docs/engineering-standards.md, "Commit hygiene".
#
#   commit-hygiene.sh msg <file>        one commit message (the commit-msg hook)
#   commit-hygiene.sh range <base> <head>  every commit in base..head (CI)
#   commit-hygiene.sh body              text on stdin, e.g. a PR description (CI)
#
# POSIX sh so it also runs from Git for Windows.
set -eu

FORBIDDEN_IDENTITY='noreply@anthropic.com'
# Matches real trailers and footers, not prose that mentions them by name.
PATTERNS='^[[:space:]]*Claude-Session:
^[[:space:]]*Co-Authored-By:.*noreply@anthropic\.com
claude\.ai/code/session_
Generated (with|by) \[Claude Code\]\('

found=0

scan_text() { # $1 = label, text on stdin
  text=$(cat)
  printf '%s\n' "$PATTERNS" | while IFS= read -r p; do
    hit=$(printf '%s\n' "$text" | grep -E -i -n -- "$p" || true)
    if [ -n "$hit" ]; then
      printf '%s: forbidden attribution:\n%s\n' "$1" "$hit" >&2
      echo x
    fi
  done
}

case "${1:-}" in
  msg)
    # Comment lines are stripped by git before the commit is made.
    out=$(grep -v '^#' "$2" | scan_text "commit message")
    [ -n "$out" ] && found=1
    for var in GIT_AUTHOR_IDENT GIT_COMMITTER_IDENT; do
      ident=$(git var "$var")
      case "$ident" in
        *"$FORBIDDEN_IDENTITY"*)
          echo "$var is '$ident'. Set git user.name/user.email to a person before committing." >&2
          found=1 ;;
      esac
    done
    ;;
  range)
    for c in $(git rev-list "$2..$3"); do
      out=$(git log -1 --format=%B "$c" | scan_text "commit $c")
      [ -n "$out" ] && found=1
      who=$(git log -1 --format='%an <%ae> / %cn <%ce>' "$c")
      case "$who" in
        *"$FORBIDDEN_IDENTITY"*)
          echo "commit $c: author/committer is $who" >&2
          found=1 ;;
      esac
    done
    ;;
  body)
    out=$(scan_text "description")
    [ -n "$out" ] && found=1
    ;;
  *)
    echo "usage: $0 msg <file> | range <base> <head> | body < text" >&2
    exit 2 ;;
esac

if [ "$found" -ne 0 ]; then
  echo "Remove the attribution above (see CLAUDE.md, 'Commit and PR messages')." >&2
  exit 1
fi
