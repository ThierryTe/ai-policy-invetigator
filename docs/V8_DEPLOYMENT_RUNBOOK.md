# Reviewed V8 production delivery

**Local application qualification: GO under option A. Production: HOLD until the
external requirements below are satisfied.** This runbook describes the hardened
existing release automation. It does not record a deployment, backup or restore.

For the now-published, approved hackathon images, follow
[REVIEWED_V8_DEPLOYMENT.md](REVIEWED_V8_DEPLOYMENT.md). The existing workflow's
`prepare-reviewed` operation now automates the unchanged V7 SQL checks, snapshot
backup and isolated restore; `deploy-reviewed` repeats them under the approved
freeze before the existing migration controller runs. The manual attestation
instructions below remain the legacy `operation=deploy` path. Worker activation
still needs a separate approval. Tooling-only main changes run tests without
rebuilding or publishing application images.

## Safety boundary

`verify.yml` still runs CI and publishes images after a successful backend `main`
push. It no longer calls deployment. `deploy-production.yml` deploys only on an
explicit `workflow_dispatch` in the backend repository on `main`. Legacy reusable
callers are accepted for compatibility but cannot run the deployment job.
`AUTO_APPLY_MIGRATIONS` is no longer consulted. The CLI also rejects automatic-component
delivery and non-manual Actions events. There is no automatic retry onto a changed base.

The retained sequence is **prepare → pinned SSH transfer → versioned production
controller**. No parallel deployment system, database reset or quota initialization
is introduced. The controller still verifies archives/platforms/digests, PostgreSQL
isolation/volume identity, model initialization, container health, exact Flyway history
and HTTPS routing, and refuses incompatible application rollback.

## Prepare the published backend without deployment

