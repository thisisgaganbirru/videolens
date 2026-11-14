import type { Metadata } from "next";
import LegalShell, { LegalSection } from "@/components/LegalShell";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "How VideoLens AI handles your media, what the server keeps for an hour, what it keeps for the paid plan, and what stays only in your browser.",
  alternates: { canonical: "/privacy" },
};

export default function PrivacyPage() {
  return (
    <LegalShell title="Privacy" effective="Effective November 13, 2026" current="privacy">
      <LegalSection heading="Media processing">
        Uploaded or downloaded media is used only to perform the requested analysis. Media is temporarily processed by our backend and Gemini, then deleted after the run finishes or fails.
      </LegalSection>
      <LegalSection heading="Information retained">
        Our server keeps a run, its status and its analysis result for about one hour after the run starts, long enough to deliver the result to you, and then deletes it. We also process a random client identifier, created in your browser, that scopes which runs your browser can see, plus limited operational logs needed for security and reliability. To count free runs, this browser also keeps a random device token that our server issues; it is not linked to you, and the server uses it only to count that device&apos;s free runs each day.
      </LegalSection>
      <LegalSection heading="Your History">
        Your History (the titles, summaries, thumbnails and full results of your recent runs) is stored only in this browser, using its on-device storage (IndexedDB), and is never sent back to us. It keeps your 20 most recent runs and drops the oldest first. Clearing this site&apos;s data in your browser removes it. Your browser may also clear it on its own: Safari, for example, can remove it after seven days without a visit unless VideoLens is added to your Home Screen.
      </LegalSection>
      <LegalSection heading="Your own Gemini key">
        Your key is stored in this browser or app only. When you start a run, it is sent with that request, held in memory only until the run calls Gemini, and then discarded. It is never written to our database or logs.
      </LegalSection>
      <LegalSection heading="Signing in">
        Signing in is optional; everything above works without it. If you sign in, our sign-in provider (Supabase) keeps your email address so it can send you one-time codes, and our server keeps a small account record: an internal identifier, your email, a personal workspace and the date you joined. It also keeps a count of the free runs your account has used each day. If you create API keys, the server keeps each key&apos;s name, its first few characters, when it was created, last used and revoked, and a one-way fingerprint of the key, never the key itself. Your session is stored in this browser and is removed when you sign out. Signing in does not move your History or your own Gemini key out of this browser. You can delete your account yourself at any time under Account: that immediately removes the account record, its workspace, your API keys, any runs the server still holds for you, and your sign-in at our provider. Copies of your email address can remain for up to about 7 days in our provider&apos;s daily database backups and sign-in logs, and our hosting provider keeps server logs for at least 7 days, until they expire. It does not touch your History or Gemini key, which stay in this browser until you remove them.
      </LegalSection>
      {/* Draft for the owner's legal review (docs/frontend/billing.md). */}
      <LegalSection heading="Payments">
        The paid plan is optional. Payments are processed by Stripe; we never see or store your card number. You enter your card on Stripe&apos;s own checkout page, and Stripe keeps its payment records under its own privacy policy. For a paid account our server keeps your Stripe customer and subscription IDs, your plan status and renewal date, a count of your runs each day, and a count of your extra runs each month. Deleting your account first cancels any subscription immediately, with no refund for the rest of the period, and then removes these billing records from our server; Stripe keeps its customer record of your payments, as it needs to for invoices and tax.
      </LegalSection>
      <LegalSection heading="Third-party services">
        Media analysis uses Google Gemini; payments for the paid plan use Stripe. Public-link processing may contact the website hosting the submitted URL. Those providers process data under their own policies.
      </LegalSection>
      <LegalSection heading="Contact">
        Before public release, replace this section with the verified operator contact address used in the store listing.
      </LegalSection>
    </LegalShell>
  );
}
