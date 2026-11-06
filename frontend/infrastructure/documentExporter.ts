import { Capacitor } from "@capacitor/core";
import { Directory, Encoding, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import type { DocumentExporter, MarkdownDocument } from "@/domain/ports";

/* Refinement 1, #12/#13; refinement 2, #1. Two ways out for a finished
   analysis, both carrying the whole Markdown report.

   Browser: save is the old blob download, unchanged; share is the Web Share
   API with the report as text.

   Android (Capacitor): a blob `<a download>` does nothing — the WebView has no
   download listener, so the click is silently dropped. Save therefore writes
   the report to a real `<slug>.md` in the app's cache directory
   (@capacitor/filesystem) and opens the share sheet WITH THE FILE
   (@capacitor/share `files`), so the sheet offers "Save to Files", Drive and
   the like instead of "Sharing text". The share plugin turns the `file://` URI
   into a content URI through the app's FileProvider, whose `cache-path "."`
   (res/xml/file_paths.xml) already covers the cache root and every folder
   under it.

   If the file cannot be written or shared — most likely an APK built before
   `cap sync` registered the filesystem plugin — save falls back to sharing the
   text, which is what refinement 1 shipped: degraded, never dead.

   A dismissed share sheet rejects; that is the user's choice, not an error. */
const EXPORT_DIR = "exports";
/** Far below any filesystem's name limit, and still readable in a picker. */
const MAX_NAME = 80;

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
      await this.saveNative(doc);
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

  private async saveNative(doc: MarkdownDocument): Promise<void> {
    const name = `${doc.filename.slice(0, MAX_NAME).replace(/-+$/, "") || "videolens-notes"}.md`;
    let uri: string;
    try {
      ({ uri } = await Filesystem.writeFile({
        path: `${EXPORT_DIR}/${name}`,
        data: doc.text,
        directory: Directory.Cache,
        encoding: Encoding.UTF8,
        recursive: true,
      }));
    } catch {
      /* No filesystem plugin in this build, or the write failed: hand over
         the text so the button still does something useful. */
      try {
        await Share.share({ title: name, text: doc.text, dialogTitle: "Save notes" });
      } catch {
        /* dismissed */
      }
      return;
    }
    try {
      await Share.share({ title: name, files: [uri], dialogTitle: "Save notes" });
    } catch {
      /* dismissed, or no app could take the file */
    }
  }
}
