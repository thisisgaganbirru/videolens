"use client";

import type { ComponentProps } from "react";
import AppNav from "@/components/AppNav";
import { useAccountEntry } from "@/application/useAccountEntry";

/* The shared top bar for routes other than `/app` (landing, Privacy, Terms,
 * 404): `AppNav` with the Account entry resolved here, since those routes are
 * server components with no shell that reads the session or capabilities.
 * Prerendered with no entry; it appears client-side once both reads answer.
 * `/app` renders `AppNav` directly with HomeScreen's own reads. */
type RouteNavProps = Omit<ComponentProps<typeof AppNav>, "showAccount" | "accountState" | "accountInitial">;

export default function RouteNav(props: RouteNavProps) {
  const entry = useAccountEntry();
  return <AppNav {...props} {...entry} />;
}
