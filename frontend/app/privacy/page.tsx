export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16 text-slate-300">
      <a href="/" className="text-sm text-indigo-300 hover:underline">VideoLens AI</a>
      <h1 className="mt-6 text-3xl font-semibold text-slate-100">Privacy Policy</h1>
      <p className="mt-2 text-sm text-slate-500">Effective August 1, 2026</p>
      <div className="mt-8 space-y-6 text-sm leading-7">
        <section>
          <h2 className="text-lg font-semibold text-slate-100">Media processing</h2>
          <p className="mt-2">Uploaded or downloaded media is used only to perform the requested analysis. Media is temporarily processed by our backend and Gemini, then deleted after the run finishes or fails.</p>
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-100">Information retained</h2>
          <p className="mt-2">Run status and analysis results may be retained for up to one hour. We also process a random client identifier for quotas and access control, plus limited operational logs needed for security and reliability.</p>
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-100">Third-party services</h2>
          <p className="mt-2">Media analysis uses Google Gemini. Public-link processing may contact the website hosting the submitted URL. Those providers process data under their own policies.</p>
        </section>
        <section>
          <h2 className="text-lg font-semibold text-slate-100">Contact</h2>
          <p className="mt-2">Before public release, replace this section with the verified operator contact address used in the store listing.</p>
        </section>
      </div>
    </main>
  );
}
