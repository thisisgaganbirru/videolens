import type { Metadata } from "next";
import LegalShell, { LegalSection } from "@/components/LegalShell";

export const metadata: Metadata = {
  title: "Terms",
  description:
    "The terms for using VideoLens AI: what you may submit, prohibited use, your own Gemini key, the paid plan, generated results and availability.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <LegalShell title="Terms" effective="Effective November 13, 2026" current="terms">
      <LegalSection heading="Permission to process">
        You may submit only media you own or are authorized to process. You are responsible for complying with copyright, privacy, contractual, and platform requirements.
      </LegalSection>
      <LegalSection heading="Prohibited use">
        Do not use the service to bypass access controls, process unlawful material, invade privacy, or overload the service. Private or login-only links are not guaranteed to work. We may limit, suspend or block access, including accounts and devices, that break these terms or put the service or other users at risk.
      </LegalSection>
      <LegalSection heading="Your own Gemini key">
        If you add your own Google Gemini API key, it is stored only in your browser and sent with your requests so we can run your analysis. We do not store it. You are responsible for keeping it safe, for all usage and charges on your Google account, and for complying with Google&apos;s terms.
      </LegalSection>
      {/* Draft for the owner's legal review (docs/frontend/billing.md). */}
      <LegalSection heading="Paid plan">
        The paid plan is a subscription, billed monthly or yearly, that renews automatically at the end of each period until you cancel. You can cancel at any time under Account, in Manage billing; you keep the paid plan until the end of the period you have paid for, and it does not renew after that. The plan includes a set number of runs each day (UTC). Runs beyond that daily allowance are billed per run, at the price shown at checkout, on your next invoice, up to a fixed number of extra runs each calendar month; past that limit, extra runs stop until the next month, and the included runs still come back each day. Runs made with your own Gemini key do not count toward the allowance. Except where the law requires otherwise, we do not refund partial periods. If we change the price, we will tell you before your next renewal, and the new price applies from that renewal on. Deleting your account cancels your subscription immediately. Payments are handled by Stripe.
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
