# VideoLens AI Publishing Plan

Last updated: August 1, 2026

## Decision

Release VideoLens AI in two stages:

1. Deploy and validate the production web application.
2. Package the proven web frontend as an Android application with Capacitor.

The Android application will remain a client of the hosted backend. Media downloads,
FFmpeg processing, Gemini requests, API keys, quotas, and temporary files must not be
moved into the mobile application.

## Target Architecture

```text
Web browser / Android app
           |
           | HTTPS
           v
Next.js frontend
           |
           | POST /api/runs
           | GET  /api/runs/{run_id}
           v
FastAPI backend
  |-- media download with yt-dlp
  |-- validation and FFmpeg normalization
  |-- Gemini upload and analysis
  |-- timestamped result generation
  `-- temporary-file cleanup
```

Production separates API handling from background processing:

```text
FastAPI API -> Redis queue -> analysis worker -> Redis run state
```

## Phase 1: Production Readiness

Complete these items before making the application publicly available.

### Required

- [x] Store production run state in Redis instead of process memory.
- [x] Execute downloads and analysis through a background worker queue.
- [ ] Choose an OIDC provider and enable authenticated accounts in production.
- [x] Bind anonymous quotas to a stable client ID and authenticated quotas to tokens.
- [x] Limit concurrent FFmpeg and Gemini operations in the worker.
- [x] Make CORS origins explicit and configurable for production.
- [x] Add structured JSON logging; connect an external error monitor during deployment.
- [x] Remove temporary local and object-storage media after success or failure.
- [x] Add privacy and terms pages; replace placeholder operator contact before release.
- [x] Require a media permission and copyright acknowledgement before submission.

### Operational Constraints

- Do not advertise support for every social-media URL. Platform authentication and
  downloader behavior change frequently.
- Never commit Gemini credentials, browser cookies, or a `cookies.txt` file.
- Production cookies, if legally and operationally required, must be mounted as a
  secret and periodically rotated.
- Local mode uses in-memory runs. Production must configure Redis, object storage,
  and the worker before scaling to multiple backend replicas.

## Phase 2: Deploy the Web Application

### Recommended Hosting

Use one Railway project with two isolated services from this repository:

| Service | Root directory | Purpose |
| --- | --- | --- |
| `videolens-backend` | `/backend` | FastAPI, yt-dlp, FFmpeg, Gemini |
| `videolens-frontend` | `/frontend` | Next.js user interface |

Railway supports separate root directories for isolated monorepo services and uses a
service Dockerfile when present:

- [Railway monorepo deployment](https://docs.railway.com/deployments/monorepo)
- [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles)

### Backend Variables

Configure these as Railway service variables:

```env
GEMINI_API_KEY=<secret>
GEMINI_MODEL=gemini-3.6-flash
RATE_LIMIT_PER_HOUR=20
MAX_FILE_SIZE_MB=200
MAX_DURATION_SECONDS=180
RUN_TTL_SECONDS=3600
TEMP_DIR=/tmp/videolens
ALLOWED_ORIGINS=https://app.example.com
REDIS_URL=<Railway Redis URL>
S3_ENDPOINT_URL=<S3-compatible endpoint>
S3_BUCKET=videolens-media
S3_ACCESS_KEY_ID=<secret>
S3_SECRET_ACCESS_KEY=<secret>
AUTH_JWKS_URL=<OIDC JWKS URL>
AUTH_ISSUER=<OIDC issuer>
AUTH_AUDIENCE=<OIDC audience>
```

Do not set the local Windows `FFMPEG_LOCATION` value in production. The backend
Dockerfile installs FFmpeg into the container's executable path.

If login-gated media is intentionally supported, configure only one cookie method:

```env
YTDLP_COOKIES_FILE=/run/secrets/cookies.txt
```

Do not configure `YTDLP_COOKIES_FROM_BROWSER` on a hosted server.

### Frontend Variables

```env
NEXT_PUBLIC_API_BASE_URL=https://api.example.com
```

Because this value is used by the browser bundle, configure it before building the
frontend image.

### Domains

Recommended production domains:

```text
app.example.com -> frontend service
api.example.com -> backend service
```

Both must use HTTPS. Set `ALLOWED_ORIGINS` to the exact frontend origin.

### Capacity

FFmpeg may temporarily hold an original download, separate video and audio streams,
a merged file, and a normalized file. A 200 MB input can therefore require much more
than 200 MB of temporary storage. Railway's Free plan currently provides 0.5 GB RAM
and 1 GB ephemeral storage per service, so production testing may require a paid
plan or lower file limits.

- [Railway pricing and resource limits](https://docs.railway.com/pricing/plans)
- [Railway ephemeral storage](https://docs.railway.com/services#ephemeral-storage)

### Web Release Verification

- [ ] `GET /api/health` returns `{"status":"ok"}`.
- [ ] File upload works from the production frontend.
- [ ] At least one public URL completes successfully.
- [ ] Private/login-only URLs return a concise, safe error.
- [ ] Transcript and on-screen text show timestamped timelines.
- [ ] Markdown rendering, copying, and downloading work on mobile and desktop.
- [ ] A 21st run from the same quota identity receives HTTP 429.
- [ ] Runs survive API restarts once Redis and the worker are enabled.
- [ ] No API keys, cookies, local paths, or terminal color codes appear in responses.

## Phase 3: Installable PWA

Add Progressive Web App support before producing the Android package:

- [x] Add a web app manifest with name, short name, colors, and standalone display.
- [x] Add 192x192 and 512x512 application icons.
- [x] Add an application icon suitable for a maskable launcher shape.
- [x] Cache only the application shell and static assets.
- [x] Do not cache API run responses or uploaded media.
- [x] Provide a useful offline state.
- [ ] Test installation on Android Chrome and desktop Chrome/Edge.

An installable PWA appears in launchers and can run in its own application window
without requiring a Play Store package:

- [PWA installation guidance](https://web.dev/learn/pwa/installation)
- [PWA installability criteria](https://web.dev/articles/install-criteria)

## Phase 4: Android Application

Use Capacitor to package the existing frontend. Capacitor is designed to add a native
Android container and native APIs to an existing web application:

- [Capacitor documentation](https://capacitorjs.com/docs)

### Android Scope

- [x] Add Capacitor and create the Android project.
- [x] Use the stable package ID `ai.videolens.app`.
- [ ] Configure the production API URL.
- [x] Use Android's native media picker for MP3, MP4, and MOV files.
- [x] Accept URLs shared from browsers and social applications.
- [x] Add native sharing for Markdown notes and result text.
- [x] Handle network loss and resumed run polling.
- [x] Add launcher icons, application name, and theme colors.
- [ ] Build and sign an Android App Bundle (`.aab`).
- [ ] Test on physical phones, tablets, small screens, and recent Android versions.

The app should bundle its frontend assets and call the hosted API. Gemini credentials,
cookies, FFmpeg, and yt-dlp must never be included in the Android package.

Release signing is configured through `ANDROID_KEYSTORE_PATH`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, and `ANDROID_KEY_PASSWORD`.
The keystore and values must be stored outside Git. With those values set, run:

```powershell
cd frontend
npm run android:sync
cd android
.\gradlew.bat bundleRelease
```

### Android Target

Target Android 16, API level 36. Google states that beginning August 31, 2026,
new applications and updates submitted to Google Play must target API 36 or higher:

- [Google Play target API requirements](https://developer.android.com/google/play/requirements/target-sdk)

### Play Console Requirements

- [ ] Create and verify a Personal or Organization Play Console account.
- [ ] Verify access to a physical Android device if Google requests it.
- [ ] Create the store listing, privacy policy URL, screenshots, and feature graphic.
- [ ] Complete the Data safety form accurately.
- [ ] Complete the content rating and app-access declarations.
- [ ] Upload the signed `.aab` to internal testing first.
- [ ] Complete required closed testing before requesting production access.

For new Personal accounts created after November 13, 2023, Google currently requires
at least 12 testers to remain opted into a closed test continuously for 14 days before
the developer can apply for production access:

- [Google Play testing requirements](https://support.google.com/googleplay/android-developer/answer/14151465)
- [Google Play developer verification](https://support.google.com/googleplay/android-developer/answer/10841920)

## Release Order

1. Add Redis-backed run state and a background worker.
2. Add authentication, per-user quotas, and production security controls.
3. Deploy backend and frontend services.
4. Test real production uploads and supported public URLs.
5. Add the PWA manifest, icons, and offline states.
6. Add Capacitor and Android-native file/share integrations.
7. Create a signed Android App Bundle.
8. Complete internal and closed Play Store testing.
9. Submit the Android application for production review.

## Definition of Done

The release is complete when:

- The public web application is available over HTTPS on a custom domain.
- Active runs are durable across API restarts and deployments.
- Backend concurrency and per-user quotas protect costs and capacity.
- Uploaded and downloaded media is deleted according to the published policy.
- The PWA is installable and usable across supported mobile and desktop browsers.
- The Android application passes physical-device testing and Play pre-launch reports.
- The Play Store production release is approved and points to the same stable backend.
