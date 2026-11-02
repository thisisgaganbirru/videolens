import { Capacitor } from "@capacitor/core";
import { Share } from "@capacitor/share";
import type { DocumentExporter, MarkdownDocument } from "@/domain/ports";

/* Refinement 1, #12/#13. Two ways out for a finished analysis, both carrying
   the whole Markdown report.

   Browser: save is the old blob download, unchanged; share is the Web Share
   API with the report as text.

   Android (Capacitor): a blob `<a download>` does nothing — the WebView has no
   download listener, so the click is silently dropped. That was the bug. The
   installed plugins are @capacitor/app and @capacitor/share; neither writes a
   file. So save opens the share sheet with the report text, where "Save to
   Drive", Files, a notes app or email all take it. A real `.md` file would
   need @capacitor/filesystem (`Filesystem.writeFile` into `Directory.Cache`,
   then `Share.share({ files: [uri] })`) plus `cap sync` — deliberately not
   added in this pass.

   A dismissed share sheet rejects; that is the user's choice, not an error. */
export class CapacitorDocumentExporter implements DocumentExporter {
  private native(): boolean {
    try {
      return Capacitor.isNativePlatform();
    } catch {
      return false;
    }
  }

  canShare(): boolean {
    return this.native() || typeof navigator.share === "function";
  }

  savesViaShareSheet(): boolean {
    return this.native();
  }

  async share(doc: MarkdownDocument): Promise<void> {
    try {
      if (this.native()) {
        await Share.share({ title: doc.title, text: doc.text, dialogTitle: "Share notes" });
      } else if (typeof navigator.share === "function") {
        await navigator.share({ title: doc.title, text: doc.text });
      }
    } catch {
      /* dismissed, or the platform refused */
    }
  }

  async save(doc: MarkdownDocument): Promise<void> {
    if (this.native()) {
      try {
        await Share.share({ title: `${doc.filename}.md`, text: doc.text, dialogTitle: "Save notes" });
      } catch {
        /* dismissed */
      }
      return;
    }
    const blob = new Blob([doc.text], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${doc.filename}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }
}
