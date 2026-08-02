export default function TermsPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16 text-slate-300">
      <a href="/" className="text-sm text-indigo-300 hover:underline">VideoLens AI</a>
      <h1 className="mt-6 text-3xl font-semibold text-slate-100">Terms of Use</h1>
      <p className="mt-2 text-sm text-slate-500">Effective August 1, 2026</p>
      <div className="mt-8 space-y-6 text-sm leading-7">
        <section>
          <h2 className="text-lg font-semibold text-slate-100">Permission to process</h2>
          <p className="mt-2">You may submit only media you own or are authorized to process. You are responsible for complying with copyright, privacy, contractual, and platform requirements.</p>
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-100">Prohibited use</h2>
          <p className="mt-2">Do not use the service to bypass access controls, process unlawful material, invade privacy, or overload the service. Private or login-only links are not guaranteed to work.</p>
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-100">Generated results</h2>
          <p className="mt-2">Transcripts and analyses may contain errors. Review important output before relying on or publishing it.</p>
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-100">Availability</h2>
          <p className="mt-2">The service is provided without a guarantee of uninterrupted availability. Limits may be applied to protect capacity, cost, and other users.</p>
        </section>
      </div>
    </main>
  );
}
