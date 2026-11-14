"use client";

import type { ComponentProps } from "react";
import BottomTabBar from "@/components/BottomTabBar";
import { useAccountEntry } from "@/application/useAccountEntry";

/* The installed-app dock for routes other than `/app`, with the Account item
 * under the same gate as everywhere (useAccountEntry; the capability read is
 * shared with RouteNav, one request per page load). */
type RouteTabBarProps = Omit<ComponentProps<typeof BottomTabBar>, "showAccount">;

export default function RouteTabBar(props: RouteTabBarProps) {
  const { showAccount } = useAccountEntry();
  return <BottomTabBar {...props} showAccount={showAccount} />;
}
