import LegalShell, { LegalSection } from "@/components/LegalShell";

export default function PrivacyPage() {
  return (
    <LegalShell title="Privacy" effective="Effective August 1, 2026" current="privacy">
      <LegalSection heading="Media processing">
        Uploaded or downloaded media is used only to perform the requested analysis. Media is temporarily processed by our backend and Gemini, then deleted after the run finishes or fails.
      </LegalSection>
      <LegalSection heading="Information retained">
        Our server keeps a run, its status and its analysis result for about one hour after the run starts, long enough to deliver the result to you, and then deletes it. We also process a random client identifier, created in your browser, that scopes which runs your browser can see, plus limited operational logs needed for security and reliability. To count free runs, this browser also keeps a random device token that our server issues; it is not linked to you, and the server uses it only to count that device&apos;s free runs each day.
      </LegalSection>
      <LegalSection heading="Your History">
        Your History (the titles, summaries, thumbnails and full results of your recent runs) is stored only in this browser, using its on-device storage (IndexedDB), and is never sent back to us. It keeps your 20 most recent runs and drops the oldest first. Clearing this site&apos;s data in your browser removes it. Your browser may also clear it on its own: Safari, for example, can remove it after seven days without a visit unless VideoLens is added to your Home Screen.
      </LegalSection>
      <LegalSection heading="Signing in">
        Signing in is optional; everything above works without it. If you sign in, our sign-in provider (Supabase) keeps your email address so it can send you one-time codes, and our server keeps a small account record: an internal identifier, your email, a personal workspace and the date you joined. If you create API keys, the server keeps each key&apos;s name, its first few characters, when it was created, last used and revoked, and a one-way fingerprint of the key, never the key itself. Your session is stored in this browser and is removed when you sign out. Signing in does not move your History or your own Gemini key off this device.
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
