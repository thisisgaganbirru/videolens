# syntax=docker/dockerfile:1
# check=error=true

# Single source of truth for the Node base image across every stage below.
# Pin the newest LTS major, never `latest`. The major must match /.nvmrc — CI
# fails the build if they drift (reusable-application-checks.yml). The digest
# has to be a literal here and cannot move into .nvmrc: it is a content hash,
# not something derivable from a version string.
ARG NODE_IMAGE=node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,id=s/c8f38ea2-9c6a-40fc-ba16-a249b3108561-/root/.npm,target=/root/.npm \
    npm ci

FROM ${NODE_IMAGE} AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM ${NODE_IMAGE} AS runner

LABEL org.opencontainers.image.title="VideoLens frontend" \
      org.opencontainers.image.description="VideoLens Next.js web application" \
      org.opencontainers.image.source="https://github.com/thisisgaganbirru/videolens" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

WORKDIR /app
ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN apk add --no-cache --upgrade 'openssl>=3.5.7-r0' \
    && rm -rf /usr/local/lib/node_modules/npm \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx

COPY --chown=node:node --from=builder /app/public ./public
COPY --chown=node:node --from=builder /app/.next/standalone ./
COPY --chown=node:node --from=builder /app/.next/static ./.next/static

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

CMD ["node", "server.js"]
