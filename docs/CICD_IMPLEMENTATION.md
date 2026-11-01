# CI/CD implementation and local validation

Implemented locally on 2026-11-01. No Git commands, VPS connections, production deployments,
service restarts, worker activation or production database migrations were performed.
The existing successful V8 release `r041243000818-11` and recovery artifacts were not modified.

Use [Production CI/CD](PRODUCTION_PIPELINE.md) for configuration, first deployment and rollback.

## Exact source file inventory

Created:

- `.github/workflows/ci.yml`
- `.github/workflows/deploy.yml`
- `.github/legacy-workflows/README.md`
- `deploy/simple/compose.images.yaml`
- `deploy/simple/compose.frontend.yaml`
- `deploy/simple/frontend-ci.yml.example`
- `scripts/ci_images.py`
- `scripts/simple_deploy.py`
- `scripts/simple_ssh.py`
- `scripts/tests/test_simple_pipeline.py`
- `src/main/java/com/tewendelabs/investigator/config/DeploymentMigrations.java`
- `src/main/java/com/tewendelabs/investigator/config/WorkersHealthIndicator.java`
- `src/test/java/com/tewendelabs/investigator/config/DeploymentMigrationsTest.java`
- `src/test/java/com/tewendelabs/investigator/config/WorkerPollingTest.java`
- `src/test/java/com/tewendelabs/investigator/config/WorkersHealthIndicatorTest.java`
- `docs/CICD_IMPLEMENTATION.md` (this report)

Modified:

- `README.md`
- `docs/README.md`
- `docs/DEPLOYMENT.md`
- `docs/PRODUCTION_PIPELINE.md`
- `deploy/backend/Dockerfile`
- `src/main/resources/application.properties`
- `src/main/java/com/tewendelabs/investigator/ingestion/IngestionWorker.java`
- `src/main/java/com/tewendelabs/investigator/investigation/InvestigationWorker.java`
- `scripts/tests/test_activation_dispatch.py`
- `scripts/tests/test_ci_automation.py`
- `scripts/tests/test_prepare_backend_qualification.py`
- `scripts/tests/test_release_safety.py`
- `scripts/tests/test_reviewed_dispatch.py`
- `scripts/tests/test_reviewed_release.py`

Archived unchanged after replacement validation; source → destination:

| Previous workflow | Archived definition |
|---|---|
| `.github/workflows/verify.yml` | `.github/legacy-workflows/verify.yml` |
| `.github/workflows/publish-images.yml` | `.github/legacy-workflows/publish-images.yml` |
| `.github/workflows/deploy-production.yml` | `.github/legacy-workflows/deploy-production.yml` |
| `.github/workflows/prepare-backend-qualification.yml` | `.github/legacy-workflows/prepare-backend-qualification.yml` |

The six historical test files above only change where archived workflow definitions are read.
Legacy operator scripts, recovery documents, SQL migrations, release evidence, existing
Compose files, model assets, secrets and sibling frontend source/workflows were left intact.
Local Maven/Angular output and Docker image caches are generated verification artifacts.

## Verification results

| Check | Result |
|---|---|
| `SPRINGDOTENV_ENABLED=false mvn -B -o -Pneural-embeddings,database-tests verify` | PASS: 183 tests, zero failures/errors/skips, packaged JAR |
| `python3 -B -m unittest discover -s scripts/tests -v` | PASS: 359 tests, including archived recovery regression tests |
| Targeted `test_simple_*.py` deployment tests | PASS: 32 tests; rerun after final deployment-script edits |
| Frontend `npm test` in the existing sibling checkout | PASS: 62 tests across 7 files |
| Backend `docker build --platform linux/amd64 --file deploy/backend/Dockerfile ...` | PASS: `local/ai-policy-investigator:simple-ci-check` |
| Frontend `docker build --platform linux/amd64 ...` | PASS: `local/ai-policy-investigator-frontend:simple-ci-check` |
| `actionlint` 1.7.12 on both active workflows and frontend notification template | PASS |
| Actual Compose CLI resolution using synthetic credentials | PASS: persistent volumes, private networks, no host ports, workers, validation-only migrations |
| Python AST syntax check | PASS for the three new scripts and deployment tests |

New tests cover successful-CI selection, rerun/artifact provenance, digest/input validation,
SSH host-key validation, failed pulls before replacement, container/public/worker health,
topology drift, snapshot secrecy/literal environment values, concurrent operations, successful
and failed rollback, changed/unreadable schema history, and blocked manual recovery.
Java tests cover real queue-poll readiness, disabled/stale executors, local embedding failure,
missing Meta configuration and validation-only Flyway. Existing isolated PostgreSQL tests
exercise V8 and application security; no production data or real Meta inference is used.

The first sandboxed Java run could not bind local HTTP fixtures. The complete suite passed
outside the sandbox. Docker builds likewise needed Docker socket access outside the sandbox.
No images were pushed to GHCR and no application containers were launched for deployment testing.

## Remaining operator validation

- Install the frontend notification template and configure `BACKEND_CI_TOKEN` in that repo;
  otherwise frontend-only pushes cannot request coordinated publication.
- Configure backend prod SSH secrets/host-key variable and package Actions access; add
  `FRONTEND_READ_TOKEN` only if cross-repository frontend checkout needs it. Update any
  branch-protection required check from the old `verify` job to `test-and-publish`.
- Verify VPS prerequisites privately: existing service/project/network/volume names,
  populated model volumes, Compose version, disk/memory capacity, outbound GHCR access
  and private read credentials. Keep current credentials and NPM/TLS routing.
- Review/set both private worker flags to true before the first authorized deployment.
  Existing queued jobs may resume normal paid processing when workers start.
- Run hosted CI after your push, then authorize the first manual deployment yourself.
  Local tests cannot certify hosted token permissions, live topology or provider availability.
- Ordinary deployments cannot apply a future migration. Review/approve schema changes
  separately. A changed or unreadable Flyway history blocks image rollback.
- Meta credentials/quota/remote availability require an explicitly authorized application
  investigation; automated readiness deliberately makes no paid inference request.

The pipeline provides an in-place update and a previous-image rollback, with brief application
interruption possible. It does not provide zero-downtime releases or database rollback.
