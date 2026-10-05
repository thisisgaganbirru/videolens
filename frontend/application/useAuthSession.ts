"use client";

import { useCallback, useEffect, useState } from "react";
import type { AuthUser } from "@/domain/entities";
import { authSession } from "@/infrastructure/container";

/* The signed-in state as React sees it.

   `ready` flips once the provider has loaded (or refused to), so a panel can
   tell "nobody is signed in" from "we do not know yet" — the two render
   differently, and rendering the sign-in prompt for the frame before the
   session arrives is the flash this flag exists to prevent. On a deployment
   with no provider `ready` is true immediately and `user` is always null. */
export function useAuthSession() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(!authSession.enabled);

  useEffect(() => {
    if (!authSession.enabled) return;
    let cancelled = false;
    const sync = () => {
      if (!cancelled) setUser(authSession.user());
    };
    const unsubscribe = authSession.subscribe(sync);
    authSession
      .load()
      .catch(() => {
        /* A provider that will not load leaves the app anonymous. Nothing to
           say to the user: the account panel explains itself from `/api/me`. */
      })
      .finally(() => {
        if (cancelled) return;
        sync();
        setReady(true);
      });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const signIn = useCallback(() => {
    void authSession.signIn();
  }, []);

  const signOut = useCallback(() => {
    void authSession.signOut();
  }, []);

  return { enabled: authSession.enabled, ready, user, signIn, signOut };
}
