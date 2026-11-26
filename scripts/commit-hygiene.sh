#!/bin/sh
# Rejects AI-tool attribution in commits, PR titles and PR descriptions:
#   - Co-authored-by trailers for an AI tool: Claude (alone or with a model
#     word), Anthropic, Copilot, ChatGPT/OpenAI, Codex, Cursor's agent,
#     Gemini Code Assist, Devin AI, aider, or any anthropic.com/openai.com
#     address. Matched on whole words and the tools' known names and bot
#     addresses, so people named Haider, Devin or Gemini Patel pass.
#   - Claude-Session trailers and Claude session URLs
#   - the "Generated with/by Claude (Code)" footer, plain, emoji or link form
#   - Claude model identifiers (claude-opus-..., claude-3-..., claude_opus)
#     and display names (Claude Opus 5.5, Claude 3.5 Sonnet)
#   - an author or committer at any anthropic.com address, or named Claude
# The owner removed these from the whole history on 2026-11-20; see
# docs/engineering-standards.md, "Commit hygiene".
#
#   commit-hygiene.sh msg <file>           one commit message (the commit-msg hook)
#   commit-hygiene.sh range <base> <head>  every commit in base..head (CI)
#   commit-hygiene.sh body [label]         text on stdin, e.g. a PR title or
#                                          description (CI)
#
# It scans message text only, never file contents. Before matching, the text
# is normalised: zero-width and bidi characters dropped, Unicode hyphens,
# spaces, quotes and a few Cyrillic look-alike letters folded to ASCII, `_`
# read as `-`, whitespace runs squeezed, leading quote/bullet/comment markers
# (`>`, `*`, `-`, `+`, `<!--`) stripped, and a footer split after "Generated
# with" rejoined (across blank lines too). Trailers and footers are matched
# where they stand (start of a line), so prose that names the rule, a line
# that opens with a quote mark, "Update CLAUDE.md" or a path under .claude/
# still passes. Model identifiers are matched anywhere, except, in body mode
# only, on the lines strictly between a line that opens with <details and its
# matching line that opens with </details>: Dependabot puts upstream release
# notes and commit lists there. An unclosed block exempts nothing. In msg
# mode the message is cut at git's scissors line (`git commit -v`).
#
# POSIX sh so it also runs from Git for Windows. Everything runs under
# LC_ALL=C and works on bytes: the folded characters are matched as their
# UTF-8 byte sequences, and Git for Windows' grep in a UTF-8 locale fails to
# match a 4-byte emoji (the footer's robot) as [^[:alnum:]]. CR is stripped.
set -eu
LC_ALL=C
export LC_ALL

# UTF-8 byte sequences (octal) folded before matching.
o() { printf "$1"; } # $1 is always a fixed escape string from this file
FOLD_SED="
s/$(o '\342\200')[$(o '\213-\217')]//g
s/$(o '\342\200')[$(o '\252-\256')]//g
s/$(o '\342\201')[$(o '\240-\244')]//g
s/$(o '\357\273\277')//g
s/$(o '\302\255')//g
s/$(o '\341\240\216')//g
s/$(o '\342\200')[$(o '\220-\225')]/-/g
s/$(o '\342\201\203')/-/g
s/$(o '\342\210\222')/-/g
s/$(o '\357\271\243')/-/g
s/$(o '\357\274\215')/-/g
s/$(o '\357\274\232')/:/g
s/$(o '\302\240')/ /g
s/$(o '\342\200')[$(o '\200-\212')]/ /g
s/$(o '\342\200\257')/ /g
s/$(o '\342\201\237')/ /g
s/$(o '\343\200\200')/ /g
s/$(o '\342\200')[$(o '\230-\233')]/'/g
s/$(o '\342\200')[$(o '\234-\237')]/\"/g
s/$(o '\320\260')/a/g
s/$(o '\320\265')/e/g
s/$(o '\320\276')/o/g
s/$(o '\321\200')/p/g
s/$(o '\321\201')/c/g
s/$(o '\321\203')/y/g
s/$(o '\321\205')/x/g
s/$(o '\321\226')/i/g
s/$(o '\323\217')/l/g
s/$(o '\324\201')/d/g
s/$(o '\320\220')/A/g
s/$(o '\320\222')/B/g
s/$(o '\320\225')/E/g
s/$(o '\320\232')/K/g
s/$(o '\320\234')/M/g
s/$(o '\320\235')/H/g
s/$(o '\320\236')/O/g
s/$(o '\320\240')/P/g
s/$(o '\320\241')/C/g
s/$(o '\320\242')/T/g
s/$(o '\320\245')/X/g
s/$(o '\320\206')/I/g
"

