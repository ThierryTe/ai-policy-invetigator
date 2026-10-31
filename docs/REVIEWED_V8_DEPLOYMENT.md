# Approved image pair: preparation and V8 approval boundary

Status: tooling prepared locally, production execution **not authorized or run**.
No Git commands, image rebuilds, production access, workflow dispatches, migrations
or production container restarts were performed while preparing this change.

The existing **Reviewed V8 production release** workflow in
`.github/workflows/deploy-production.yml`, on backend `main`, remains the only CI/CD
entry point. It retains the protected `prod` environment, pinned Actions, existing
SSH account/pinned Ed25519 host key, production concurrency group and VPS
`deployment.lock`. Source control owners must make this tooling available on
reviewed `main` through their normal process before either new operation exists
there. This document is not approval to do so or to dispatch it.

The reviewed pair is fixed in `scripts/reviewed_v8_release.py`:

| Component | Approved GHCR reference |
| --- | --- |
| Backend | `ghcr.io/thierryte/ai-policy-invetigator@sha256:97a96a48cb9e4ec47726cbcf7f9a7219ec174483165de23c9ed103e16ea813cb` |
| Frontend | `ghcr.io/thierryte/ai-policy-invetigator-frontend@sha256:89517d956a3d348e364b8028e8695c42d206fd9eb26e9adbe8a99b403feb64dc` |

The runner verifies registry manifests/configs and linux/amd64 source labels,
derives source revisions from those approved images, and reuses the already
published model-init at the backend's immutable SHA tag. Missing model-init or
incorrect labels is a blocker, never a build fallback. PostgreSQL stays pinned to
the previously verified `c72df104…` manifest / `56a5b20c…` config. The retained
source archive and running layers/configuration are compared regardless of Docker
store ID, using the already established archive-normalization explanation from
[V7_BACKUP_RESTORE.md](V7_BACKUP_RESTORE.md). No identity investigation is repeated.

The production env path is always
`/opt/ai-policy-investigator/.env.production`, regular/non-symlink, deployment-user
owned, mode 600. Its contents never enter logs/artifacts. No file discovery,
permission changes or secret-file edits are performed. Approved phase flags
override only the two worker flags in the controller's Compose process environment.

## One-time production inputs

Keep existing `prod` SSH secrets (`VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`, optional
`VPS_PORT`, `VPS_DEPLOY_PATH=/opt/ai-policy-investigator`) and pinned `VPS_HOST_KEY`.
Required reviewers/main-only protection must already be configured; the workflow
does not create or certify protection rules. Environment jobs wait for configured
reviewers before accessing secrets, as described in the
[GitHub Actions deployment documentation](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments).

Set these two protected `prod` variables from actual production records:

| Variable | Required value |
| --- | --- |
| `V7_DEMO_INVESTIGATION_ID` | The existing completed judge investigation UUID, never a local fixture ID. Missing/wrong/incomplete demo fails the original SQL qualification. |
| `V7_BACKUP_DIR` | Existing encrypted/access-controlled private backup directory outside `/opt/ai-policy-investigator` and repositories, deployment-user owned, mode 700, no symlinks. |

Disk checks require at least four times the database size plus 1 GiB free on both
the backup and Docker data filesystems. No pruning or automatic provisioning is
performed. Retain cluster credentials/configuration separately: a logical dump
does not include role credentials. Backup/restore does not expose or compare
password-derived hashes; that original limitation is preserved.

## Authorized preparation operation

After explicit dispatch approval, select the existing workflow on `main` with:

```text
operation=prepare-reviewed
expected_previous=<approved current validated V7 release ID>
allow_migrations=false
```

Leave `backend_sha`, `frontend_sha`, `prepared_release`, `rollback_release` and all
confirmation inputs empty/default false. The reported historical V7 release was
`r141093671636-11`; it must be approved against the production change record and
match `last-successful.json`, rather than being silently assumed current.

Preparation pulls/saves the approved images on the runner, verifies all archives,
and transfers an immutable release directory through the existing SSH transport.
It does not load candidate images on the VPS or start application code. Under the
existing lock, it verifies source content/topology/initializer/env permissions,
runs the unchanged `qualification_v8_preflight.sql` in V7, holds an exported
read-only snapshot automatically, and streams `pg_dump -Fc` plus the unchanged
`qualification_v7_backup.sql` source checks against that same snapshot.

