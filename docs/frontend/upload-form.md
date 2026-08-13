# Upload form

The "Analyze" tab's entry point: paste a public media URL, or drag/drop/browse a local file. URL is the primary path (listed first, larger emphasis) with file upload as secondary.

**Files**
- `frontend/components/UploadForm.tsx` — everything (no dedicated hook; this component's local state is presentational/form-validation only, not app-wide state, so it wasn't pulled into `application/`).

**Client-side pre-validation** (backend re-validates authoritatively regardless):
- File: extension allowlist (`.mp3`/`.mp4`/`.mov`), `MAX_FILE_SIZE_MB` (200), and a best-effort duration check (`readMediaDuration`, via a hidden `<video>`/`<audio>` element's `loadedmetadata` event) against `MAX_DURATION_SECONDS` (180) — wrapped in try/catch since this can fail on some browsers/files, in which case it's silently skipped ("Backend performs authoritative validation").
- URL: must parse as `http:`/`https:`.

**Terms acceptance**: a checkbox, persisted in `localStorage` (`videolens-media-terms-v1`) so it stays checked across sessions once accepted. Required before either submit path is enabled.

**Native share-target handling**: on mount, checks for a shared URL arriving three possible ways — a `?url=` query param, a `?text=` param containing a URL, or `localStorage.getItem("videolens-shared-text")` (set by the native Android share-intent handler) — and also listens for a `"videolens-share"` window event for shares that arrive after initial mount. This is what makes "Share to VideoLens AI" work from other Android apps.

**Known issue**: none identified beyond the documented best-effort duration check.

**Tests**: none (see `run-analysis-hook.md`).
