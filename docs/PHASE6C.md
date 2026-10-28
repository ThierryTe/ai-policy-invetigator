# Phase 6C — Minimal CI and optional manual GHCR publication

Prepared October 28, 2026. No Git command, hosted workflow run, registry publication,
SSH connection or VPS deployment was performed. Both working copies remain on develop.
Existing domain/security/provider code, Dockerfiles, production isolation overlays,
database schema and ONNX initialization/cache behavior are unchanged.

## Workflow files and installation status

| Repository | File in that repository | Status |
|---|---|---|
| Backend | `.github/workflows/verify.yml` | Updated: Backend CI |
| Backend | `.github/workflows/publish-images.yml` | Added: manual backend + model-init publication |
| Frontend | `.github/workflows/verify.yml` | Ready at backend `docs/ci/frontend/verify.yml`; installation pending |
| Frontend | `.github/workflows/publish-image.yml` | Ready at backend `docs/ci/frontend/publish-image.yml`; installation pending |

The frontend is outside this session's writable workspace, and its direct write was
rejected. It remains unchanged. The two delivered files are independently linted and
were placed in the temporary frontend verification workspace. Copy only these files
into the frontend checkout after review, or add that repository as a writable workspace:

```sh
: "${BACKEND_DIR:?Set the actual backend checkout absolute path}"
: "${FRONTEND_DIR:?Set the actual frontend checkout absolute path}"
test ! -e "$FRONTEND_DIR/.github/workflows/verify.yml" || exit 1
test ! -e "$FRONTEND_DIR/.github/workflows/publish-image.yml" || exit 1
mkdir -p "$FRONTEND_DIR/.github/workflows"
cp "$BACKEND_DIR/docs/ci/frontend/verify.yml" "$FRONTEND_DIR/.github/workflows/verify.yml"
cp "$BACKEND_DIR/docs/ci/frontend/publish-image.yml" "$FRONTEND_DIR/.github/workflows/publish-image.yml"
```

These copy commands are for the owner and were not executed against the frontend.
If files already exist, compare/reconcile them instead of overwriting them. The owner
handles all commits, PRs and merges. The delivered frontend files do not become backend
Actions workflows under `docs/`; each must live in its own repository's `.github/workflows`.

## Ordinary CI behavior

Both CI workflows trigger only on pushes to `develop` and PRs targeting `main`.
They use GitHub-hosted Ubuntu 24.04, read-only contents permission, job time limits,
and cancel superseded CI runs. There is no `pull_request_target`, production environment,
PAT, SSH key, Docker login, registry push or VPS action in ordinary CI.

Backend CI uses Temurin Java 21 and the existing Maven wrapper, which pins Maven
3.9.16. It runs `./mvnw -B -Pdatabase-tests verify`, including PostgreSQL 16/pgvector
Testcontainers tests. Docker failure fails CI rather than treating database tests as
success. Python 3.12 runs all standard-library tooling tests and the existing production
Compose verifier. It then builds the production backend Dockerfile without starting it.
Maven dependency caching uses the setup-java action's built-in support.

Ordinary Maven tests omit the neural-runtime profile and use controlled embedding/
provider fixtures. The Dockerfile adds the existing neural-runtime dependencies to the
production JAR, but never starts the application or downloads ONNX weights during build.
No real Meta request or production credential is needed. Real provider demonstrations,
model initialization and browser workflows remain explicit operator operations.

