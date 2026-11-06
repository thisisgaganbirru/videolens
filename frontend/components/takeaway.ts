/**
 * Splits a TL;DR into its key takeaway (the first sentence, or the first line
 * when the model wrote lines) and the rest. Pure: no React, no DOM.
 *
 * Sentence boundaries come from `Intl.Segmenter` with the `ss-standard`
 * suppressions (so "e.g." and "Dr." do not end a sentence and "3.5" never
 * does), followed by our own merge pass over a short abbreviation list, because
 * suppression data varies by engine. Without `Intl.Segmenter` (old WebViews), a
 * conservative regex fallback only breaks after . ! ? followed by whitespace and
 * an uppercase letter, digit or opening quote, with the same merge pass.
 */

const ABBREVIATIONS = [
  "e.g.", "i.e.", "etc.", "vs.", "cf.", "approx.", "incl.", "esp.", "no.", "fig.",
  "mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "jr.", "sr.", "inc.", "ltd.", "co.",
  "u.s.", "u.k.", "a.m.", "p.m.", "min.", "sec.", "hr.", "hrs.",
];

function endsWithAbbreviation(text: string): boolean {
  const trimmed = text.trimEnd().toLowerCase();
  if (ABBREVIATIONS.some((abbr) => trimmed.endsWith(` ${abbr}`) || trimmed === abbr || trimmed.endsWith(`(${abbr}`))) {
    return true;
  }
  // A single initial ("J. Smith") is not a sentence end either.
  return /(^|\s)[a-z]\.$/i.test(trimmed);
}

function rawSentences(text: string): string[] {
  const Segmenter = (Intl as unknown as { Segmenter?: typeof Intl.Segmenter }).Segmenter;
  if (Segmenter) {
    try {
      const segmenter = new Segmenter("en-u-ss-standard", { granularity: "sentence" });
      return Array.from(segmenter.segment(text), (part) => part.segment);
    } catch {
      /* fall through to the regex */
    }
  }
  return text.split(/(?<=[.!?]["”’)]?\s+)(?=["“(]?[A-Z0-9])/);
}

/** Sentences, with any split after an abbreviation or initial glued back. */
export function sentences(text: string): string[] {
  const merged: string[] = [];
  for (const part of rawSentences(text)) {
    if (merged.length > 0 && endsWithAbbreviation(merged[merged.length - 1])) {
      merged[merged.length - 1] += part;
    } else {
      merged.push(part);
    }
  }
  return merged.map((part) => part.trim()).filter(Boolean);
}

export interface SplitSummary {
  /** The first sentence (or line); null when the summary is empty. */
  takeaway: string | null;
  /** Everything after it, trimmed; empty when the summary is one sentence. */
  rest: string;
}

export function splitTakeaway(summary: string | null | undefined): SplitSummary {
  const text = (summary ?? "").trim();
  if (!text) return { takeaway: null, rest: "" };

  // The model sometimes writes the TL;DR as lines; the first line is then the
  // unit, unless it is itself several sentences, in which case its first one.
  const newline = text.indexOf("\n");
  const firstLine = newline === -1 ? text : text.slice(0, newline).trim();
  const takeaway = sentences(firstLine)[0] ?? firstLine;

  // Cut at the takeaway's position in the original so the rest keeps its own
  // line breaks and spacing exactly.
  const at = text.indexOf(takeaway);
  const rest = at === -1 ? text.slice(firstLine.length) : text.slice(at + takeaway.length);
  return { takeaway, rest: rest.trim() };
}
