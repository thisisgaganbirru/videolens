export default function OfflinePage() {
  return (
    <main className="page-shell flex min-h-[calc(100dvh-var(--safe-top)-var(--safe-bottom))] max-w-lg flex-col justify-center py-10">
      <img src="/icon-192.png" alt="" className="h-14 w-14" />
      <h1 className="mt-6 text-3xl font-semibold tracking-[-0.025em] text-[var(--color-text-strong)]">You are offline</h1>
      <p className="mt-3 text-base leading-7 text-[var(--color-muted)]">
        Video analysis requires a network connection. Reconnect, then return to your run.
      </p>
      <a href="/" className="button-primary mt-6 self-start">
        Try again
      </a>
    </main>
  );
}
