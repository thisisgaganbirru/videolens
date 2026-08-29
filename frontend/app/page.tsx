import { Suspense } from "react";
import HomeScreen, { RoutedHomeScreen } from "@/components/HomeScreen";

/* The Suspense boundary is a Next.js requirement, not a design choice, which is
   why it lives in `app/`: the active tab is a search param, and on a statically
   rendered route (every route here — the Capacitor build is `output: "export"`)
   Next resolves search params on the client and renders the nearest fallback
   into the prerendered HTML. Without a boundary `next build` fails.

   The fallback is a real Analyze shell rather than a spinner or `null`, so the
   prerendered HTML is the finished page for `/` — the overwhelmingly common
   entry point — instead of a placeholder that swaps in after hydration. The one
   honest cost: a deep link to `/?view=history` paints Analyze for the frame
   before hydration, because no static file can know the query string. */
export default function Page() {
  return (
    <Suspense fallback={<HomeScreen activeTab="analyze" />}>
      <RoutedHomeScreen />
    </Suspense>
  );
}
