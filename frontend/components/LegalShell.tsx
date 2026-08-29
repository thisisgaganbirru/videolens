import Link from "next/link";
import { ChevronLeft, House } from "lucide-react";
import AppNav from "@/components/AppNav";

/* Hallmark · theme: Terminal (locked, carried from tokens.css) · macrostructure: Long Document
 *
 * Shared frame for /privacy and /terms. They are one document type, so they
 * share a shape rather than each inventing one; the page files hold only copy.
 *
 * Chrome is the app's chrome, not a legal-page variant: the same `.shell`
 * frame, the same `<AppNav />` — brand, all four tabs, drawer and theme toggle,
 * literally the same component HomeScreen renders — and the same
 * `.page-end` / `.foot` footer. A standalone route is still the same
 * application, so it does not get its own furniture. The tabs work here because
 * they address the URL (`/?view=history`), not HomeScreen's React state; none
 * of them is `aria-current` on a legal route, because none of them is where you
 * are.
 *
 * `data-frame="fixed"` locks the nav and footer to the viewport; only the
 * document body between them scrolls, and only when the content is actually
 * taller than that band.
 */

type LegalShellProps = {
  title: string;
  effective: string;
  /** Which legal route this is — labels the crumb and marks the footer link. */
  current: "privacy" | "terms";
  children: React.ReactNode;
};

export default function LegalShell({ title, effective, current, children }: LegalShellProps) {
  return (
    <div className="shell" data-view="legal" data-frame="fixed">
      <AppNav activeTab={null} />

      <section data-view="legal" aria-label={title}>
        {/* Two different things, so two different elements: a control, then a
            location. The back button is deliberately OUTSIDE the <ol> — it is
            an action, not an ancestor, and listing it as a breadcrumb item
            would tell a screen reader this document sits two levels deep when
            it sits one. The trail below it is a real <nav> + <ol>, which is
            what lets assistive tech announce "breadcrumb, 2 items" and skip
            the whole thing. */}
        <div className="crumb-bar">
          <Link href="/" className="crumb-back">
            <ChevronLeft aria-hidden="true" />
            {/* A real text node rather than aria-label: translatable, and it
                survives a text-only rendering. `sr-only` is absolutely
                positioned, so it is not a flex item and cannot push the
                glyph off centre. */}
            <span className="sr-only">Back to VideoLens AI</span>
          </Link>

          <nav aria-label="Breadcrumb">
            <ol>
              <li>
                <Link href="/" className="crumb-home">
                  <House aria-hidden="true" />
                  <span className="sr-only">VideoLens AI home</span>
                </Link>
              </li>
              <li>
                {/* aria-hidden: the slash is the visible grammar of a path, but
                    read aloud between two items it is only noise. */}
                <span className="crumb-sep" aria-hidden="true">
                  /
                </span>
                <span className="crumb-current" aria-current="page">
                  {current}
                </span>
              </li>
            </ol>
          </nav>
        </div>

        <div className="legal-doc select-text">
          <div className="legal-body">
            <h1 className="page-title">{title}</h1>
            <p className="card-label mt-[var(--space-xs)]">{effective}</p>

            <div className="legal-copy mt-[var(--space-lg)] flex flex-col gap-[var(--space-lg)] pb-[var(--space-lg)]">
              {children}
            </div>
          </div>
        </div>
      </section>

      <div className="page-end">
        <footer className="foot">
          <span>VideoLens AI</span>
          <nav className="foot-legal" aria-label="Legal">
            <Link href="/privacy" aria-current={current === "privacy" ? "page" : undefined}>
              Privacy
            </Link>
            <Link href="/terms" aria-current={current === "terms" ? "page" : undefined}>
              Terms
            </Link>
          </nav>
        </footer>
      </div>
    </div>
  );
}

/** A single titled clause. Kept here so both routes get identical section rhythm. */
export function LegalSection({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="col-label">{heading}</h2>
      <p className="prose mt-[var(--space-xs)]">{children}</p>
    </section>
  );
}