Frontend CI uses Node 22, supported by the project's Angular 21 line, and npm 11.8.0
matching `packageManager`/Dockerfile. It runs `npm ci`, the existing 29 tests, the
production build and the existing production Dockerfile. npm's download cache is reused;
node_modules is recreated from the lockfile. No backend credential/token is passed to
npm, Angular or Docker build arguments. See [Angular's compatibility table](https://angular.dev/reference/versions).

### Cross-repository Compose contract

The frontend GitHub URL returned 404 to an unauthenticated metadata request; it may be
private or unpublished. Backend CI therefore does not try to clone it or require a
cross-repository token. `.ci/frontend/compose.yaml` is a reviewed, exact snapshot of
its current small Compose configuration, with source/hash/commit context in its README.
It contains no application code or credentials and is excluded from the Docker context.

CI sets `POLICY_FRONTEND_DIRECTORY` to that fixture directory and passes it to the
existing verifier; the Python topology tests use the same selection. Local tests
continue using the actual sibling frontend checkout by default and fail if its Compose
contract drifts from the snapshot. Review/update the fixture and recorded hash when
frontend Compose changes. Independent future private-repository changes cannot be
rediscovered automatically by backend CI without access; this is an explicit MVP tradeoff.
The fixture must never be used as a frontend build/deployment checkout.

## Pinned actions and token permissions

Every `uses:` reference is pinned to a full commit SHA verified against the official
release tag and fetched action manifest. Versions and source URLs are in
[phase6c-action-pins.json](verification/phase6c-action-pins.json). These releases use the
Node 24 action runtime; that is separate from the frontend project's Node 22 toolchain.
GitHub-hosted runners supply the required current Actions runtime.

Checkout disables persisted credentials. CI grants only `contents: read`. Manual
publisher jobs grant only `contents: read` and `packages: write`; all unspecified
permissions are absent. No OIDC, attestations, deployment permission or separate PAT
is requested. See [GitHub's security guidance](https://docs.github.com/en/actions/reference/security/secure-use).

## Optional manual publication

Publication workflows have **only** `workflow_dispatch` and run only when the selected
ref is `main`. Pushes/PRs never publish. The workflow file must first reach the default
branch (`main`) before GitHub offers manual dispatch. Choose `main` in Actions → the
appropriate publisher → Run workflow. A dispatch selecting develop is deliberately
skipped. No workflow has been dispatched by this agent.

Each publisher reruns its tests before building. It builds first, then logs into GHCR
using only that job's built-in GITHUB_TOKEN via password stdin. Docker authentication
is isolated under RUNNER_TEMP and logged out in an always-cleanup step. No token is
stored in checkout configuration, image layers, frontend assets or repository files.
OCI source/revision labels link images to their own repository and source commit.

For the confirmed repository names, image patterns are:

| Produced by | Image and tag pattern |
|---|---|
| Backend publisher | `ghcr.io/thierryte/ai-policy-invetigator:sha-<full backend commit SHA>` |
| Backend publisher | `ghcr.io/thierryte/ai-policy-invetigator-model-init:sha-<same backend SHA>` |
| Frontend publisher | `ghcr.io/thierryte/ai-policy-investigator-frontend:sha-<full frontend commit SHA>` |

Workflow names derive from the actual repository, lowercased. No latest/develop tag
is published. The two repositories have independent commit SHAs. The initializer
image packages the unchanged fetcher; it contains no model weights or credentials.

A full commit SHA identifies immutable source, but registry tags can be moved or
replaced by a rerun. Record the actual `sha256:` registry digest from each push and
pin that digest for deployment. No registry digest is invented in this documentation.
These workflows publish native Linux amd64 images on Ubuntu runners; ARM remains
unverified and no multi-architecture infrastructure was added.

For first publication, ensure repository Actions policy permits these pinned official
actions and the publisher's packages permission. If a package already exists, grant
its owning repository appropriate Actions access instead of adding a broad PAT.
New GHCR packages default to private. The owner may deliberately make hackathon images
public for anonymous VPS pulls. Private VPS pulls require separate read:packages
registry authentication; GitHub documents a classic PAT for that outside-Actions use.
It is not needed in these workflows and must not be introduced as a VPS/CI SSH secret.
See [GHCR authentication and visibility](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Deploy approved image versions manually — after separate deployment approval

Use the existing Phase 6B path variables, private runtime environment and
`backend_compose` / `frontend_compose` functions from [the VPS runbook](PHASE6B.md).
Keep its project names, NPM topology, health checks and account/backup procedures.
The new image-only overlays do not replace any security/network/volume configuration:

- Backend: `deploy/backend/compose.ghcr.yaml` applied after backend production config.
- Frontend: `deploy/frontend/compose.ghcr.yaml` applied after frontend production config.

Copy the approved real pull references into exported process variables:
`BACKEND_IMAGE_REF`, `MODEL_INIT_IMAGE_REF`, `FRONTEND_IMAGE_REF`. Each must be the
appropriate `ghcr.io/...@sha256:<64 hexadecimal digest>` reference. Do not supply a
mutable tag. Backend and initializer should come from the same approved backend run.
No real registry images or digests exist from this task yet.

```sh
: "${BACKEND_IMAGE_REF:?Export the approved backend GHCR digest reference}"
: "${MODEL_INIT_IMAGE_REF:?Export the matching initializer GHCR digest reference}"
: "${FRONTEND_IMAGE_REF:?Export the approved frontend GHCR digest reference}"
export BACKEND_IMAGE_REF MODEL_INIT_IMAGE_REF FRONTEND_IMAGE_REF

backend_compose -f "$BACKEND_DIR/deploy/backend/compose.ghcr.yaml" config --quiet
frontend_compose -f "$BACKEND_DIR/deploy/frontend/compose.ghcr.yaml" config --quiet
backend_compose -f "$BACKEND_DIR/deploy/backend/compose.ghcr.yaml" config --images
frontend_compose -f "$BACKEND_DIR/deploy/frontend/compose.ghcr.yaml" config --images

backend_compose -f "$BACKEND_DIR/deploy/backend/compose.ghcr.yaml" pull backend model-init
frontend_compose -f "$BACKEND_DIR/deploy/frontend/compose.ghcr.yaml" pull frontend
backend_compose -f "$BACKEND_DIR/deploy/backend/compose.ghcr.yaml" up -d --no-build --pull never --wait --wait-timeout 300
frontend_compose -f "$BACKEND_DIR/deploy/frontend/compose.ghcr.yaml" up -d --no-build --pull never --wait --wait-timeout 120
```

Before executing, review the image list: application/initializer references must contain
`@sha256:` and the expected repository paths. The PostgreSQL image remains the Phase 6B
`pgvector/pgvector:0.8.0-pg16` base selection. On a first installation retrieve that
approved database image separately (`backend_compose pull postgres`) before using
`--pull never`; do not turn an ordinary app update into an implicit database upgrade.
Private image pulls require operator registry authentication already established outside
Actions; public images need none. The agent did not authenticate, pull GHCR images,
publish or execute these deployment commands.

`--no-build` prevents fallback to the base files' build contexts, and `--pull never`
starts only the already-pulled approved versions. All PostgreSQL/model/native volumes
are retained. No new migration or auth behavior is introduced. For updates, use the
Phase 6B maintenance/backup process. For rollback, select previously approved digests
with the same secure overlays and assess schema compatibility; do not delete volumes,
reset credentials, change NPM or use Git history operations. Runtime health/TLS/Meta
checks still require the later approved deployment.

## Verification scope and remaining work

[phase6c-results.json](verification/phase6c-results.json) records actual local commands
and counts. actionlint syntax/expression checks and official action-ref/manifest checks
cover all four workflows. Local equivalent Java/PostgreSQL/Python/Compose checks ran
in a clean temporary backend workspace without dotenv files or production credentials.
Frontend lockfile installation, tests and production build ran in the pinned Node 22
Docker build stage; its temporary test context allowed spec files only for that check.
The actual frontend production Dockerfile/context was built separately.

These are not GitHub-hosted workflow results. Registry login, token/package permissions,
publication and VPS image deployment remain unexecuted. Frontend workflow installation
is pending writable access/owner copy, and the frontend GitHub repository's availability
is unverified. The owner must commit/review both repositories, run CI, place manual
publishers on main, choose package visibility and approve image digests before deployment.
No domain/certificate or Phase 6B runtime prerequisite is implicitly approved here.
