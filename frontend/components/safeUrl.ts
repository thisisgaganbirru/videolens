/** An http(s) URL fit for an `href`, or null.
 *
 * `source_url` and `uploader_url` on a run's source metadata come from yt-dlp,
 * i.e. from the page that was fetched, so they are third-party strings. React
 * refuses to render a `javascript:` href and the CSP would stop it running,
 * but an anchor should not depend on either: anything that is not a plain
 * web address simply is not linked. Markdown links are sanitised separately by
 * react-markdown; this is for the anchors the SourceCard and the export build
 * by hand. */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
}
