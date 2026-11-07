import type { LegalRoute } from "@/components/MoreSheet";

/* The web shell's footer, one copy for every route (it was three identical
 * blocks in HomeScreen, LegalShell and /offline). Hidden only in the
 * phone-width installed-app shell (<= 37.5rem), where Privacy and Terms are
 * rows in the More sheet; a wider installed window shows it.
 *
 * Plain <a>, not next/link: /offline renders this from the service-worker
 * cache with the network down, where a client-side navigation cannot resolve.
 */
export default function SiteFooter({ current }: { current?: LegalRoute }) {
  return (
    <div className="page-end">
      <footer className="foot">
        <span>VideoLens AI</span>
        <nav className="foot-legal" aria-label="Legal">
          <a href="/privacy" aria-current={current === "privacy" ? "page" : undefined}>
            Privacy
          </a>
          <a href="/terms" aria-current={current === "terms" ? "page" : undefined}>
            Terms
          </a>
        </nav>
      </footer>
    </div>
  );
}
