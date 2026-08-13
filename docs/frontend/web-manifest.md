# Web app manifest

`frontend/app/manifest.ts` generates `/manifest.webmanifest` for PWA install
metadata and Web Share Target support. The share target uses a GET action and
explicitly declares `application/x-www-form-urlencoded`, the valid encoding
for GET share targets. This avoids browser manifest validation warnings.
