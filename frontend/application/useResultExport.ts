"use client";

import { useCallback, useSyncExternalStore } from "react";
import type { MarkdownDocument } from "@/domain/ports";
import { documentExporter } from "@/infrastructure/container";

const noSubscribe = () => () => {};

/**
 * Share and save for a finished result (refinement 1, #12/#13). Both hand over
 * the same whole-report Markdown; the component builds the document, this hook
 * decides nothing but which adapter call to make.
 *
 * `canShare` / `savesViaShareSheet` are platform facts that never change
 * during a page's life, read with `useSyncExternalStore` so the prerendered
 * HTML (server snapshot: false) and the client agree without a
 * set-state-in-effect.
 */
export function useResultExport() {
  const canShare = useSyncExternalStore(noSubscribe, () => documentExporter.canShare(), () => false);
  const savesViaShareSheet = useSyncExternalStore(
    noSubscribe,
    () => documentExporter.savesViaShareSheet(),
    () => false,
  );
  const share = useCallback((doc: MarkdownDocument) => documentExporter.share(doc), []);
  const save = useCallback((doc: MarkdownDocument) => documentExporter.save(doc), []);
  return { canShare, savesViaShareSheet, share, save };
}
