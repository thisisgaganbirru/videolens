# Legal and offline routes

The three standalone pages that render *outside* the app shell: `/privacy`,
`/terms`, and the service worker's `/offline` fallback.

**Files**
- `frontend/components/LegalShell.tsx` — the shared frame for the two *documents*: `AppNav`, a `.view-scroll` section holding the `.legal-page` column (crumb bar, title, effective date, clauses), footer, plus the `LegalSection` clause wrapper.
- `frontend/components/AppBackLink.tsx` — the Back link `LegalShell` renders above the title; on Privacy and Terms it shows in every shell since refinement 10 (see Phase 4 layout).
- `frontend/components/AppNav.tsx` — the nav band. All three routes render it; see `app-shell-layout.md`.
- `frontend/components/ThemeToggle.tsx` — the theme button, rendered inside `AppNav`, so it is literally the same control on every route rather than a lookalike. Exports `toggleTheme()` too.
- `frontend/app/privacy/page.tsx` — privacy copy only.
- `frontend/app/terms/page.tsx` — terms copy only.
- `frontend/app/offline/page.tsx` — offline fallback, served by the service worker. Carries the same chrome, rendered directly rather than via `LegalShell` (see below).
- `frontend/sw/sw.template.js` — **the service worker source**. Decides which route a failed navigation actually resolves to; see "What the service worker serves offline".
- `frontend/scripts/build-sw.mjs` — generates the served worker from that template after every build.
- `frontend/public/sw.js` — **generated, gitignored.** Do not edit.
- `frontend/components/ServiceWorkerRegistration.tsx` — registers `/sw.js` in production only. In dev (`NODE_ENV !== "production"`) it instead unregisters every registration on the origin and deletes the `videolens-shell-*` caches, because a worker left by an earlier production build on the same origin (e.g. `localhost:3005`) otherwise keeps serving stale cached chunks cache-first and the dev page runs old code (seen 2026-11-13: the Account tab missing on `npm run dev`).

All three are **server components**; `ThemeToggle` is the only `"use client"`
island. All routes are statically prerendered.

## Chrome is the app's chrome — not a standalone-route variant

**This is a project-wide rule, not a detail of these routes: the footer and nav
are identical on every page.** A standalone route is still the same
application, so it does not get its own furniture. All three routes reuse the
exact classes and markup `HomeScreen` renders — `.shell` frame with
`data-frame="fixed"`, the same `<AppNav />` component (brand, all four tabs,
mobile drawer, `ThemeToggle`), and `.page-end > .foot` with the `VideoLens AI`
span left and the `.foot-legal` Privacy/Terms nav right.

There is **no exception left**. `LegalShell` and `/offline` both render
`<AppNav activeTab={null} />` — `null` because on a legal or offline route none
of the four tabs is where you are, so none carries `aria-current`. This was only
possible once the tabs moved into the URL (`/?view=…`); see `app-shell-layout.md`
§ Tab routing.

Because the frame *is* `.shell`, width, gutters and safe-area handling match the
app exactly rather than being re-derived. `.legal-body` spans full container width (`max-width: 100%`) so document paragraphs fill the shell width. Measured, not eyeballed: `/`,
`/?view=history`, `/privacy` and `/offline` return **identical**
`getBoundingClientRect` values for `.shell`, `.nav`, `.foot` and
`.theme-toggle` at 1440x900 (`shell 176/0/1088/900`, `nav 184/16/1072/52.7`,
`foot y:856.1 w:1056`, toggle `32x32`) and at 390x844 (`shell 0/0/390/844`,
`nav 8/16/374/62`, `foot y:800.1 w:358`, toggle `44x44`), in **both** themes,
plus iPhone 13 touch emulation (`foot y:620.1`, toggle `44x44`). All four
routes now agree at 390px — the 16px footer discrepancy is fixed, see below.

### Why `/offline` renders the chrome directly instead of sharing a frame component

Considered and rejected: extracting nav *and footer* into a `StandaloneFrame`
that both `LegalShell` and `/offline` render through. That would have unified
two of the three sites while leaving `HomeScreen` — the one that *defines* the
target — outside it, creating a second canonical form free to drift from the
app as a unit.

The nav half of that objection is gone: `AppNav` is the extraction, and
`HomeScreen` is one of its three callers, so there is exactly one nav. What
remains un-extracted is the footer band and the `.shell` scaffolding, and the
original reasoning still holds for those — a frame shared by only the
non-`HomeScreen` routes would be a second canonical form. The shared vocabulary
for them is `globals.css`.

`LegalShell` stays an abstraction over `/privacy` and `/terms` because those are
one document *type* sharing a body shape, not because they are both
"standalone".

`/offline` keeps the app's centred `.home-center` + `.run-state` idiom: it is a
blocking state, not a document, so it gets neither the crumb bar nor the
scrolling `.legal-doc`.

### Why `/offline` renders live tabs that can land back on `/offline`

`/offline` renders the full four-tab nav like every other route. Tapping
History there produces `/?view=history`, which the service worker deliberately
answers with `/offline` again (see the policy below), so you land back where you
started.

That was considered and kept, deliberately:

- It is an **honest answer**. "Show me my history" with no network has exactly
  one true reply, and the page gives it. A loop back to a page that explains the
  situation is not a dead end; a dead end is a control that does nothing.
- The links are **not decorative**. They are real navigations that start
  resolving normally the instant connectivity returns — and returning to
  connectivity is the single most likely thing to happen while this page is on
  screen. Rendering them disabled would be a lie in the other direction: the
  page cannot know when the network is back, so it would have to stay
  permanently wrong.
- The alternative costs more. A route whose chrome visibly differs from every
  other route breaks the project-wide rule in a way users can see at a glance,
  to avoid a loop they only discover by tapping.

The one thing that is **not** acceptable and is not done: rendering the tabs
looking live while they cannot act. Since the shell's JS is now precached
(below), React genuinely hydrates offline — the drawer opens, the toggle
toggles, the tabs navigate. Verified offline at 390x844: drawer `0/0/272/844`,
theme toggle flips and persists, tapping History reaches `/?view=history`.

## Phase 4 layout (2026-11-01, `design/phase4-boards/{Privacy,Terms,Offline}*.png`) — supersedes "The measure", "Fixed frame" and "Layout" below