It then verifies the checksum/archive listing and restores into a new PostgreSQL
container using the already loaded source image ID, a new dedicated volume,
`--network none`, no ports, Unix-socket-only PostgreSQL, generated rehearsal
passwords, the unchanged initializer, and the documented resource/security limits.
It checks mounts, labels, privileges, active interfaces and IPv4/IPv6 routes before
and after restoring. Restore uses `--exit-on-error --single-transaction`, retaining
owners/ACLs/triggers. Both original SQL scripts must pass on the restored data;
source/restored JSONL must match exactly. It checks production still has V7.

All dumps, checksums, fingerprints, env files and database stdout/stderr remain
private on the VPS. Nonempty stderr blocks success for private review. Successful
preparation stops only its own rehearsal container; the container and volume are
retained. Failed checks never produce a success record. No retention cleanup is
automated.

The safe Actions summary returns `PREPARED_AWAITING_V8_APPROVAL`, the retained
release ID, source/configuration revisions and manifest digests. Its private
`prepared.json` binds the release manifest hash and evidence location. This is
the **V8 approval boundary**: production app containers are unchanged and remain
in V7. No migration, restart or subsequent workflow is dispatched automatically.

## Single production deployment operation awaiting approval

After reviewing the successful private preparation evidence, approving the exact
image/build qualification, and arranging the probe-compatible public delivery
and external-writer freeze, dispatch the same workflow on `main` once with:

```text
operation=deploy-reviewed
prepared_release=<ID returned by successful prepare-reviewed>
expected_previous=<same approved V7 release ID>
phase=migrate-v8
allow_migrations=true
evidence_ref=<nonsecret approved change-record ID>
confirm_github_protection=true
confirm_write_freeze=true
confirm_image_qualification=true
```

Leave the three legacy backup/restore confirmation inputs false. They are earned
by actual automated verification on the VPS; the retained approval records only
the human approvals. Leave activation confirmations false and source SHA inputs
empty. Both reviewed images are fixed by code, so this operation cannot select a
different application image. No runner image preparation or new release transfer
is repeated for deployment.

Under one VPS lock, deployment verifies the immutable prepared release/current
base and config, records approval/run/operator/change IDs, stops only the exact
frontend and backend containers of this project, and performs a **new** V7 backup
and full isolated restore verification while both applications are stopped.
PostgreSQL and all production volumes stay in place. External writers/edge
maintenance are operator approvals, not claims of automated detection. A failed
backup/restore leaves the application stopped and V7 unmigrated; it never starts
V8 or automatically resumes writers.

Only after those checks pass does the existing release controller load the
retained archives and apply V8, with both worker flags pinned false. Its existing
Flyway inventory/history, ownership/RLS, image content, topology, health, and
public 200/200/401 routing gates remain enforced. The original V8 SQL preflight
runs in V8. Before either success marker advances, the original backup script's
fingerprint/metadata queries run again: all public table data except the changing
Flyway history, role/membership/extension/relation/ACL metadata and the completed
demo must match the frozen V7 source. Only the V8-intended policy/function
definitions and Flyway rows are excluded from that conservation comparison;
their new boundary is checked by the unchanged V8 preflight and qualified image
migration inventory. The full V7 qualification is never bypassed for backup or
restore.

No automatic retry follows an attempted deployment. `attempt.json` prevents reuse
after any partial stop/migration/health failure; inspect private evidence and
approve a recovery explicitly. The workflow never restores production, removes
volumes, seeds users/demo data, resets quotas, repairs Flyway history, or rolls
back the database. Use the existing V7 recovery guide for an approved recovery.

## Separate worker activation remains required

After V8 business/data/access acceptance, use the existing `operation=deploy`,
`phase=activate-v8`, `allow_migrations=false` path with `prepared_release` and
`expected_previous` both equal to the successful reviewed migration release ID.
Supply the backend/frontend SHAs and backend child digest from preparation's safe
summary and the existing activation confirmations (`github_protection`,
`write_freeze`, `image_qualification`, `v8_acceptance`, `worker_reactivation`).
Keep backup confirmation inputs false. Run from the same configuration/tooling
revision: the existing activation gate requires identical source, runtime,
configuration and all image manifest/config/source identities. This reuses the
same fixed digests and published model-init and pins both worker flags true;
no secret-file edit is needed. Worker activation can consume Meta attempts and
is never implied by migration approval.

## Validation scope

The Python regression suite, synthetic orchestration/failure tests and Compose
configuration checks run without production access. Their results establish
tooling behavior, not a real production backup/restore. Historical qualification
records remain unchanged. Live preflight/backup/restore results will exist only
after an explicitly approved preparation dispatch. The user has not approved any
dispatch or production change in this session.
