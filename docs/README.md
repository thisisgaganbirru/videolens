# docs/

This project's docs/ folder holds quick per-feature/component reference docs — what a feature does, what files it touches, known issues — so it can be understood without reading all the source. It does NOT replace README.md / ARCHITECTURE.md / DESIGN.md / PUBLISH.md (if present); those cover onboarding, high-level architecture, and release process, not per-feature reference.

Every new feature or component should get (or update) a doc here. Scope is strictly the feature/component you're actively touching this session — never a retroactive sweep to document the rest of an existing codebase just because docs/ is new or empty. Pre-existing features stay undocumented until someone actually touches them — this folder starting empty is not a backlog to clear.

## Cross-cutting docs

Everything else here is filed per feature under `backend/` or `frontend/`. The
exception, listed so it isn't mistaken for a stray file:

- `container-workflows.md` — local/dev/production workflow boundaries,
  hardened container behavior, image publication, and operator requirements.
- `engineering-standards.md` — cross-cutting, not a per-feature reference. A
  repo-wide engineering-hygiene register audited 2026-08-15. Dependency
  reproducibility and container vulnerability gates are now implemented;
  remaining findings stay deferred.

## Applies to subagents too — no exceptions

**Every agent and subagent follows this, not just the main session.** If you were
dispatched to do a piece of work, you read the relevant doc here *before*
starting and update it *before* reporting back. "The orchestrator will document
it" is not an exemption — the agent that did the work is the one that knows what
changed and why.

## Changelog line (required)

When you touch a doc, append one line to its `## Changelog` section (create the
section if absent) so the next agent can see what has already been done and by
whom, instead of re-deriving it or redoing it:

```markdown
## Changelog
- 2026-08-15 · frontend agent · ported the legal routes to the shared app chrome; added the crumb bar
- 2026-08-15 · main session · deleted the dead Midnight Glass classes after their last caller was ported
```

Format: `YYYY-MM-DD · <who> · <what changed, one line>`. Newest last. `<who>` is
the agent type (`frontend agent`, `main session`, …). Keep it to one line — the
detail belongs in the doc body and in `mem/`.

**Several agents share these files.** Read the changelog before editing so you
don't duplicate or revert a sibling's work, and append rather than rewriting
someone else's entry.

## Changelog

- 2026-08-15 · main session · indexed the environment-separated container workflow reference and updated the standards status
