import type { Metadata } from "next";
import LegalShell, { LegalSection } from "@/components/LegalShell";

export const metadata: Metadata = {
  title: "Terms",
  description:
    "The terms for using VideoLens AI: what you may submit, prohibited use, generated results and availability.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <LegalShell title="Terms" effective="Effective August 1, 2026" current="terms">
      <LegalSection heading="Permission to process">
        You may submit only media you own or are authorized to process. You are responsible for complying with copyright, privacy, contractual, and platform requirements.
      </LegalSection>
      <LegalSection heading="Prohibited use">
        Do not use the service to bypass access controls, process unlawful material, invade privacy, or overload the service. Private or login-only links are not guaranteed to work.
      </LegalSection>
      <LegalSection heading="Generated results">
        Transcripts and analyses may contain errors. Review important output before relying on or publishing it.
      </LegalSection>
      <LegalSection heading="Availability">
        The service is provided without a guarantee of uninterrupted availability. Limits may be applied to protect capacity, cost, and other users.
      </LegalSection>
    </LegalShell>
  );
}
