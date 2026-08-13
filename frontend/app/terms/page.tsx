export default function TermsPage() {
  return (
    <main className="page-shell max-w-2xl py-8 sm:py-12 md:py-16">
      <a href="/" className="text-link text-sm font-medium">VideoLens AI</a>
      <h1 className="mt-5 text-3xl font-semibold tracking-[-0.025em] text-[var(--color-text-strong)] sm:text-4xl">Terms of Use</h1>
      <p className="mt-2 text-sm text-[var(--color-faint)]">Effective August 1, 2026</p>
      <div className="legal-copy mt-8 space-y-7 text-base leading-7 text-[var(--color-text)]">
        <section>
          <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">Permission to process</h2>
          <p className="mt-2">You may submit only media you own or are authorized to process. You are responsible for complying with copyright, privacy, contractual, and platform requirements.</p>
        </section>
        <section>
          <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">Prohibited use</h2>
          <p className="mt-2">Do not use the service to bypass access controls, process unlawful material, invade privacy, or overload the service. Private or login-only links are not guaranteed to work.</p>
        </section>
        <section>
          <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">Generated results</h2>
          <p className="mt-2">Transcripts and analyses may contain errors. Review important output before relying on or publishing it.</p>
        </section>
        <section>
          <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">Availability</h2>
          <p className="mt-2">The service is provided without a guarantee of uninterrupted availability. Limits may be applied to protect capacity, cost, and other users.</p>
        </section>
      </div>
    </main>
  );
}
