# VideoLens redesign: handoff

Design canvas: https://claude.ai/artifact/Ttdw94J5sgmBaunDVvHnDL (private, owner only). Boards are named "Desktop - X", "Web - X" (phone browser) and "App - X" (installed app). Treat the canvas as the visual source of truth and this file as the rules around it.

## What to build

A calm editorial look: warm paper background, near-black ink, one green accent, red for errors only. Hanken Grotesk for UI, Newsreader for headlines and notes. Replace the Terminal theme. Tokens are in `tokens.css` (draft). Map them onto the existing names in `frontend/app/tokens.css` first, then restyle in place.

## Product rules the design assumes

- No login and no accounts. All user state (History, key, settings) lives in the browser.
- The app works without an API key. A visitor gets a few free runs. After that they bring their own Gemini key. The number of free runs is a placeholder (3 on the boards).
- A paid tier that connects YouTube and Instagram is planned later. It is not designed. Keep the More sheet and the API key page easy to extend.
- History is capped at 20 items.
- Files are deleted from the server as soon as a run finishes (existing copy, keep it).

## Screens

Desktop (1280): Intake, Results (Notes, TL;DR, Transcript, On-screen), Progress, Failed, Connection lost, History, API key, Releases, Privacy, Terms, Offline, Landing. Dark versions exist for Intake, Results (Notes) and History only.

Phone browser ("Web"): same set, plus the full-screen Menu. Top bar with logo, theme toggle, hamburger. Footer with Privacy and Terms. No bottom bar.

Installed app ("App"): Splash, Welcome, Intake with free runs left, Intake with free runs used, then the same pages. Bottom tab bar with Analyze, History, More. More opens a sheet with API key, Releases, dark theme switch, Privacy, Terms. No footer.

Choose the nav by display mode: `display-mode: standalone` (PWA) or the Capacitor platform check shows the app layout. A normal browser tab shows the web layout.

## Key patterns

- Progress is a four-frame filmstrip: Downloading, Normalizing, Uploading, Analyzing. Done frames are soft green with a check. The active frame has a scan line. Waiting is dark. Failed shows a red frame with an X on the step that stopped. Connection lost shows a dashed neutral frame, not red. Phone layout stacks the frames vertically.
- History is a poster grid: 5 columns on desktop, 2 on phone, 3:4 posters, platform chip top left, duration chip bottom right, title and date under. Landscape items (regular YouTube videos) use `grid-column: span 2` and a 16:9 thumbnail. Use `grid-auto-flow: row dense` and `align-items: start`.
- Results use a segmented tab row. Notes and TL;DR are serif prose. Transcript is timestamped rows with a search box and a timestamps switch. On-screen is a list of frame thumbnails with the extracted text.
- Touch targets are at least 44px. Focus ring is a 2px green outline with 2px offset.

## Placeholder content to replace

- Sample result ("A week of lunches...") and all History items are invented.
- Releases entries and version numbers are invented.
- Privacy and Terms text is sample copy.
- The API key page says the key is stored in the browser only. Confirm that is true before keeping it.
- "Trying again in 8 seconds" on Connection lost needs a real countdown or different copy.
- History thumbnails are flat tinted placeholders until the app stores real thumbnails.

## Not designed yet

Dark mode for the error screens, the pages added after the first dark round, and all mobile. The paid tier. A first-run flow for the web (the landing page covers the marketing side).

## Repo rules to respect (from CLAUDE.md)

Never run build:mobile, android or gradle locally; CI does it. Update docs/ and mem/ entries. Keep `agentRules: false`. Work on a feature branch, then dev, then main. Show a plan before changing anything.

## First prompt to give Claude Code

> Read design-handoff.md and tokens.css. Do not change code yet. Answer the questions below against this repo, then give me a phased plan (tokens and shell first, then screens, then new features) with the files each phase touches.

## Questions to answer first

Free runs with no login
1. How would you count free runs per visitor without accounts? Compare a signed device ID cookie, IP-based limits and a mix, and say how easy each is to bypass.
2. Where should the count be enforced, in the FastAPI backend or the client? What happens if someone clears storage or uses a private window?
3. What should the API return when free runs are used up so the frontend can show the "free runs used" state? Which status code and error shape fit the current error handling?
4. How is the user's own Gemini key sent with a request and where is it stored? Check it is never logged or persisted server-side.
5. What is a sensible free-run limit given Gemini cost per run? Show the math from the current pipeline.

History without accounts
6. What is stored per history item today, and which fields are new (thumbnail, duration, platform, status, summary snippet)?
7. Can yt-dlp return a thumbnail and duration for links? What do we show for uploaded files? Where should thumbnails be stored so they do not fill browser storage?
8. How should failed runs appear in History, and do they count toward the 20?

Nav and app shell
9. How do we detect the installed PWA or Capacitor app versus a phone browser to pick the nav? Does the current AppNav and routing allow this without a rewrite?
10. Does a landing page at `/` fit the routes, with the tool moving to `/app`? What breaks for existing links, the service worker and the offline page?
11. How do the splash and welcome screens fit the PWA manifest and Capacitor setup?

Design mapping
12. Map the new tokens onto tokens.css. What can be renamed, what must stay, how does dark mode map?
13. Which components can be restyled in place and which need a new structure (HomeScreen, UploadForm, RunStatusView, ResultsView, AppNav, the three panels)?
14. Which backend step names drive the filmstrip, and what should the UI show if a step is skipped or fails midway?

Process
15. Which repo rules apply, and what is the safest phase order?