Use [Prepare backend qualification only](../.github/legacy-workflows/prepare-backend-qualification.yml)
to prepare a single backend image before seeking production approval. After this workflow
has been reviewed and is present on the default branch, an authorized repository writer
chooses **Actions → Prepare backend qualification only → Run workflow → main**.
The only trigger is `workflow_dispatch`; pushes do not run this preparation workflow.
GitHub requires repository write access for a [manual dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

| Input | Exact approved V8 value |
| --- | --- |
| `backend_sha` | `48669d57b32cd1acb83acc57bd9da50b02ee3cd0` |
| `approved_backend_digest` | `sha256:dca3389c5555b09c13e4f643074a6c7684d9ba7d3d73f931b34d53fcb9276eea` |
| `approved_config_digest` | `sha256:baf9cf5911c21e0129afa1700a91abec14f88bd4c4ff9d74b8943efd45baf76d` |
| `evidence_ref` | Actual non-secret approved change-record ID, 3–80 uppercase letters/digits/dot/dash/underscore characters |
| `confirm_authorized` | `true` only when preparation and downloadable artifact storage are authorized; defaults to `false` |

The three image inputs default to these approved values and can be reused for a later
reviewed V8-compatible image. The fixed backend repository cannot be overridden. The
confirmation records the dispatcher's authorization; it does not verify the change record
or assert production readiness. False confirmation fails before checkout or authentication.
The job and command both reject non-manual Actions execution, other repositories and
non-`main` refs.

No `prod` environment approval or production secrets are required. The job has only
`contents: read` and `packages: read`, using the automatically supplied `GITHUB_TOKEN`
for GHCR. The package must grant this backend repository Actions read access. Production
SSH secrets remain confined to the existing production workflow. There is no image build,
push, SSH, VPS access, database connection, migration execution, container start or worker
execution in this preparation path.

The new [backend preparation command](../scripts/prepare_backend_qualification.py) reuses
`ghcr_manifest`, `normalized_archive`, `archive_image` and `qualified_migrations` from the
existing release scripts. It verifies the registry manifest hash, rejects an index digest,
requires the approved config digest, and pulls only `repository@digest` for `linux/amd64`.
It inspects the runner platform, assigns the existing digest-based local alias, saves and
normalizes exactly one image, then verifies config bytes, platform, revision/source labels
and every layer's uncompressed DiffID. It reads the JAR inside the verified layers and
requires exact versions, filenames, Flyway checksums and SHA-256 values for V1–V8 against
the historical inventory whose SHA-256 is pinned in `release_safety.py`. Docker image IDs
are not treated as registry digests or portable content proofs.

Only a successful verification uploads the artifact
`backend-qualification-<run_id>-<run_attempt>`, containing exactly:

- `BACKEND_IMAGE_REF.tar`: normalized Docker-save backend archive.
- `evidence.json`: image identity, migration inventory, layer DiffIDs, historical evidence
  hash, archive SHA-256, change-record reference and Actions run/tooling revision.
- `SHA256SUMS`: SHA-256 checksums of the archive and evidence report.

Download from the successful run's **Artifacts** section and run `sha256sum -c SHA256SUMS`
from the extracted artifact directory before use. Access follows the repository's Actions
artifact policy; authorize storage according to that visibility. Retention is seven days,
subject to repository policy; retain the approved evidence privately if it is needed longer.
The upload service's outer artifact digest is separate from the individual file checksums.
Checksums detect changes; retain the trusted run provenance with them. Authentication
files, raw saves and resolved Docker environments are excluded from the upload allowlist.
A failed run uploads no qualification artifact; discard any partial local output and use
a fresh output directory for a retry.

A PASS establishes **published image integrity and migration equivalence**. The report
explicitly records `binaryIdentityVerified=false` and
`productionBuildProfileQualified=false`. It neither compares the full image JAR with the
historical qualified JAR nor runs or tests the `neural-embeddings` production build.
Those false values mean unverified, not a demonstrated binary mismatch or profile failure.
Existing local JAR qualification and CI publication are separate evidence. Production
remains NO-GO until the exact production image/build profile has separate supporting
qualification, and all target preflight, backup/restore, freeze, protection and approval
conditions below are satisfied. Do not set `confirm_image_qualification=true` based solely
on this preparation PASS. V8 acceptance and worker reactivation still need separate approval.

The command is also reusable in an explicitly authorized trusted runner with Docker and
GHCR read authentication, using `--revision`, `--manifest-digest`, `--config-digest`,
`--evidence-ref`, `--confirm-authorized` and `--output`. Output must be a new directory
outside the repository. It does not need frontend/configuration release inputs or a
production release ID, and its evidence is not a deployable `release.json`.

## 1. GitHub settings — owner must configure and verify

The YAML's `environment: prod` does not itself configure reviewers. In GitHub:

- Restrict the backend `prod` environment to `main`; require an authorized reviewer,
  prevent self-review and disable protection-rule bypass where supported.
- Restrict repository/workflow administration and protect changes to release workflows,
  scripts and qualification evidence through review and required CI checks.
- Keep production secrets only in the protected backend environment. Require a separate
  review for each migration and reactivation dispatch. Freeze competing deliveries
  and relevant `main` changes throughout both phases.

The workflow requires the operator to attest these settings, but does **not** query
GitHub to prove them. Unsupported or unverified review protection remains NO-GO.
See GitHub's [environment protection documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

Secret names: `VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`, `VPS_PORT`, `VPS_DEPLOY_PATH`,
and automatically supplied `GITHUB_TOKEN` (used as `GHCR_TOKEN`). Variable names:
`VPS_HOST_KEY` and `VPS_ENV_FILE`. No secret values belong in workflow inputs or evidence
references. Existing private VPS application credentials remain unchanged.

## 2. Prepare external evidence — approved operator only

Confirm the actual deployment root, env-file path, validated V7 release, running
containers and database agree. The scripts require `/opt/ai-policy-investigator` and
the existing project/database/service contracts; a mismatch is a blocker, not a
reason to guess another target. The actual paths, release IDs, host pin and published
SHAs/digests have not been supplied or checked here.

Use [DEPLOYMENT.md](DEPLOYMENT.md#operator-commands-for-an-existing-release) for the
existing Compose status/exec/stop/start helpers and
[backup commands](DEPLOYMENT.md#postgresql-backup). Before migration:

1. Establish an approved writer and cross-repository delivery freeze. The controller
   restarts the frontend and requires `/healthz` = 200, `/` = 200 and anonymous
   `/api/auth/me` = 401. The freeze must survive frontend restart and permit these
   probes plus authorized read-only acceptance checks. No ingress freeze is implemented
   or independently verified by this change; a blanket 503 maintenance page is incompatible.
2. Drain active work where possible, then stop only this project's frontend/backend.
   Leave PostgreSQL and all persistent volumes intact. Verify target-specific V7
   preflight using the reviewed `scripts/qualification_v8_preflight.sql`:

   ```sh
   backend_compose exec -T --user postgres postgres psql -X -U postgres -d investigator \
     -v expected_database=investigator -v target_version=7 < "$V8_PREFLIGHT_SQL"
   ```

   `V8_PREFLIGHT_SQL` is the operator-approved path to that file; verify its checksum
   before use. The automated release now bundles it and repeats it on the actual target.
3. Produce a private V7 `pg_dump -Fc`, verify its SHA-256 and restore **that exact dump**
   into a fresh isolated PostgreSQL 16/pgvector database with matching roles and ACLs.
   Require successful restore and V7 preflight there. A readable archive listing alone
   is insufficient. Retain the backup, matching V7 images and recovery prerequisites.
4. Record private before/after counts and content fingerprints covering judge accounts,
   departments, memberships, READ grants, PDF/version/evidence data, investigations,
   reviews, `demo_access` and `demo_meta_budget`. Do not publish row contents or hashes
   of passwords. Do not reprovision judges, reset quotas/refund attempts or edit leases.
5. Review the already published backend/model-init/frontend revisions and the exact
   linux/amd64 backend **child manifest digest**. Record image/build-profile qualification.
   The production JAR includes `neural-embeddings`; matching SQL does not establish its
   whole-JAR identity with the separately qualified local JAR.

Keep these proofs in a protected change record binding the actual target, V7 release,
backup checksum/restore result, freeze, image digest/source/build profile and approvals.
The workflow's `evidence_ref` is only a non-secret record identifier, such as an internal
change-ticket ID using uppercase letters, digits, dot, dash and underscore. Entering
that reference does not prove that the referenced work happened.

## 3. Migration dispatch — workers explicitly disabled

With the backend stopped, the authorized operator edits only these existing values
in the actual protected VPS env file (preserve every other value, owner and mode 600):

```text
APP_WORKER_ENABLED=false
APP_INVESTIGATION_WORKER_ENABLED=false
```

Each flag must occur exactly once as an unquoted lowercase literal. Missing, empty,
duplicate, interpolated, quoted or non-boolean values fail closed. The production
overlay requires both inputs; the controller validates and pins them across Compose
calls, so a later env-file edit cannot silently enable workers in the active migration
process. Resolved values must both be `false` for migration; running-container flags
are checked again. Do not pass credentials or rely on runner-shell worker overrides.

In backend Actions, choose **Reviewed V8 production release → Run workflow → main**:

| Input | Migration phase |
| --- | --- |
| `operation` | `deploy` |
| `phase` | `migrate-v8` |
| `backend_sha`, `frontend_sha` | Approved published full 40-character revisions |
| `rollback_release` | Empty |
| `allow_migrations` | `true` |
| `expected_previous` | Actual approved validated V7 release ID |
| `approved_backend_digest` | Approved linux/amd64 backend child manifest digest |
| `evidence_ref` | Protected change-record identifier, never a secret or URL |
| `confirm_github_protection`, `confirm_write_freeze`, `confirm_image_qualification` | `true` only after the operator has verified these external requirements |
| `confirm_v7_preflight`, `confirm_v7_backup`, `confirm_isolated_restore` | `true` only after these actual target/backup checks have passed |
| `confirm_v8_acceptance`, `confirm_worker_reactivation` | `false` |

All confirmation inputs default to false. Missing or contradictory inputs fail before
registry/SSH work. The independent `prod` reviewer must inspect the protected proofs
before approval. Approving the job and entering attestations are distinct responsibilities.

The orchestrator binds the operator, reference, approved base/digest, phase and exact
confirmation set into `release.json`. It prepares and verifies the actual image archive,
then requires its eight embedded migrations (versions, filenames, Flyway checksums and
SHA-256 values) to equal the pinned historical [qualified inventory](verification/v8-artifact.json).
The transferred evidence file must match the SHA-256 pinned in `release_safety.py`.
The transport and VPS controller repeat the release checks; archive extraction still
proves the inventory comes from the image JAR. A bare staged manifest without the
attestation record is now refused.

Under the project lock, the controller requires the approved base and an existing
database with exactly V1–V7, runs the target SQL preflight, then applies only qualified
V8 with disabled workers. It runs V8 preflight after backend health, checks container
flags, starts/checks the frontend, and updates release markers only after all automated
checks pass. A stale base or failed step requires diagnosis and a new explicit dispatch;
it is never automatically retried onto a different release.

## 4. V8 acceptance and separate reactivation approval

Keep the freeze and false flags. The operator must verify preserved data/fingerprints,
judge identities/private departments/READ grants, investigations/results/reviews and
unchanged quota counters, plus authorized old PDFs and cross-department denial. These
reads require no new model request. A changed counter or unexplained data difference
is NO-GO. Do not upload, seed, reprovision or start a new investigation as a smoke test.

After acceptance, explicitly approve resuming queued work: reactivation can consume
real Meta attempts, and long maintenance may already have expired jobs/deadlines.
Privately set both existing flags to `true`. Dispatch the **same workflow separately**:

| Input | Reactivation phase |
| --- | --- |
| `operation`, `phase` | `deploy`, `activate-v8` |
| `backend_sha`, `frontend_sha`, `approved_backend_digest` | Exactly the migration release's approved images |
| `expected_previous` | The successfully validated disabled-worker migration release ID |
| `allow_migrations`, `rollback_release` | `false`, empty |
| `evidence_ref` | Protected record covering V8 acceptance and reactivation approval |
| Common GitHub-protection/freeze/image confirmations | `true` |
| V7-preflight/backup/restore confirmations | `false` (not the confirmation set for this phase) |
| `confirm_v8_acceptance`, `confirm_worker_reactivation` | `true` |

The controller requires V8 history, the preceding validated `migrate-v8` phase, identical
backend/frontend/configuration SHAs, configuration/runtime hashes and all image digests.
Both explicit worker literals must be `true`; no migration permission is accepted.
Keep tooling `main` unchanged between the two runs. Verify the running flags, V8
preflight and health, then approve traffic reopening and monitor actual job/usage states.
No budget, counter, permission or account is reset by either phase.

## What success proves — and what it does not

Automated checks: manual-event restriction, exact confirmation schema, approved target
base and backend digest, qualified embedded SQL, explicit/pinned phase worker flags,
existing-database/phase history, actual target SQL preflights, archive/content checks,
same-image reactivation, health/routing and existing rollback guards.

`VALIDATED` means those automated deployment checks passed. `releaseSafety` records
the operator confirmations with `external_checks_verified_by_automation=false` and
`binary_identity_verified=false`. Results separately identify actual target preflight
and qualified-inventory verification; both the Actions summary and retained release
records state the distinction. Backup, isolated restore, freeze, GitHub settings,
image qualification and business acceptance remain external operator/reviewer duties.
No checkbox proves completion, currency, scope or authenticity of an external record.

Production remains **NO-GO** until those external duties have real supporting evidence,
the selected production image/build profile is qualified beyond SQL identity, and
GitHub review protection is actually configured. If all pass, the existing two-phase
workflow can be approved; this document does not approve or perform it.

Rollback remains an explicit `operation=rollback` with a retained validated release ID,
empty image SHA inputs and `allow_migrations=false`. Existing exact-history, archive,
health and routing guards remain. After V8 commits, rollback to V7 needs a separately
approved fresh-database restore and reviewed switch as described in the
[V8 recovery plan](V8_PREPRODUCTION.en.md#realistic-rollback). Do not delete Flyway history,
rely on automatic reversal, or use `pg_restore --clean` against V8 to remove V8-only
helpers. Restoring data cannot reverse a transmitted provider request or its cost.

Local hardening checks: **196 Python tests passed**, including 23 focused safety tests.
Workflow/Compose YAML structure, Python syntax, documentation links and shell snippets
were validated locally. Hash comparisons confirmed 73 protected application, migration,
dataset, qualified-JAR and historical-evidence files unchanged. No hosted workflow,
publication, VPS connection, deployment or real Meta request was performed.
