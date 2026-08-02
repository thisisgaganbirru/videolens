export default function OfflinePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-4 py-16">
      <img src="/icon-192.png" alt="" className="h-14 w-14" />
      <h1 className="mt-6 text-2xl font-semibold text-slate-100">You are offline</h1>
      <p className="mt-2 text-sm leading-6 text-slate-400">
        Video analysis requires a network connection. Reconnect, then return to your run.
      </p>
      <a href="/" className="mt-6 self-start text-sm text-indigo-300 hover:underline">
        Try again
      </a>
    </main>
  );
}
