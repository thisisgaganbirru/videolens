import AppBackLink from "@/components/AppBackLink";
import AppNav from "@/components/AppNav";
import BottomTabBar from "@/components/BottomTabBar";
import SiteFooter from "@/components/SiteFooter";

/* Hallmark · theme: editorial (tokens.css) · macrostructure: Long Document
 * (design/phase4-boards/Privacy*.png, Terms*.png: serif title, a muted date
 * line right under it, then serif section heads over Hanken body at a reading
 * measure — no rules between sections, and no crumb bar: the boards drop it,
 * the shared nav above is the way back)
 *
 * Shared frame for /privacy and /terms. They are one document type, so they
 * share a shape rather than each inventing one; the page files hold only copy.
 *
 * Chrome is the app's chrome, not a legal-page variant: the same `.shell`
 * frame, the same `<AppNav />`, and the same `<SiteFooter />` (browser tab) or
 * `<BottomTabBar />` (installed app) — literally the components HomeScreen
 * renders. A standalone route is still the same application, so it does not
 * get its own furniture. The tabs work here because they address the URL
 * (`/?view=history`), not HomeScreen's React state; none of them is
 * `aria-current` on a legal route, because none of them is where you are.
 *
 * Scrolling is HomeScreen's model (Phase 4): the section is a `.view-scroll`
 * band — from 32rem up it scrolls between the fixed nav and footer, only when
 * the document is taller than the band; below, `.viewport` scrolls under the
 * sticky bar. `data-frame="fixed"` and the inner `.legal-doc` scroller went,
 * so the scrollbar sits at the window edge on every route alike.
 */

type LegalShellProps = {
  title: string;
  effective: string;
  /** Which legal route this is — marks the footer link / More-sheet row. */
  current: "privacy" | "terms";
  children: React.ReactNode;
};

export default function LegalShell({ title, effective, current, children }: LegalShellProps) {
  return (
    <div className="shell" data-view="legal">
      <AppNav activeTab={null} />

      <section className="view-scroll" data-view="legal" aria-label={title}>
        <div className="legal-page">
          <AppBackLink />
          <article className="select-text">
            <header className="view-head">
              <h1 className="view-title">{title}</h1>
              <p className="legal-meta">{effective}</p>
            </header>
            <div className="legal-copy">{children}</div>
          </article>
        </div>
      </section>

      <SiteFooter current={current} />
      <BottomTabBar activeTab={null} currentRoute={current} />
    </div>
  );
}

/** A single titled clause. Kept here so both routes get identical section rhythm. */
export function LegalSection({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <section className="legal-section">
      <h2 className="legal-heading">{heading}</h2>
      <p className="legal-text">{children}</p>
    </section>
  );
}