# Extended regexes, one per line, matched case-insensitively against the
# normalised text. Trailer values have one space after the colon at most.
PATTERNS=$(cat <<'EOF'
^co[- ]?authored[- ]?by ?:.*(^|[^[:alnum:]])(anthropic|copilot|chatgpt|openai|codex)([^[:alnum:]]|$)
^co[- ]?authored[- ]?by ?: ?claude([ -](code|opus|sonnet|haiku|fable|instant|ai|[0-9][0-9.]*))* ?(<|\(|\[|$)
^co[- ]?authored[- ]?by ?: ?(cursor( agent)?|gemini( code assist| cli)?|google gemini|devin[ -]ai|aider)( \([^)]*\))? ?(<|\[|$)
^co[- ]?authored[- ]?by ?:.*(@([[:alnum:].-]+\.)?(anthropic\.com|openai\.com)|@aider\.chat|cursoragent@|devin-ai-integration|gemini-code-assist|copilot-swe-agent)
^co[- ]?authored[- ]?by ?:.*\(aider\)
^claude-? ?session ?:
claude\.ai/code/session
^[^[:alnum:]"'`]*generated (with|by) \[?claude
generated (with|by) \[claude code\]\(
EOF
)
MODEL_PATTERNS=$(cat <<'EOF'
(^|[^[:alnum:]])claude-(opus|sonnet|haiku|fable|instant|[0-9])
(^|[^[:alnum:]])claude (opus|sonnet|haiku|fable|instant) ?[0-9]
(^|[^[:alnum:]])claude [0-9][0-9.]* (opus|sonnet|haiku)
EOF
)

found=0

normalise() { # stdin -> stdout
  tr -d '\r' | sed -e "$FOLD_SED" | tr '\t_' ' -' | tr -s ' ' |
    sed -E 's/^([[:space:]]|>|[-*+]|<!--)+//' |
    awk '{
      if (held != "") {
        if ($0 ~ /^ *$/) next
        print held " " $0; held = ""
      }
      if (tolower($0) ~ /generated (with|by) ?$/) { held = $0; next }
      print
    } END { if (held != "") print held }'
}

# stdin -> stdout. Drops the lines strictly between a line that opens with
# <details (and does not also close it) and its matching line that opens with
# </details>; both tag lines are kept. Nested blocks count. An unclosed block
# drops nothing: its lines are held and printed at the end.
drop_details() {
  awk '{
    l = tolower($0)
    open = (l ~ /^<details([ >]|$)/ && index(l, "</details>") == 0)
    shut = (l ~ /^<\/details>/)
    if (depth == 0) { print; if (open) { depth = 1; n = 0 }; next }
    if (shut && depth == 1) { depth = 0; n = 0; print; next }
    buf[++n] = $0
    if (open) depth++
    else if (shut) depth--
  } END { for (i = 1; i <= n; i++) print buf[i] }'
}

scan_text() { # $1 = label, $2 = details (body mode); text on stdin; prints x on a hit
  text=$(normalise)
  hit=$(printf '%s\n' "$text" | grep -E -i -n -e "$PATTERNS" || true)
  if [ "${2:-}" = details ]; then
    models=$(printf '%s\n' "$text" | drop_details | grep -E -i -n -e "$MODEL_PATTERNS" || true)
  else
    models=$(printf '%s\n' "$text" | grep -E -i -n -e "$MODEL_PATTERNS" || true)
  fi
  if [ -n "$hit$models" ]; then
    printf '%s: forbidden attribution:\n' "$1" >&2
    [ -z "$hit" ] || printf '%s\n' "$hit" >&2
    [ -z "$models" ] || printf '%s\n' "$models" >&2
    echo x
  fi
}

is_forbidden_identity() { # $1 = name, $2 = email; case-insensitive
  name=$(printf '%s\n' "$1" | normalise | tr '[:upper:]' '[:lower:]' | sed 's/^ //;s/ $//')
  email=$(printf '%s\n' "$2" | normalise | tr '[:upper:]' '[:lower:]' | tr -d ' ')
  case "$email" in
    *@anthropic.com | *@*.anthropic.com) return 0 ;;
  esac
  case "$name" in
    claude | "claude code" | "claude[bot]" | "claude "[0-9]* | \
    "claude opus"* | "claude sonnet"* | "claude haiku"* | "claude fable"*) return 0 ;;
  esac
  return 1
}

case "${1:-}" in
  msg)
    # git drops everything from the scissors line down (`git commit -v` puts
    # the staged diff there) and strips comment lines before the commit is
    # made. CI's range check reads the commit as made, so this cut cannot
    # hide anything from it.
    out=$(sed '/^# -\{24\} >8 -\{24\}$/,$d' "$2" | grep -v '^#' |
      scan_text "commit message")
    [ -n "$out" ] && found=1
    for var in GIT_AUTHOR_IDENT GIT_COMMITTER_IDENT; do
      ident=$(git var "$var")
      name=$(printf '%s\n' "$ident" | sed 's/ <.*//')
      email=$(printf '%s\n' "$ident" | sed -n 's/.*<\(.*\)>.*/\1/p')
      if is_forbidden_identity "$name" "$email"; then
        echo "$var is '$ident'. Set git user.name/user.email to a person before committing." >&2
        found=1
      fi
    done
    ;;
  range)
    # Assigned first so a failing rev-list stops the script (set -e) instead
    # of checking no commits.
    commits=$(git rev-list "$2..$3")
    for c in $commits; do
      msg=$(git log -1 --format=%B "$c")
      out=$(printf '%s\n' "$msg" | scan_text "commit $c")
      [ -n "$out" ] && found=1
      who=$(git log -1 --format='%an%n%ae%n%cn%n%ce' "$c")
      an=$(printf '%s\n' "$who" | sed -n 1p); ae=$(printf '%s\n' "$who" | sed -n 2p)
      cn=$(printf '%s\n' "$who" | sed -n 3p); ce=$(printf '%s\n' "$who" | sed -n 4p)
      if is_forbidden_identity "$an" "$ae" || is_forbidden_identity "$cn" "$ce"; then
        echo "commit $c: author/committer is $an <$ae> / $cn <$ce>" >&2
        found=1
      fi
    done
    n=$(printf '%s\n' "$commits" | grep -c . || true)
    echo "Checked $n commit(s) in $2..$3."
    ;;
  body)
    out=$(scan_text "${2:-description}" details)
    [ -n "$out" ] && found=1
    echo "Checked the ${2:-description}."
    ;;
  *)
    echo "usage: $0 msg <file> | range <base> <head> | body [label] < text" >&2
    exit 2 ;;
esac

if [ "$found" -ne 0 ]; then
  echo "Remove the attribution above (see CLAUDE.md, 'Commit and PR messages')." >&2
  exit 1
fi
