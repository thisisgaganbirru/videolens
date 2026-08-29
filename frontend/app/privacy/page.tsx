import LegalShell, { LegalSection } from "@/components/LegalShell";

export default function PrivacyPage() {
  return (
    <LegalShell title="Privacy Policy" effective="Effective August 1, 2026" current="privacy">
      <LegalSection heading="Media processing">
        Uploaded or downloaded media is used only to perform the requested analysis. Media is temporarily processed by our backend and Gemini, then deleted after the run finishes or fails.
      </LegalSection>
      <LegalSection heading="Information retained">
        Run status and analysis results may be retained for up to one hour. We also process a random client identifier for quotas and access control, plus limited operational logs needed for security and reliability.
      </LegalSection>
      <LegalSection heading="Third-party services">
        Media analysis uses Google Gemini. Public-link processing may contact the website hosting the submitted URL. Those providers process data under their own policies.
      </LegalSection>
      <LegalSection heading="Contact">
        Before public release, replace this section with the verified operator contact address used in the store listing.
      </LegalSection>
    </LegalShell>
  );
}