Built to the owner's boards in `design/phase4-boards/` (the first pass that
day had extrapolated without them). **The crumb bar is gone**: the boards draw
none, and the shared nav/footer/More sheet are the way back. That reverses the
earlier record of the crumb bar as "the user's call" — the boards are the
owner's later word; flag it if that was not intended. Any section below that
describes the crumb bar is history; all `.crumb-*` CSS is deleted.
The three sections below describe the Terminal-era `.legal-doc`/`.page-title`/
`.home-center` implementation and are kept for history only — those classes
are deleted from `globals.css`.

- **Scroll model.** `data-frame="fixed"` is dropped from all three routes.
  Each renders `<section class="view-scroll">`, the same scroller Analyze,
  History, API key and Releases use (`.shell > main.view-scroll` in
  `globals.css`): from 32rem it is the full-bleed region between the fixed nav
  and footer, `overflow-y: auto` so a short page shows no scrollbar; below
  32rem `.viewport` scrolls. Measured at 1366×900, 390×844 web and app, both
  themes: no document scroll, no horizontal scroll.
- **Legal** (`LegalShell`): `.legal-page` (the centred 43.5rem column shared
  with `.key-page`/`.releases`) → `<article>` with `.view-head`
  (`h1.view-title` "Privacy" / "Terms" — retitled from "Privacy Policy" /
  "Terms of Use" per the boards) and `.legal-meta` directly under it →
  `.legal-copy` (capped at `--measure`, 30px between sections, **no rules**).
  `LegalSection` renders `section.legal-section > h2.legal-heading`
  (Newsreader 24→28px) `+ p.legal-text` (17/1.65, ink-2, 4px under its
  heading). Deviations: the meta line keeps "Effective <date>" (currently November 13, 2026; the
  boards' "Last updated:" would change what the date means legally), and the
  boards' tint "Sample text — replace before launch" notice is not rendered:
  the copy is the real policy text, not sample text (its Contact clause still
  carries its own pre-launch placeholder).
- **App-shell Back link (2026-11-01, owner decision).** The crumb bar stays
  gone in the web shell. In the installed app (`html[data-shell="app"]`)
  `LegalShell` renders `<AppBackLink />` above the `<article>`: a quiet
  `‹ Back` (Hanken 15px, muted, 44px target, green focus ring) that goes
  `history.back()` when the previous entry is in-app (e.g. the History tab the
  More sheet was opened from) and to `/` otherwise (cold open). Hidden with
  `display:none` in the web shell. **[Refinement 10, owner: "it should be
  visible on every other, not only app": Privacy and Terms now render
  `<AppBackLink everywhere />` (`.app-back--everywhere`), so it shows in the
  web shell too, at every width. Web target `/app`; in the installed app a
  cold-open Back still lands on `/app.html` (R9 `canonicalizeAppPath`).
  API key and Releases are unchanged (app shell only: on the web they are nav
  tabs). Measured on the web at 390x844 and 1280x800, light and dark: link
  69x44 directly above the title, no horizontal scroll; cold Back → `/app`;
  from `/app?view=history` → back to History.]** `/offline` does **not** get it (still true after refinement 10; its links stay plain `<a>`) — it is not
  opened from the More sheet, and its Try again already goes home. Full
  behaviour and measurements: `app-shell-layout.md` § "App-shell Back link".
- **Offline**: `.offline` (28rem), centred in the band at every width — the
  offline section is a flex column filling the band, so the block centres on
  phones too. A 76px round tint disc with lucide `WifiOff` (ink, never red),
  serif `h1` "You're offline" at the shared title size, the lede "VideoLens
  needs a connection to analyze new videos. A run you already started keeps
  going on the server.", and **`<a href="/">` Try again** (`.btn-ink`) —
  still a plain anchor (the eslint override for `app/offline/**` stays),
  because an RSC navigation cannot resolve with the network down.
  **Phase 5a (supersedes the Phase 4 deviation):** the lede is now the board's
  "VideoLens needs a connection to analyze new videos. Your History is still
  here." and `.offline-actions` holds Try again (`.btn-ink`) + **Open History**
  (`<a href="/?view=history">`, `.btn-secondary .btn-pill`), side by side,
  **[Phase 5c: Try again is now `href="/app"` and Open History
  `href="/app?view=history"`; the tool moved to `/app`.]**
  wrapping on the narrowest phones. Both are true now: History is in IndexedDB
  and the worker serves its address offline (below). The old "A run you
  already started keeps going on the server." sentence was dropped to match
  the board.

## The measure

`.legal-body` caps the document column at `var(--measure)` (40rem), and inside
it `.prose` drops its own cap so paragraphs fill to that edge. Heading, effective
date, every `.col-label` hairline and every paragraph therefore terminate at the
same x — verified at 832px on a 1440px viewport.

This is load-bearing. `.col-label` rules the full width of its container; in the
results pane that container is a narrow column, so the rule tracks its text.
Dropped into the 68rem shell with only the paragraphs capped, each section rule
overshot the last character beneath it by ~450px and the page read as half-
rendered. In a theme with no boxes, the shared right edge *is* the structure.

Two rule widths exist and they mean two different things: **chrome rules** (the
footer's) span the shell; **document rules** span the measure. Above the footer
a legal route now draws only document rules — the `.col-label` hairlines under
each section head. The crumb bar has none; see "There is no hairline here".

## Fixed frame, conditional scroll

`data-frame="fixed"` puts these routes on the same one-viewport model as the
app: the nav band and footer stay fixed, and only `.legal-doc` between them
scrolls. It uses `overflow-y: auto`, never `scroll`, so a short document shows
no scrollbar at all. Verified by measurement — at 900px tall the document does
not scroll; at 560px it does; in **both** cases the page itself does not scroll
and the footer sits flush to the bottom edge.

`/offline` is on the same `data-frame="fixed"` shell but has **no** scrolling
region at all — a blocking state should fit. Measured at 1440×900 and 390×844:
`viewport.scrollHeight === viewport.clientHeight`, so nothing scrolls anywhere
on the page.

### The footer's 16px offset between `flow` and `fixed` — fixed

At 390px the footer used to sit at y=784.1 on `/` and y=800.1 on `/privacy`.
Cause: the bottom safe gutter was applied **twice** on a `flow` route — once by
`.shell`'s `padding-bottom` and again by `.page-end`'s. On a `fixed` route
`.page-end` zeroes its own, so it was applied once.

Fix, in the mobile-first block of `globals.css`: `.page-end` keeps its
`padding-bottom` and gains a matching **negative** `margin-bottom`, reaching
back into the gutter `.shell` already reserves instead of adding a second one.
The padding has to stay — it is what carries the band's `--color-paper`
background to the bottom edge while the footer is stuck mid-scroll, and dropping
it would let content show through underneath. `.shell[data-frame="fixed"]
.page-end` and the desktop block both set `margin-bottom: 0` alongside the
`padding-bottom: 0` they already had.

**The one-viewport scroll model is untouched** — this changes where the footer
rests, not what scrolls. Measured at 390×400 (small enough that the `flow` frame
genuinely scrolls, 188px of overflow): `.foot` bottom is 384 and `.page-end`
bottom is 400 at the top of the scroll, midway through it, and at the end —
i.e. the footer holds one gutter above the viewport edge throughout and its
background still reaches that edge. At 390×844 the footer is now y=800.1 on all
four routes; desktop was already identical at y=856.1 and is unchanged.

`app-shell-layout.md` records this as unfixable without changing the mobile
scroll model. That turned out not to hold — its owner should update that entry.

## Layout

Legal: `AppNav` → crumb bar → `h1` → effective date as a `.card-label` →
`.col-label` sections → footer. The page files hold nothing but copy. **No rule
between the nav and the heading** — see "There is no hairline here".

Offline: `AppNav` → centred `.home-center > .run-state` holding `h1` +
`.prose` + a `Try again` `.btn-primary` → footer. No crumb bar — a breadcrumb
implies a hierarchy to climb, and `/offline` is not a place in one; the primary
action already points home.

**Type is retuned for mono**, not inherited from the old Inter scale: `.page-title`
is `1.5rem`, stepping to `1.75rem` at 32rem, weight 500 to match
`.wordmark`/`.btn`, and the negative letter-spacing is removed — it fights a
fixed advance width. It lives in `globals.css` rather than as Tailwind arbitrary
values on the element, so its breakpoint is the app's 32rem and not Tailwind's
`sm`. It was `.legal-title` while the two legal pages were its only callers;
`/offline`'s `h1` is the same object in the same position, so it is now named
for the position rather than the route — measured at 28px/500 on both routes at
1440 and 24px/500 on both at 390, i.e. `/offline` picked up the 32rem step it
never had while it carried inline Tailwind sizes. Section heads use
`.col-label` + a hairline rather than a size jump: in a
single-face system a larger `h2` just reads as more mono, so the label and rule
carry the hierarchy instead.

## Crumb bar

```
[ ‹ ]   ⌂ / PRIVACY
Privacy Policy
EFFECTIVE AUGUST 1, 2026
```

No rule anywhere in that chain — see "There is no hairline here" below.

Sits **under** the nav, not inside it. The nav carries the brand; the crumb bar
carries the way back and names the current page only. It does not repeat the
brand, which is already directly above it.

**A control, then a location — two elements, not one row of four glyphs.**
`.crumb-back` is a bordered **rounded-square** button holding a single chevron,
and it sits **outside** the `<ol>`. The trail after it is a real
`<nav aria-label="Breadcrumb"><ol>`: home link, `/`, current page. Both halves
link to `/`.

Classes: `.crumb-bar` (the row, **and the one type spec the whole row
inherits**), `.crumb-back` (the button), `.crumb-home` (the trail's home link —
bare house glyph), `.crumb-sep` (the `/`), `.crumb-current` (the page name; sets
`color` and nothing else).

### This shape is the user's explicit call — do not "fix" it back

An earlier pass shipped `← BACK / PRIVACY` and argued for it in this section on
two grounds, **both of which the user has now overruled twice**. The old
arguments are recorded here so nobody re-derives them and silently reverts:

- ~~"One icon, not two — two glyphs pointing at the same single destination."~~
  The user asked for **arrow plus home**, twice. It is built that way. The
  chevron is a control and the house is a location; that they share a `href` is
  not duplication the user cares about, and it is not this agent's call.
- ~~"The link has a word, and the word is what carries the touch target."~~
  `BACK` is gone — the arrow already says back. The target is now carried by
  explicit box sizing (below), not by an English word's width.

What survives from that pass, unchanged and still deliberate:

- **The `/` separator.** Without it this was loose labels with none of a
  breadcrumb's grammar, and a slash is the one punctuation mark a monospace
  system has an unambiguous claim to. `aria-hidden` — visible grammar, audible
  noise.
- **The `<nav>` + `<ol>`**, not a row that merely looks like one. That is what
  lets assistive tech announce and skip it.

### Why the back button is outside the `<ol>`

It is an action, not an ancestor. Listed as a breadcrumb item it would tell a
screen reader this document sits two levels deep when it sits one. Measured:
the ARIA snapshot of `/terms` is `navigation "Breadcrumb" → list → 2 listitems`
(`link "VideoLens AI home"`, then `terms`) with the button nowhere in it.

It is a `<Link href="/">`, not a `history.back()` button. Browser-back from a
deep link — store listing, terms checkbox, an emailed URL — leaves the app
entirely; a real destination is honest about where it goes.

### Size and shape — deliberately NOT the nav icon-button family

`.theme-toggle`, `.menu-toggle` and `.menu-close` share a `2.75rem` mobile-first
/ `2rem` desktop box and `--radius-pill`. `.crumb-back` matches none of that,
**on purpose, at the user's direction**:

| | those three | `.crumb-back` |
| --- | --- | --- |
| painted box | 2.75rem → 2rem | **1.75rem, flat at every width** |
| radius | `--radius-pill` (999px) | **`--radius-control` (8px)** |

Two reasons it holds up rather than reading as drift. Those three are nav chrome
living inside a 52–62px band, so a 32–44px round control is in scale there; this
sits in a 0.68rem micro-label row, where matching them made it the loudest thing
on the page. And `--radius-pill` on a *square* box is a circle — this is a
button, not one of the nav's round glyph controls. Do not "restore consistency"
by folding it back into that group.

`--radius-control` is a third radius token, added for this (`tokens.css`, next
to `--radius-card: 0` and `--radius-pill: 999px`). 8px against a 28px box is 57%
of the way to a circle; measured against the reference, 4–6px reads as an
anti-aliasing artifact at this size and 12px is already a squircle. If the box
size ever changes, re-derive the radius against the new box rather than keeping
8px.

### Touch targets — measured, both of them

This is the constraint that killed the first icon-only attempt (it shipped at
35x44, half a WCAG 2.5.5 target), so both controls are measured, not assumed:

| | fine pointer | `pointer: coarse` |
| --- | --- | --- |
| `.crumb-back` | 28x28 painted **and** hit | 28x28 painted / **44x44 hit** |
| `.crumb-home` | 13.6x13.6 | **44x44** |

`.crumb-back` shrank to 28px on the user's ask, so on touch it grows **only its
hit area**, via an invisible `::before`. Two facts about that overlay are
measured, not arithmetic:

- **Every offset adds `var(--rule-w)` back.** An absolutely-positioned child's
  containing block is the *padding* box, and with `box-sizing: border-box` a
  1.75rem button with a 1px border has a 26px padding box — so a flat
  `inset: -0.5rem` produces a **42x42** target, not 44x44. It measured 42 before
  the correction. Verified after: `44.0 x 44.0`, with all four corners and all
  four edge midpoints resolving to the link via `elementFromPoint`.
- **The 18px of growth is split 14 left / 2 right, not 9/9.** Left of the button
  is the shell's empty gutter; right of it is `.crumb-home`'s own 44px target.
  Centred, the two hit areas end up 7px apart, under the 8px adjacent-target
  minimum. Biased, they measure **14px** apart and the extra target lands on
  dead gutter. A target does not have to be concentric with its paint.

`.crumb-home` gets `min-width` **and** `min-height: 2.75rem` in the coarse block;
a bare 13.6px house is otherwise the entire target. Both controls carry
`justify-content: center`. The row's `gap` opens from `--space-xs` to
`--space-sm` under `pointer: coarse`, since both controls are 44 wide there.

At a fine pointer `.crumb-back` is 28x28 — above WCAG 2.5.8's 24x24 AA minimum,
below 2.5.5's 44x44 AAA, which is the same standing every other desktop icon
button in the app has at 2rem.

Neither has visible text, so each carries a visually-hidden `sr-only` span
(`Back to VideoLens AI`, `VideoLens AI home`) rather than an `aria-label` —
real text is translatable and survives a text-only rendering.

### There is no hairline here

**User's call: "remove that hairline. I don't see any use for that."** It is
deleted, not moved or zeroed.

Two earlier positions are both dead, recorded so neither gets reinstated:

- ~~`.crumb-bar { border-bottom }`~~ with `.legal-doc` opening a `--space-lg`
  (32px) gap before the `h1`. That read as a divider *closing* the crumb off,
  with the heading stranded below a line belonging to neither.
- ~~`.legal-body { border-top }`~~ directly above the heading. Better, but it
  still cost more vertical space (leading above and below) than it bought.

`.page-title` is 28px of mono against a 0.68rem tracked-out crumb row; that
contrast is already all the separation the two need. The `.col-label` rules
under each section head still carry the document's internal rhythm, so the page
has not lost its ruled structure — it lost one rule that was doing nothing.

Swept rather than zeroed: `.crumb-bar` has no `border-bottom`, `.legal-body` is
`max-width` and nothing else, and `.legal-doc`'s `padding-top` is gone with it.
Verified by walking every element in the nav → heading chain and reporting any
non-zero border, outline, or rule-drawing `::before`/`::after` — **zero stray
rules** in all 8 route × width × theme combinations.

The crumb bar keeps `margin-top: --space-md` (the app's standard first-content
gap, unchanged from every other route); `padding-bottom: --space-2xs` is now the
whole gap between the crumb row and the heading.

### Measured chain, nav bottom → `h1` top

| | before this revision | after |
| --- | --- | --- |
| 1440x900 | 77.0px | **60.0px** |
| 390x844 | 89px | **76.0px** |

For reference, the original `← BACK` + hairline + 32px void layout was 78.6px on
desktop. The desktop saving comes from two places roughly equally: deleting the
rule and its leading, and dropping the button from 32px to 28px.

**Why it survives now that the nav has four real links out.** Its original
justification — "these routes sit outside the shell's tab nav, so without the
back link the only way out is the browser's back button" — is **void**. The nav
carries Analyze, History, API key and Releases on `/privacy` like everywhere
else, so nobody is stranded.

Kept anyway, on two narrower merits:

- **It names where you are.** `AppNav` deliberately passes `activeTab={null}`,
  so nothing in the nav is `aria-current` on a legal route. Without the crumb
  the chrome would say nothing at all about which of two near-identical
  documents you are reading. The `<h1>` says it too, but the `<h1>` scrolls
  away with `.legal-doc` and the crumb does not.
- **`back` is not the same destination as `analyze`.** The crumb link is
  `/` — the app as it was, with no `?view=`. A nav tab is a lateral move to a
  named destination. "Leave this document" and "go to the Analyze tab" read the
  same only because Analyze happens to be the default view.

Neither is a strong claim, and removing the bar would not break anything. It
stays because it costs one hairline row and answers "which document is this"
without a size jump, which in a single-face type system is otherwise expensive.

## Things that are deliberate

- **`select-text` on the legal `<main>`.** `layout.tsx` sets `select-none` on
  `<body>` (it's a PWA), but unselectable policy text is a real problem. These
  routes opt back in. `/offline` has no policy text and does not.
- **No `shrink-0` on the route roots any more, and none is needed.** `.viewport`
  is a column flex container with `overflow-y: auto`, so a direct child that can
  shrink compresses instead of scrolling — but the child here is `.shell`, which
  already declares `flex: 0 0 auto`. `/offline` needed the utility only while
  its root was a bare `<div>`. If a route ever roots on something other than
  `.shell`, it needs it back.
- **Heights are measured, not computed** — now by inheriting the shell rather
  than by re-deriving. `/offline` previously ran `min-h-full` plus four
  `max(space, --safe-*)` paddings of its own; all of that is `.shell`'s job and
  `.shell` does it. One consequence, recorded honestly: the app applies
  `--safe-left/right/bottom` but **not** `--safe-top` (the nav band's own
  `padding-top` stands in), so `/offline` no longer applies safe-top either. It
  now matches every other route, which is the point, but `--safe-top` is
  currently a token with no callers app-wide.
- **Exactly one wordmark per page.** The nav carries the brand, so nothing below
  it repeats one: the legal footer drops it, and `/offline`'s body `<span
  className="wordmark">VideoLens AI</span>` was removed when the nav gained a
  real one — two stacked wordmarks read as a broken header. Verified: one
  `.wordmark` node per route.
- **`text-wrap: balance` on the offline paragraph.** `.prose` caps at
  `--measure`, a reading width tuned for left-aligned columns; centred, the
  sentence spilled one word onto a second line. `balance` splits it evenly and
  degrades to the normal wrap where unsupported — cheaper and more honest than
  inventing a second, narrower measure for one paragraph.
- **`.run-state` is used bare.** `/offline` used to override it to `32rem`,
  re-deriving a width the shell already owns. It now takes the app's own
  centred-state width (44rem), with `.prose` capping itself at `--measure`
  inside it.
- **Plain `<a>` in the offline footer, not `next/link`.** This page is served
  from cache with the network down, where a client-side RSC navigation cannot
  resolve. `HomeScreen`'s footer uses plain anchors too; `LegalShell` uses
  `Link`, which is correct for pages that are only reached online.
- **Legal copy and effective dates are byte-identical** to the pre-redesign
  versions. These are policy documents; the Terminal port restyled them only.

`.legal-copy` and the document vocabulary (`.crumb-*`, `.legal-doc`,
`.legal-body`) are page-scoped survivors of the Midnight Glass deletion.
`.page-shell` was the last of that set and went with `/offline`'s old layout;
`--content-width`, its only remaining consumer gone, went with it.

## What the service worker serves offline

**Phase 5c update (2026-11-01), supersedes the route lists below.** The tool
moved to `/app` and `/` became the landing page (`landing-page.md`).

```js
const SHELL_DOCUMENTS = ["/", "/app", "/offline", "/privacy", "/terms"];   // precached
const OFFLINE_CAPABLE_DOCUMENTS = ["/", "/privacy", "/terms"];             // served from cache offline
const OFFLINE_CAPABLE_VIEWS = ["history"];                                 // of APP_DOCUMENT = "/app"
```

- **`/` is now offline-capable.** It used to be off the list because it was
  the tool, which needs the API. It is now the landing: static text, a sample
  card, no API calls. Complete with no network, so it earns its place.
- **`/app?view=history`** is served from the cached `/app` (Phase 5a's rule,
  moved to the new path). Every other `/app` address gets `/offline`.
- **Legacy `/?view=history`** is not mapped in the worker. It is served the
  cached landing, whose pre-paint script replaces the URL with
  `/app?view=history`, which the worker then serves from cache. One extra
  cached hop, no network, and the address bar ends on the canonical URL. That
  is simpler than teaching the worker the old address too, and it stays
  correct if the redirect table changes.
- `build-sw.mjs` maps `/app` to `app.html` for the precache digest.
- The offline page's buttons point at `/app` and `/app?view=history`.

**Measured (2026-11-01)** on `next build` + `next start -p 3016`. The worker
was active and controlling, then the **server process was killed** (not
`setOffline`, which this doc already records as insufficient):

| requested | renders |
| --- | --- |
| `/app?view=history` | History (hydrated) |
| `/?view=history` | ends on `/app?view=history`, History |
| `/` | the landing |
| `/app` | You're offline |
| `/app?view=api-key` | You're offline |
| `/privacy` | Privacy |
| `/nope` | You're offline |
| `/offline` → Open History | `/app?view=history`, History |


**Phase 5a update (2026-11-01).** `/?view=history` is now served from the
cached `/` shell offline (`OFFLINE_CAPABLE_VIEWS = ["history"]` +
`cachedAppView()` in `sw.template.js`): History reads IndexedDB, so it is
complete with no network. Every other view of `/` (bare `/`, `?view=api-key`,
`?view=releases`) and unknown paths still get `/offline` — it is still an
allowlist. Inside that shell, opening a stored run switches to Analyze by
`pushState` (no request) and renders from IndexedDB. Pressing Analyze there
gives an intake whose submit fails with the honest "Can't reach the server"
sentence — acceptable, since the user chose to go there.
`build-sw.mjs` now also digests the template's own bytes, so a policy-only
change renames the cache and sweeps the old one (it changes every build
anyway). **Measured** on `next build` + `next start -p 3007` with the real
worker controlling, History seeded, then the **server process stopped**
(Playwright's `setOffline` alone did not stop the worker's own `fetch` from
reaching the live server in this setup, so it is not a sufficient offline test
here): `/?view=history` → History with 6 posters; `/offline` → Open History →
History; reopening a run → its result; `/`, `/?view=api-key`,
`/?view=releases`, `/nope` → offline page; `/privacy` → Privacy; React
hydrated. The table below is the pre-5a measurement.

The navigate branch used to be `fetch(req).catch(() => caches.match("/offline"))`
— it never consulted the cache for the **requested** URL, so `/privacy` and
`/terms` rendered the offline page even though both documents were sitting in
that same cache. Re-confirmed by running it before changing it, then replaced
with an explicit route classification:

```js
const OFFLINE_CAPABLE_DOCUMENTS = ["/privacy", "/terms"];
```

Try network → on failure, if the requested route is on that list serve it from
cache → otherwise serve `/offline`.

**It is an allowlist, and that is the point.** A route added later falls into
the `/offline` bucket by default rather than silently into the wrong one. A
route earns a place on the list only if it is genuinely complete with no
network: all of its content is in the cached HTML and it calls no API.

- **`/privacy` and `/terms` are on it.** Static documents, already precached,
  work perfectly with no network. Hiding them behind an offline screen was a
  pure loss.
- **`/` is deliberately not**, and this is the product call. The app is useless
  without the API: the cached shell would give an upload form that cannot upload
  and a history panel that errors. That is a worse lie than "you are offline",
  and it would make `Try again` load a half-working app instead of staying put.
- Anything else (`/?view=history`, an unknown path) → `/offline`.

One route can arrive as `/privacy`, `/privacy/` or `/privacy.html` depending on
whether the caller is `next start`, the static export or a deep link, so
`documentRoute()` normalises all three before classifying.

Two smaller changes in the same handler: cross-origin navigations are now left
alone entirely (the old handler would have answered a link to another site with
our offline page), and the same-origin asset branch is unchanged.

**Measured offline** on a production standalone build with the real worker
registered and `setOffline(true)`:

| requested | renders |
| --- | --- |
| `/privacy` | Privacy Policy, crumb bar, 4 nav tabs |
| `/terms` | Terms of Use, crumb bar, 4 nav tabs |
| `/` | You are offline |
| `/?view=history` | You are offline |
| `/offline` | You are offline |
| `/nope` | You are offline |

Also verified offline: `next/link` navigation *between* cached documents works
(footer Privacy → Terms lands on Terms of Use), and the crumb `back` link from
`/privacy` correctly reaches `/offline`.

**A cold offline start is now proven**, which the previous note recorded as
unproven because the CSS was arriving from the browser's HTTP cache rather than
the worker's. Repeated with the HTTP cache wiped first (CDP
`Network.clearBrowserCache`) and the network then cut: `/privacy` still renders
with `.nav` resolving `border-radius: 999px` and the translucent
`--color-paper-2` fill, `.menu-toggle` present (so React hydrated), and the
theme toggle flipping light → dark.

## The precache list is generated, not hand-written

**Files**: `frontend/sw/sw.template.js` (source) → `frontend/scripts/build-sw.mjs`
→ `frontend/public/sw.js` (generated, **gitignored**) and `frontend/out/sw.js`
for the Capacitor export. `npm run build` and `npm run build:mobile` both run
the generator as a second step. Edit the template; never edit `public/sw.js`.

This exists because the theme toggle was inert offline. Exactly one request
failed — a `/_next/static/chunks/*.js` — so React never hydrated and every
client control (toggle, drawer, tab links) rendered and did nothing. The cause
was structural, not a missing line: Next content-hashes every chunk filename, so
a hand-maintained `sw.js` can name the HTML routes but never their JS. Hardcoding
a hash is correct for one build and silently rots on the next.

The generator walks the build's own `static` directory (`out/_next/static` for
the export, `.next/static` otherwise), collects every `.js`/`.css` file, and
substitutes the list into the template. It exits non-zero if the build directory
is missing, if it finds zero assets, or if a precached route has no prerendered
HTML — a partial precache that appears to work is worse than none. `install`
uses `cache.addAll`, which is atomic, for the same reason: a failed entry fails
the whole install loudly instead of leaving a cache that breaks on the one
missing chunk.

**Not Workbox, deliberately.** `injectManifest` would do the manifest half, but
its real value is a runtime routing DSL this worker does not want — the whole
policy above is 20 lines and is the thing that needed to be explicit and
readable. Adding `workbox-build` would have meant a dependency tree and a
rewrite of the part that was worth writing by hand. The generator is
dependency-free Node.

### Cache versioning — yes, it was needed

`videolens-shell-v1` was a fixed name, and the file's bytes never changed
between builds, so **the browser had no reason to re-install the worker at all**
— which is the failure mode worth naming: a stale cache pairing old HTML with
chunk filenames that no longer exist on the server.

The cache is now `videolens-shell-<12 hex>`, a SHA-256 over the sorted asset URL
list plus the bytes of all four precached HTML documents. Any change to either
changes the name, changes the worker's bytes, and therefore triggers a
re-install whose `activate` sweeps every other cache.

Measured end-to-end against the static export served from disk, rebuilt in place
mid-session so a rebuild *was* a deploy: build 1 left one cache
(`videolens-shell-dd721246a907`, 22 entries); a fake stale `videolens-shell-v1`
was seeded by hand; after the rebuild the only cache present was
`videolens-shell-820d0c076b6d` — both the previous cache and the seeded v1 were
gone — and all four routes still rendered correctly offline with a working
toggle.

Two honest costs:

- **Every build gets a new cache name, even a no-op rebuild.** Next's buildId is
  random by default and is a path segment in three precached assets. So a deploy
  costs a full ~1 MB re-precache regardless. That over-invalidates, never under,
  which is the safe direction; making it content-derived would mean pinning
  `generateBuildId`, which changes what the build ID means everywhere else.
- **`skipWaiting` + a swept cache is rough on an already-open tab.** A tab still
  running the old HTML asks for old chunk URLs that the new worker just deleted;
  the asset branch falls through to the network, which is fine online and
  broken offline until the tab reloads. Narrow window, not worth blocking the
  upgrade for.

## Known issues

- **The Capacitor/Android WebView is unverified.** `install` precaches the four
  routes by extensionless path (`/privacy`), which `next start` and the test
  static server both resolve. The export writes `out/privacy.html` and an
  `out/privacy/` directory containing only `.txt` payloads — no `index.html`. If
  the Android WebView's asset server does not fall back to `privacy.html`, the
  atomic `addAll` fails and **the worker never activates on Android at all**;
  if it falls back to `index.html` instead, `/privacy` would be cached holding
  the app shell. Pre-existing — the old worker precached the same four paths, so
  this is unchanged, not introduced — but it is now a bigger install to lose.
  Needs an emulator or device to settle; not run here.
- **`?_rsc=` prefetches fail offline.** `AppNav` and `LegalShell` use
  `next/link`, so Next prefetches RSC payloads; offline those requests fail and
  Next falls back to a full document navigation, which the worker answers
  correctly. Measured: every offline navigation succeeded, and the only failed
  requests in the whole offline run were `?_rsc=` ones. Cosmetic console noise,
  no user-visible effect.
- **Whichever build runs last owns `public/sw.js`.** Running `npm run build`
  then `npm run build:mobile` leaves the file describing the *export's* assets.
  Harmless in practice — the Dockerfile runs only `npm run build`, and the
  Android job ships `out/sw.js` — but do not assume `public/sw.js` matches
  `.next/` after a mixed pair of builds.
- **Not tested on a physical device.** Chromium emulation only.

### Smaller

- **`offline` no longer shows the app icon.** The rounded raster
  `<img src="/icon-192.png">` was the only non-flat, non-square object left on
  the page; it's replaced by the nav `.wordmark`, whose `::before` supplies the
  accent `▮`. Now that the nav carries a real wordmark the page reads correctly
  with no brand mark in the body at all — but the PNG is still the one element
  removed rather than restyled, so say so if you want it back.
- **No canonical class for a wordmark *link*.** `.wordmark` has no hover,
  `:focus-visible`, or `text-decoration: none` — it is only ever used on a nav
  `<span>`. Nothing currently needs the link form; if a route grows a back-link
  wordmark, an `a.wordmark` rule belongs in `globals.css`.
- **Visually verified** via Playwright (Chromium) at 1440×900 and 390×844,
  light and dark, across `/`, `/?view=history`, `/privacy` and `/offline`.
  `.shell`, `.nav`, `.foot` and `.theme-toggle` rects are identical across all
  four routes at every combination; the page itself does not scroll at either
  size (`documentElement` and `.viewport` both report no overflow), there is no
  horizontal overflow at 390px, and the toggle is 44px under touch emulation.

**Tests**: none (see `run-analysis-hook.md`); verified via `npx tsc --noEmit`,
`npm run build`, `npm run build:mobile`, plus the Playwright passes above and a
real-service-worker offline pass (production build, `setOffline(true)`,
including a cold start with the HTTP cache cleared via CDP
`Network.clearBrowserCache` so the SW cache was the only source).

## Refinement 6 (2026-11-02)

**OFF-03, a real 404.** `app/not-found.tsx` replaces Next's bare 404 with the
app's chrome: `.shell` + `AppNav activeTab={null}` + `main.view-scroll
data-view="not-found"` + `SiteFooter` + `BottomTabBar activeTab={null}`.
Content mirrors /offline (shares its CSS): a tint disc with a compass, h1
"This page doesn't exist.", one line ("The address may be mistyped, or the
page has moved."), and two links, "Open VideoLens" (/app) and "Go to the home
page" (/). Title "Page not found · VideoLens AI". The static export writes it
as `out/404.html` (head script passes `node --check`). The service worker is
unchanged and deliberately does not precache it: navigation is network-first,
so online an unknown path gets the server's 404 page; offline it gets /offline
(the SW cannot tell "no such page" from "needs the network"), which has the
same chrome. Both verified with the SW active against the export served like a
static host, in the web and installed shells.

## Refinement 8 (2026-11-02)

**NF-01, the installed app showed the landing at an unknown path.** Capacitor's
asset server is not a static host: it answers an unknown extensionless path
with `index.html`, never `404.html`. The pre-paint head script now sends such a
path to `/404.html` on the asset-server origin (details and the rule table in
`landing-page.md`, "Unknown paths in the installed app"). The 404 page's "Go to
the home page" link carries `.not-found-action--web` and is hidden under
`:root[data-shell="app"]`, so in the installed app it shows only "Open
VideoLens". Measured on an emulated asset server over `out/` with a fake
bridge, light and dark: `/nope`, `/nope/deeper`, `/app/zzz`, `/404` and
`/nope?x=1#h` all end on `/404.html` with the not-found page, dock shown, no
landing painted; `/`, `/app`, `/privacy`, `/terms`, `/offline` unchanged; "Open
VideoLens" reaches the tool. Web (static host, no bridge) still shows the 404
at the typed address with both links.

## Refinement 9 (2026-11-02) — one address for the tool in the installed app

On the Capacitor asset server (native, `localhost`, no port), a cold start, a
reload and the legal pages' Back (a history step) landed on `/app.html`. The
dock and Back's fresh-entry link are client-side navigations to `/app`, so the
same screen answered to two addresses. `canonicalizeAppPath()`
(`application/useMainTab.ts`, run once by HomeScreen on mount) rewrites `/app`
or `/app/` to `/app.html` with `history.replaceState`. It keeps the query, the
hash and the in-app entry marker, and passes a fresh state object to Next's
patched history. `/app.html` is the spelling that resolves on the asset server
without the `index.html` hop. On the web (`isCapacitorAssetServer()` false) it
does nothing, and `/app` stays `/app`.

Verified on an emulated asset server serving `out/`: start, terms Back (fresh
entry), privacy Back (after the app) and the dock from privacy all end on
`/app.html`. On `next start` the web stays on `/app`.

## Copy update (2026-11-13, owner-approved)

Both pages now read "Effective November 13, 2026". Terms: a new "Your own
Gemini key" section after "Prohibited use" (key stored only on the device,
not stored by us, user responsible for it, its charges and Google's terms),
and "Prohibited use" ends with the limit/suspend/block sentence covering
accounts and devices; the meta description names the new section. Privacy:
a new "Your own Gemini key" section after "Your History" (sent with the run
request, held in memory until the run calls Gemini, then discarded; never
written to the database or logs), and "Signing in" now says the server also
keeps a count of the free runs the account has used each month. Pages stay
static server components; no scripts added, so the CSP hashes are unchanged.

## Paid plan copy (2026-11-13, drafts for the owner's legal review)

Terms gain "Paid plan" after "Your own Gemini key" (auto-renewing monthly or
yearly until cancelled; cancel in Manage billing, access to the end of the
paid period; extra runs billed per run at the checkout price; BYOK runs do
not count; no partial-period refunds except where the law requires; price
changes announced before renewal; Stripe handles payments). Privacy gains
"Payments" before "Third-party services" (Stripe processes payments, we never
see or store the card number; we keep the Stripe customer and subscription
IDs, plan status, renewal date and a monthly run count), and "Third-party
services" names Stripe. Both meta descriptions mention the new sections. Each
section carries a JSX comment marking it a draft. Effective date unchanged
(November 13, 2026). Static, no scripts: CSP hashes unchanged. Terms key
bumped to v3 (`upload-form.md`). Detail in `billing.md`.

## Changelog

- 2026-08-15 · frontend agent · ported privacy/terms/offline off the Midnight Glass classes
- 2026-08-15 · main session · moved both legal routes onto the shared app chrome (.shell + .nav + .foot), added the crumb bar and the fixed-frame scroll model, extracted ThemeToggle. NOTE: app/offline/page.tsx still has its own centred layout and does NOT carry the shared nav/footer — open gap
- 2026-08-15 · frontend agent (pipeline review) · capped the document column at --measure so section rules and prose share one right edge; rebuilt the crumb as a real nav/ol breadcrumb (← BACK / PRIVACY, 53x44 on touch); moved the h1 into .legal-title off Tailwind arbitrary values and the orphan sm: breakpoint; recorded that the legal nav's missing tabs are a real deviation, not parity
- 2026-08-15 · frontend agent (offline chrome) · put /offline on the shared app chrome (.shell[data-frame=fixed] + .nav pill with ThemeToggle + .page-end/.foot), measured identical to /privacy at 1440x900 and 390x844 in both themes; dropped the duplicate body wordmark; renamed .legal-title → .page-title now that it serves both route types; deleted .page-shell and --content-width with their last caller; documented (by running a real SW offline) that the footer's Privacy/Terms links dead-end to /offline and that the theme toggle is inert offline
- 2026-08-15 · frontend agent (sw offline policy) · sw.js now serves /privacy and /terms from cache offline and keeps / on the offline page (explicit allowlist; / deliberately excluded); precache list generated at build time from the real build output (sw/sw.template.js + scripts/build-sw.mjs → gitignored public/sw.js), so React hydrates offline and the theme toggle works; cache name is now a content digest, verified to sweep a stale cache across a real rebuild; /offline ported to `<AppNav activeTab={null} />` so all four routes carry identical chrome; fixed the 16px footer offset between flow and fixed frames at 390px; corrected the "One honest exception", the rejected-extraction rationale and the crumb bar's justification — all three void since the tabs moved into the URL
- 2026-08-15 · frontend agent (crumb bar revision) · crumb is now a 28px bordered rounded-square back button (chevron, outside the `<ol>`, new `--radius-control: 8px` token) then the trail `⌂ / PRIVACY`; dropped the word BACK; DELETED the hairline from the nav→crumb→heading chain entirely (`.crumb-bar` border-bottom, `.legal-doc` padding-top and a short-lived `.legal-body` border-top all gone); nav→h1 77.0→60.0 desktop, 89→76.0 mobile; back button's 44x44 touch target now carried by an asymmetric `::before` (a flat `inset: -0.5rem` measured 42, not 44 — border-box). Three things here are the USER'S explicit calls and were each argued the other way by a previous pass: two glyphs not one, no `BACK` word, no hairline. Do not revert them
- 2026-11-01 · frontend agent · footers on /privacy, /terms and /offline replaced by the shared `SiteFooter` (web shell) + `BottomTabBar` (app shell, Privacy/Terms in the More sheet as plain `<a>` so they still work offline); routing contract and plain-anchor rule unchanged — see app-shell-layout.md "Two shells"
- 2026-11-01 · frontend agent (Phase 4) · editorial restyle of Privacy, Terms and Offline (no board): `.view-scroll` section replaces `data-frame="fixed"`, serif `.view-title` + `.legal-meta`, `.legal-section`/`.legal-heading`/`.legal-text` clauses at `--measure`, Offline as a dashed WifiOff tile + serif title + plain `<a>` Try again; deleted `.legal-doc`/`.legal-body`/`.page-title`/`.home-center`
- 2026-11-01 · frontend agent (Phase 4, boards) · rebuilt Privacy/Terms/Offline to design/phase4-boards: crumb bar removed (boards draw none; all .crumb-* CSS deleted), titles Privacy/Terms, meta directly under title, no section rules, tighter section rhythm; Offline as a round tint disc + "You're offline" + new lede, centred on phones; "Your History is still here"/Open History omitted (not true offline yet); "Effective" kept over "Last updated"; sample-text notice not rendered
- 2026-11-01 · frontend agent (app Back link) · `LegalShell` renders `<AppBackLink />` above the Privacy/Terms title, visible only in the app shell (`display:none` in web, so the boards' crumb-less web layout is unchanged); Back = history.back() when the previous entry is in-app, else `/`; /offline unchanged
- 2026-11-01 · frontend agent (Phase 5a) · Offline page gets the board's "Your History is still here." + Open History (`<a href="/?view=history">`); service worker serves `/?view=history` from the cached shell offline (allowlisted view); cache digest now includes the template; verified with the real worker and the server stopped
- 2026-11-01 · frontend agent (Phase 5a) · Privacy: "Information retained" now says the server keeps a run about an hour after it starts and then deletes it; new "Your History" section (IndexedDB only, never sent back, 20 most recent, cleared with site data, browser may evict e.g. Safari after 7 days unvisited). Effective date left unchanged — owner to decide
- 2026-11-01 · frontend agent (Phase 5c) · SW: precache /app, / (now the landing) offline-capable, History offline moved to /app?view=history, legacy /?view=history via the landing's redirect; offline page links → /app; measured with the server killed
- 2026-11-02 · frontend agent (refinement 6) · OFF-03 app/not-found.tsx with shared chrome (out/404.html); SW unchanged
- 2026-11-02 · frontend agent (refinement 8) · NF-01: installed app sent to `/404.html` for unknown extensionless paths; home-page link hidden in the installed shell
- 2026-11-02 · frontend agent (refinement 9) · installed app canonicalizes /app to /app.html (asset server only) so Back and the dock agree; web unchanged
- 2026-11-02 · frontend agent (refinement 10) · Privacy/Terms Back link visible on every shell (`AppBackLink everywhere`), web target /app, app cold-open still /app.html; /offline unchanged (no Back link, plain <a>)
- 2026-11-09 · frontend agent · privacy page deletion sentence corrected (backups and logs ~7 days); detail in auth-sign-in.md "Phase 3 state"
- 2026-11-12 · launch-checklist session · `/privacy` and `/terms` get per-page title, description and canonical; `/offline` is `noindex, nofollow` and excluded by robots.txt; the Privacy "Contact" placeholder is still unfilled and is flagged as a launch blocker in `seo-and-discovery.md`
- 2026-11-13 · frontend agent · `ServiceWorkerRegistration` now unregisters any leftover worker and deletes the `videolens-shell-*` caches when not in production, so `npm run dev` never runs under a stale production worker; production registration unchanged
- 2026-11-13 · frontend agent · effective date November 13, 2026 on both pages; Terms gains "Your own Gemini key" and a suspension sentence in "Prohibited use"; Privacy gains "Your own Gemini key" and the monthly free-run count under "Signing in"
- 2026-11-13 · frontend agent · Terms "Paid plan" and Privacy "Payments" sections (drafts for legal review), Stripe named under third-party services, meta descriptions updated
- 2026-11-13 · frontend agent · Terms "Paid plan": deleting your account cancels your subscription immediately; Privacy "Payments": deletion cancels first (no refund), billing rows removed, Stripe keeps its customer record for invoices and tax (drafts)
