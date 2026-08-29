# Railway environments and deploy triggers

How code reaches a running Railway service, which branch feeds which environment, and the three ways a deploy can silently not happen. Cross-cutting rather than per-feature: it spans both apps and the CI pipeline. See `container-workflows.md` for what the GitHub workflows themselves do, and `../DEPLOYMENT.md` for variables and first-time setup.

## Topology

Project `videolens` (`7ad439b2-a26e-4e54-9233-f2c54afdece5`), two environments:

| | `dev` | `production` |
|---|---|---|
| Environment id | `35fc5dbc-478a-4ebc-9ca8-ea5a75a9b267` | `e30dcf31-667e-43e1-b8c2-94882b8a9716` |
| Tracks branch | `dev` | `main` |
| Backend | `videolens-backend-dev.up.railway.app` | `videolens-backend-production.up.railway.app` |
| Frontend | `videolens-frontend-dev.up.railway.app` | `videolens-frontend-production.up.railway.app` |
| Worker | no domain (not HTTP-facing) | no domain |
| Redis | managed, private network | managed, private network |

`production` was created 2026-08-29 by forking `dev`, which copies service config and every variable without anyone reading them. Both environments run the same four services with `sleepApplication: true`.

## Railway builds from source. It does not run the GHCR images.

This is deliberate and worth stating plainly, because the repository also publishes container images and it is easy to assume those are what deploy.

- **Railway** is wired to `thisisgaganbirru/videolens` with `Builder: DOCKERFILE` and a per-service root directory (`/backend`, `/frontend`). It builds its own image on every qualifying push.
- **GHCR images** (`reusable-container-publish.yml`) are an archive: scanned, with SBOM and provenance attached, tagged `dev` / `latest` / `sha-<commit>`. Nothing deploys them.

So the security gate in `reusable-container-checks.yml` covers the *same Dockerfiles* Railway builds, but not the *artifact* Railway runs. Wait for CI is what connects the two: Railway refuses to deploy a commit whose checks did not pass, so a commit that fails the Grype gate never reaches a running service.

## Deploy triggers

Both environments have **autodeploy on** and **Wait for CI on**. Behaviour, per Railway's docs:

- A push to the tracked branch queues a deploy in `WAITING`.
- While GitHub Actions runs, it stays `WAITING`.
- **If any workflow on that commit fails, the deploy becomes `SKIPPED`.**
- When all succeed, it proceeds.

"Autodeploy off" and "Wait for CI on" are not two independent switches — Wait for CI is a modifier on autodeploy. Turning autodeploy off means nothing deploys on push at all and Wait for CI has nothing to gate; every release then needs a manual **Deploy Latest Commit** from the command palette.

### Branch mapping must be set in the dashboard

Railway scopes the source branch to an environment's *service instance*, and the dashboard edits it that way. The API and MCP path (`connect_service_source`) accepts an `environment_id` but applies the branch at **service level** — setting `production` to `main` through it also moves `dev` to `main`, and the next push deploys the wrong code to the wrong environment.

This happened on 2026-08-29: `dev` briefly ran `main`'s commit before being restored. **Change trigger branches in the Railway dashboard only**, per environment, per service.

## Three ways a deploy silently does not happen

Each of these presents as "Railway just didn't deploy", with no error anywhere obvious. All three are `SKIPPED` deployments in the service's deploy history — check there first.

**1. A failed workflow on the commit, including one you already re-ran.** A re-run does not erase the original. `workflow_dispatch` succeeding later leaves the earlier `push` run reading `failure`, and Wait for CI still sees the failure. A commit that failed CI once can never deploy; it needs a new commit.

**2. A bot-authored commit awaiting workflow approval.** The Android release job commits the release manifest back to `dev`. GitHub queues that commit's checks as `action_required` until someone approves them, and until then Wait for CI has no success to wait on, so the deploy is skipped. See `container-workflows.md` for why that commit no longer carries `[skip ci]`.

**3. An unrelated failing workflow on the same SHA.** Wait for CI reads *every* workflow on the commit, not only the pipeline. A failing Dependabot run counts. Two `docker in /.` Dependabot runs failed on `3b7dc14` and contributed to production skipping it.

## Environment variables that do not survive a fork

Forking copies variables verbatim, which is right for secrets and wrong for anything naming the environment. After creating an environment from another, these must be corrected or the new environment silently talks to the old one:

- `NEXT_PUBLIC_API_BASE_URL` on the frontend service — baked into the build (see below), so a stale value ships inside the image.
- `ALLOWED_ORIGINS` on the backend service — a stale value fails CORS preflight for the new frontend, which `fetch` cannot distinguish from an offline server, so the app just says it cannot reach the server. See `backend/cors.md`.

Both were corrected for `production` on 2026-08-29.

## The frontend image is environment-specific

`NEXT_PUBLIC_API_BASE_URL` is a build arg, inlined by Next at build time via `frontend/infrastructure/apiBase.ts`. A frontend image therefore physically contains one backend URL and cannot be promoted between environments — which is why `reusable-container-publish.yml` takes an `api_base_url` input at all, and why `development-environment.yml` hardcodes the dev URL while `production-environment.yml` reads `vars.PRODUCTION_API_BASE_URL` from the GitHub `production` environment.

Under the current model this costs nothing, because Railway builds each environment separately from source. It would matter if the GHCR images ever became the deployment artifact; making the URL runtime-resolved (fetching `/config.json` at boot) is the change that would unblock that.

## Known issues

- **Wait for CI has two standing ways to stall production**: the bot manifest commit needing approval, and any unrelated failing workflow on the SHA. Neither is a Railway fault; both are consequences of gating on "every workflow green".
- **The `docker in /.` Dependabot entry has failing runs** (`3b7dc14`). Not yet diagnosed. Because Wait for CI counts every workflow, a chronically failing scheduled job would block deploys indefinitely.
- **`connect_service_source` cannot express this topology.** Any automation of branch mapping has to go through the dashboard or Railway's own per-environment API, not that call.

## Changelog
- 2026-08-29 · main session · created; documents the new `production` environment, the source-build vs GHCR-archive split, Wait for CI semantics, the service-level branch-mapping trap, and the three silent-skip modes
