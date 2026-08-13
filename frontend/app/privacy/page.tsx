export default function PrivacyPage() {
  return (
    <main className="page-shell max-w-2xl py-8 sm:py-12 md:py-16">
      <a href="/" className="text-link text-sm font-medium">VideoLens AI</a>
      <h1 className="mt-5 text-3xl font-semibold tracking-[-0.025em] text-[var(--color-text-strong)] sm:text-4xl">Privacy Policy</h1>
      <p className="mt-2 text-sm text-[var(--color-faint)]">Effective August 1, 2026</p>
      <div className="legal-copy mt-8 space-y-7 text-base leading-7 text-[var(--color-text)]">
        <section>
          <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">Media processing</h2>
          <p className="mt-2">Uploaded or downloaded media is used only to perform the requested analysis. Media is temporarily processed by our backend and Gemini, then deleted after the run finishes or fails.</p>
        </section>
        <section>
          <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">Information retained</h2>
          <p className="mt-2">Run status and analysis results may be retained for up to one hour. We also process a random client identifier for quotas and access control, plus limited operational logs needed for security and reliability.</p>
        </section>
        <section>
          <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">Third-party services</h2>
          <p className="mt-2">Media analysis uses Google Gemini. Public-link processing may contact the website hosting the submitted URL. Those providers process data under their own policies.</p>
        </section>
        <section>
          <h2 className="text-xl font-semibold text-[var(--color-text-strong)]">Contact</h2>
          <p className="mt-2">Before public release, replace this section with the verified operator contact address used in the store listing.</p>
        </section>
      </div>
    </main>
  );
}
