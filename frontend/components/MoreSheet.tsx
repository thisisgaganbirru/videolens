"use client";

import type { MouseEvent, Ref } from "react";
import Link from "next/link";
import { ChevronRight, FileText, KeyRound, Moon, Shield, Tag, type LucideIcon } from "lucide-react";
import { isPlainLeftClick } from "@/components/navClick";
import { mainTabHref, type MainTab } from "@/application/useMainTab";

/* Hallmark · theme: editorial · component: bottom sheet (installed-app shell)
 * states: default · hover · focus · active · current · checked (theme switch)
 *
 * The More sheet from the App boards: everything the bottom tab bar has no
 * room for. A native modal <dialog>, opened with showModal() by BottomTabBar —
 * the platform supplies the top layer, the inert page behind it (focus stays
 * inside), Escape, and ::backdrop; this component adds the backdrop click.
 */

/** Which legal route this is, when it is one — so its row can be marked current. */
export type LegalRoute = "privacy" | "terms";

/**
 * One row. Three kinds, because the sheet holds three kinds of thing: a tab
 * that lives on `/app` (in-place navigation), a standalone route (a document
 * navigation, plain `<a>` so it also works from the offline page), and the
 * theme switch.
 */
export type MoreSheetRow =
  | { kind: "tab"; tab: MainTab; label: string; icon: LucideIcon }
  | { kind: "route"; route: LegalRoute; href: string; label: string; icon: LucideIcon }
  | { kind: "theme"; label: string; icon: LucideIcon };

/**
 * The sheet's contents, as data. Each inner array is a group; groups are
 * separated by a rule. A later tier (YouTube / Instagram connect) adds rows or
 * a group here — no markup changes needed for the common case.
 */
export const MORE_SHEET_GROUPS: MoreSheetRow[][] = [
  [
    { kind: "tab", tab: "api-key", label: "API key", icon: KeyRound },
    { kind: "tab", tab: "releases", label: "Releases", icon: Tag },
    { kind: "theme", label: "Dark theme", icon: Moon },
  ],
  [
    { kind: "route", route: "privacy", href: "/privacy", label: "Privacy", icon: Shield },
    { kind: "route", route: "terms", href: "/terms", label: "Terms", icon: FileText },
  ],
];

/** True when the current location is one of the sheet's own destinations. */
export function sheetOwnsLocation(activeTab: MainTab | null, currentRoute?: LegalRoute): boolean {
  if (currentRoute) return true;
  return MORE_SHEET_GROUPS.some((group) =>
    group.some((row) => row.kind === "tab" && row.tab === activeTab)
  );
}

type MoreSheetProps = {
  ref: Ref<HTMLDialogElement>;
  activeTab: MainTab | null;
  currentRoute?: LegalRoute;
  onSelectTab?: (tab: MainTab) => void;
  /** The theme as painted when the sheet opened, kept current by `onToggleTheme`. */
  dark: boolean;
  /** No stored choice: the theme is the device's (refinement 2, #3). */
  followsDevice: boolean;
  onToggleTheme: () => void;
  /** Fired by the dialog's own `close` event, however it closed. */
  onClose: () => void;
};

export default function MoreSheet({
  ref,
  activeTab,
  currentRoute,
  onSelectTab,
  dark,
  followsDevice,
  onToggleTheme,
  onClose,
}: MoreSheetProps) {
  /* The dialog has no padding of its own (it is on `.sheet-body`), so the only
     click whose target is the <dialog> element itself is one on ::backdrop. */
  const handleDialogClick = (event: MouseEvent<HTMLDialogElement>) => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  };

  const handleTabClick = (tab: MainTab) => (event: MouseEvent<HTMLAnchorElement>) => {
    event.currentTarget.closest("dialog")?.close();
    if (!onSelectTab || !isPlainLeftClick(event)) return;
    event.preventDefault();
    onSelectTab(tab);
  };

  const renderRow = (row: MoreSheetRow) => {
    const Icon = row.icon;
    const icon = (
      <span className="sheet-icon" aria-hidden="true">
        <Icon />
      </span>
    );

    if (row.kind === "theme") {
      return (
        <button type="button" role="switch" aria-checked={dark} className="sheet-row" onClick={onToggleTheme}>
          {icon}
          <span className="sheet-label">
            {row.label}
            {/* Says why the switch is already on (or off) before anyone
                touched it. Gone after the first press: that stores a choice. */}
            {followsDevice && <span className="sheet-sublabel">Following your device</span>}
          </span>
          <span className="switch" aria-hidden="true" />
        </button>
      );
    }

    if (row.kind === "tab") {
      return (
        <Link
          className="sheet-row"
          href={mainTabHref(row.tab)}
          aria-current={activeTab === row.tab ? "page" : undefined}
          onClick={handleTabClick(row.tab)}
        >
          {icon}
          <span className="sheet-label">{row.label}</span>
          <ChevronRight className="sheet-chevron" aria-hidden="true" />
        </Link>
      );
    }

    /* Plain <a>: the legal routes are also reached from /offline, which is
       served from the service-worker cache where a client-side navigation
       cannot resolve — the same reason the web footer uses plain anchors. */
    return (
      <a
        className="sheet-row"
        href={row.href}
        aria-current={currentRoute === row.route ? "page" : undefined}
      >
        {icon}
        <span className="sheet-label">{row.label}</span>
        <ChevronRight className="sheet-chevron" aria-hidden="true" />
      </a>
    );
  };

  return (
    <dialog
      ref={ref}
      id="more-sheet"
      className="sheet"
      aria-modal="true"
      aria-labelledby="more-sheet-title"
      onClick={handleDialogClick}
      onClose={onClose}
    >
      <div className="sheet-body">
        <span className="sheet-handle" aria-hidden="true" />
        <h2 id="more-sheet-title" className="sheet-title">
          More
        </h2>
        {MORE_SHEET_GROUPS.map((group, index) => (
          <ul key={index} className="sheet-list">
            {group.map((row) => (
              <li key={row.label}>{renderRow(row)}</li>
            ))}
          </ul>
        ))}
      </div>
    </dialog>
  );
}
