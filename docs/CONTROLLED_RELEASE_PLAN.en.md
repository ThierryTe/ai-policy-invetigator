# Controlled hackathon release — October 31, 2026

**Preparation only. Production NO-GO.** No publication, workflow dispatch, VPS
access, migration or deployment was performed. Production V7 and existing required
`prod` reviewers are operator-supplied facts; this audit did not inspect the target
or change environment protection. Issue [#14](https://github.com/ThierryTe/ai-policy-invetigator/issues/14)
authorizes the local replacement qualification only. It does not authorize publication
or production delivery.

## Verified starting point

| Item | Evidence and limit |
| --- | --- |
| Corrected local backend | JAR `6e57c1852c96ac87f335453cad6f36324d94ff76b83e1f52f0821b5b37a8867b`; linux/amd64 manifest `sha256:a0373a4558724c868de46069912741297145f41e3b71817ab41c09422fa8b3cf`; config `sha256:29bfd30f5c3c54a49ee741fd9cb220a6697e787634068b178b02b6d7c124dfbb`. Local PASS: 269 gates, real offline inference, isolated Spring startup. This image has no source/revision labels and is not a source-bound published release. |
| Backend remote main | API snapshot: `afa68f0c62ba502f213a4235e6f281a1a5fb17cd`. Of 67 qualified build-input files, only local `pom.xml` and `deploy/backend/Dockerfile` differ from that commit. The correction therefore has no remote release revision yet. The new runtime harness is also local. |
| Frontend remote main | API snapshot: `a07f52c25aead414ac08e6593667f864a4c33a20`. Authentication changes are local: routing/bootstrap, auth/guards/navigation, shell/login and synthetic browser coverage differ from remote. There is no remote revision for the tested fix yet. |
| Frontend evidence reused | 62 unit/routing tests, 8 synthetic Chromium tests and clean production build, as recorded in the adjacent frontend `docs/AUTH_RELEASE_REVIEW.md` and supplied by the operator. They were not rerun here. They do not prove live V7 compatibility or production authorization. Local input hashes were recorded for later source binding. |
| Historical records | Original runtime FAIL, historical JAR MISMATCH and all V1–V8 SQL/evidence remain unchanged. Existing local migration/security qualification is reused, with its original artifact scope. It does not establish target readiness or qualify a different image automatically. |

Read-only API snapshots and reconciliation details are under
`/private/tmp/controlled-release-preparation-001/`. The local backend qualification
is under `/private/tmp/v8-offline-runtime-replacement-001/`. Retain these private
records outside temporary storage before depending on them for release review.

## Smallest publication path and approvals

1. Obtain **image-publication approval**, covering reviewed backend/frontend source,
   model-init publication, GHCR writes and discovery-channel updates. Main pushes
   already publish automatically after CI. Approval must precede a main update that
   triggers publication; the `prod` deployment review does not gate this job.
2. Have the owners record the backend correction and harness plus this reviewed
   preparation as full source revision **B**, using their approved source-control
   procedure. No Git commands were run by this audit. Use the normal backend CI:
   `verify.yml` calls `publish-images.yml` after verification and publishes backend
   and model-init at `sha-B`. Existing tags are verified/reused, never overwritten.
3. After B is known, the frontend owner fills both markers in
   [the handoff template](release-preparation/frontend-publication.patch.template)
   with that same full backend tooling SHA and records the reviewed auth fix as
   revision **F**. This removes the legacy deployment call and pins both the reusable
   publication workflow and the code it executes. Use normal frontend CI/publication
   at `sha-F`. No backend migration is needed to publish or deliver this frontend.
4. Retain each `publication-<component>-<run>-<attempt>` JSON artifact. It now binds
   application repository/SHA, actual tooling SHA, run URL/attempt, platform and each
   image's index/child-manifest/config digests. These records support review; they
   are not cryptographic build attestations. Registry SHA tags are a convention;
   use their verified content digests for approval and delivery. The existing
   `release-main` channel is discovery only.

The publication workflow now requires an explicit frontend `tooling_sha`; old
frontend callers will fail closed until the owner applies the handoff. Backend
callers use their own validated source SHA. Both repositories' package permissions
and reusable-workflow access must work on the next authorized CI run; no access
settings were changed or certified here. Required third-party Actions retain SHA pins.

## Reconcile the published candidate once

- Record actual **B**, **F**, tooling/configuration revision **T**, CI run IDs and all
  published linux/amd64 child-manifest/config identities, including model-init.
  No candidate B/F or corrected published digest exists in the evidence inspected
  here. Never copy the old failed `dca3389c…`/`baf9cf59…` identities into a new approval.
- Compare B's runtime inputs with `build-inputs.json` from the local qualification;
  compare F's application/build inputs with `frontend-local-inputs.json` from this
  audit. Documentation/workflow changes do not themselves invalidate unchanged
  application tests. Review any application, dependency or build-input difference
  before reusing their results. Source labels alone are not proof of file equality.
- Use **Prepare backend qualification only**, with B and the *new published*
  child-manifest/config digests, a new evidence reference and explicit artifact
  preparation consent. This existing read-only workflow verifies source labels,
  config/layer content and V1–V8 identity without a target or migrations. Stale
  identity defaults were removed. Keep its GitHub run/artifact digest as an
  independent anchor when downloading; its checksums alone are not that anchor.
- Extract/hash the JAR from that exact verified image. Record full JAR equality
  separately from application/dependency/loader-entry equality. The existing
  `verify_backend_qualification.compare_jars` helper can provide a static delta;
  its CLI is intentionally anchored to the historical failed candidate and must
  not have its old trust constants replaced or be presented as new qualification.
- A CI rebuild can change JAR ZIP bytes, image labels/config, timestamps and layers.
  Do not expect the local JAR/image digests to survive. Use the existing
  `scripts/test_offline_embedding_runtime.py` once on the exact published candidate,
  with its actual JAR/config hashes and a new output directory. It checks default
  engine/offline behavior, fresh scratch, native bytes and isolated startup. Keep
  the preserved failed JAR as its baseline; its strict class/dependency comparison
  must pass. Any unexplained delta is a review blocker, not permission to weaken
  the check. This necessary exact-image qualification replaces no historical result.
- Existing V7→V8 migration/security suites and frontend tests need no blanket local
  repetition when their source/SQL inputs are unchanged. Normal mandatory CI still
  runs. Retain the new published-image qualification alongside the local PASS and
  all FAIL/MISMATCH records. Approve the resulting candidate identities explicitly.

## Independent frontend delivery: blocker and owner handoff

The latest observed frontend main run
[40950112694](https://github.com/ThierryTe/ai-policy-invetigator-frontend/actions/runs/40950112694)
failed validation before any jobs ran: line 50 could not fetch the called backend
deployment workflow at `main`. That is historical evidence, not a claim that the
file is still absent: the current backend tree contains it.

The current structural blocker is exact: frontend `verify.yml` calls deployment
through the reusable interface, but the backend deploy job requires a backend-main
`workflow_dispatch`. [GitHub's reusable workflow context follows the caller](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations). Even a
successful current publication would not make that call deliver the fix. Manual
dispatch offers only `migrate-v8` and `activate-v8`; `validate_release` requires V8
artifacts, activation requires a preceding identical migration release, and the
controller recreates model-init/backend. Neither phase is a frontend-only path.

**Release owner action:** approve a separate frontend-only delivery/rollback
procedure. The template fixes CI/publication wiring; it does not create a deployment
path. No such production path was implemented, executed or assumed by this audit.
The approved procedure must:

- Use the existing production lock and `prod` review, or the same operator-reviewed
  target change control. Select only the approved F image by verified platform/config
  digest and retain the previous complete frontend artifact. Reuse allowlisted
  archive/content checks from existing tooling.
- Read and retain the actual V7 backend, model-init, database/history, worker flags,
  network/volume and runtime-config identities. Replace only the frontend service
  with `--no-deps`, `--no-build`, `--pull never`; do not call the all-component deploy
  script, initializer, Flyway, quota/provisioning tools or either V8 phase.
- Check existing V7 `/api/auth/login` and bearer `/api/auth/me` compatibility through
  read-only account use; source compatibility alone is insufficient. Check the
  complete asset set, SPA deep links/refresh, health/root 200, anonymous auth 401,
  CSP/no-store, denied resources, logout and browser Back. Do not start an investigation.
- Keep a frontend-only delivery record bound to the retained V7 base, new F/config
  identities and previous frontend. Do not mark an all-component/V8 release validated.
  Reconcile this record with the actual base and chosen F before later migration.
- Roll back only the frontend and repeat those checks. Returning to the older
  memory-only auth frontend requires clearing only `ai-policy-investigator.session`
  in affected browser tabs, without reading/exporting tokens, then fresh login.
  Backend services and database history stay untouched.

This handoff is prepared for the owners; it was not applied to the frontend checkout
or sent to an external service. Independent UI delivery remains blocked until its
specific production procedure, candidate identity and approval exist. Do not bypass
the V8 guards to create that path.

## Later V7→V8 backend window

Use the existing [V8 deployment runbook](V8_DEPLOYMENT_RUNBOOK.md) and
[recovery plan](V8_PREPRODUCTION.en.md#realistic-rollback), with the new candidate
identities. No workflow dispatch is authorized by this document.

| Order | Operator action / required evidence |
| --- | --- |
| Target readiness | Obtain **production deployment approval**, independent of publication. Reuse existing `prod` required reviewers; confirm applicable main-only/protection settings rather than recreating the environment. Record actual target, env path, SSH host pin, retained validated V7 release ID, image identities, capacity and existing PostgreSQL/pgvector configuration. Freeze the approved T revision through migration and activation. |
| Freeze and backup | Establish a probe-compatible ingress/writer freeze, drain work, stop only this project's app services and preserve PostgreSQL/volumes. Run the existing read-only V7 SQL preflight with the real database name. Make a private V7 `pg_dump -Fc`, record its SHA-256, and restore **that exact dump** into a fresh isolated database with required roles/extensions/ACLs; require restored V7 preflight and data verification. Archive listing alone is insufficient. |
| Preservation | Record private before/after counts/fingerprints for existing judge identities, private departments/WRITE and shared READ grants, policies/PDFs/results/reviews, queues/leases, `demo_access` and `demo_meta_budget`. Do not reprovision judges, change credentials, reset quotas, refund attempts, edit leases/deadlines or log sensitive row content. Confirm option A: private judge WRITE, shared-source READ only. |
| Migrate | Set both worker flags to literal `false` in the approved private configuration. Dispatch backend main with `phase=migrate-v8`, `allow_migrations=true`, B/F, the **published qualified backend child digest**, actual `expected_previous` and the protected evidence reference. Set only the phase's genuine confirmations after their checks pass. Independent `prod` review must inspect the proofs. |
| Accept V8 | Confirm exactly V1–V8, unchanged V1–V7 checksums, V8 preflight, both running workers disabled, health/routing, old content/results/reviews, judge isolation/shared-read boundaries and unchanged accounts/grants/counters. Keep the freeze. Existing checks can use old completed data and no Meta calls. Health alone is not business acceptance. |
| Activate | Obtain **separate worker-reactivation approval**, acknowledging queued work can consume Meta attempts. Dispatch `activate-v8`, `allow_migrations=false`, the migration release as `expected_previous`, identical B/F/T, images/config/runtime hashes and the activation confirmations. Both worker literals become `true`. Do not advance tooling main between phases. Verify flags, health, lease recovery/queues, errors and budget consumption before reopening. New real Meta acceptance, if needed, requires explicit authorized scope/budget and is not part of this preparation. |
| Rollback | Before V8 commits, confirm clean V7 state and use retained validated V7 artifacts. After V8 commits, the controller correctly refuses V7 application-only rollback. Obtain a separate recovery approval: retain V8 diagnostic state, restore the verified V7 dump into a fresh database, verify roles/data/history and switch with matching V7 artifacts. No history deletion, Flyway repair, volume deletion or `pg_restore --clean` against V8. Account for writes/costs after backup. |

## Shortest next actions

1. Approve publication scope; review and record B, then fill/apply the frontend owner
   handoff and record F. One normal successful CI/publication run per candidate.
2. Capture published provenance, prepare/qualify the exact published backend once,
   and approve the actual digest tuple. Retain all old evidence unchanged.
3. In parallel with backend release preparation, approve the frontend-only target
   procedure and deliver F independently against unchanged V7, with UI-only rollback.
4. Only after target V7 preflight, real backup/isolated restore and deployment review
   pass, execute migrate-v8. Verify V8/judge preservation, then obtain the separate
   activation approval. Until these gates pass, **production NO-GO**.
