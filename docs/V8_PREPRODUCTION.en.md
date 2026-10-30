# V7 → V8 preproduction qualification — October 30, 2026

English companion to the [original qualification record](V8_PREPRODUCTION.md).
The original French record and all historical verification files remain unchanged.
This translation preserves the recorded results, option A decision and operational
conditions. It does not record a new test run or deployment.

**Reassessed verdict: GO for local V7 → V8 qualification under option A, explicitly
confirmed by the project owner.** Judges may write and import documents within their
private department. Synthetic documents shared from other departments remain strictly
READ-only. Investigations over shared sources remain permitted within quotas; analysis
does not grant document WRITE permission.

The earlier NO-GO interpreted the requirement as also prohibiting private writes.
The owner's explicit decision resolves that point. No code, migration or artifact
change was required. This GO applies to the qualified local artifact; it does not
validate the VPS or authorize deployment. The operator conditions below still apply.

No application code or migration was changed during qualification. No Git command,
VPS/production connection, deployment or real Meta request was made. Credentials were
generated for disposable containers and excluded from the evidence. All data was synthetic.

## Reassessment under option A

Existing evidence was reused without rerunning tests. The hashes and test counts of
**15 Surefire reports** matched `v8-qualification.json`: **172 Java tests**, with no
failures, errors or skipped tests. The JAR and eight migrations matched the SHA-256
values in `v8-artifact.json`. The **173 successful Python tests** were retained as
existing qualification evidence. No evidence gap was identified.

| Confirmed requirement | Assertions in successful existing tests |
| --- | --- |
| Shared READ without WRITE | `judgeReadonlySharedScopeRunsWithAdmissionAndMetaReservationsButWithoutContentWrite` checks `can_write_policy=false`, zero affected rows for policy/version UPDATE and rejected page/PDF/ingestion writes. `judgeProvisioningPreservesCompletedScenarioAndProvidesOnlyPrivateWriteAndTargetedRead` also rejects consent changes and reviews; an accidental extra ADMIN membership and WRITE grant cannot expand shared-source write scope. |
| Isolated private WRITE | The provisioning test uploads, ingests and versions a private PDF, then completes its investigation. A second judge cannot read its policy, PDF, evidence, job, extractions, findings or graph. `jdbcJpaAndConnectionReuseDenyOtherDepartment` and `jpaWritesCannotCrossDepartmentBoundary` also cover JDBC/JPA isolation. |
| Unauthorized sources and revocation | `judgeReadonlyRejectsHiddenScopesEvenThroughDefinerScheduling` rejects hidden sources, the wrong organization and missing membership, including DEFINER scheduling. `judgeReadonlyRevocationStopsReservationsAndAsyncPersistence` and the migration test cover revocation before and during processing. |
| Quotas and Meta budgets | `judgeReadonlyConcurrentSqlAdmissionsKeepQuotaReservations`, `demoMetaIndividualBudgetIsAtomicAndInvalidLeaseDoesNotDebit` and `demoCollectiveMetaBudgetIsAtomicAcrossDifferentJudges` demonstrate concurrent caps. Exhaustion and retry cases prevent an additional call. `demoReservationRollsBackWithItsWorkAndRuntimeCannotAlterLimits` denies direct runtime access to limits. |
| RLS and ordinary users | `judgeAnalysisDefinerIsRestrictedAndUnsafeOwnershipBlocksStartup` and `effectiveRolesFunctionAclsAndForcedRlsAreSafe` cover DEFINER/INVOKER, ACLs, FORCE RLS and NOBYPASSRLS owners. `ordinaryReadersStillNeedWritePermissionToAnalyze` preserves ordinary READ/WRITE distinctions; `explicitGrantWorksAndRevocationTakesEffectForJpaAndSql` covers grant and revocation. |

Recorded cases, hashes, reassessment grounds and remaining conditions are in
[v8-qualification.json](verification/v8-qualification.json). Assertions are in
[SecurityDatabaseTest](../src/test/java/com/tewendelabs/investigator/SecurityDatabaseTest.java)
and [V8MigrationDatabaseTest](../src/test/java/com/tewendelabs/investigator/V8MigrationDatabaseTest.java).
The option A reassessment changed only the original report and qualification JSON;
the artifact report, tests, application code and migrations were unchanged.

## Recorded results

Environment: Java 21, PostgreSQL **16.10**, `pgvector/pgvector:0.8.0-pg16`.
Migrations run through the `investigator_owner` login. Application operations use
`investigator_app`, a member of `investigator_runtime`. The superuser is used only to
initialize roles/extensions, prepare fixtures, observe assertions and inject test faults.

| Check | Result and evidence |
| --- | --- |
| Existing regression suite | **166 Java tests**, including **93** in `SecurityDatabaseTest`, with no failures, errors or skips. |
| Actual upgrade | **Six additional tests** in `V8MigrationDatabaseTest`. Flyway first targets V7; fixtures are created; Spring Boot then applies only V8. |
| Data preservation | Counts and row-content fingerprints for every public table except Flyway history match before/after upgrade. V1–V7 history matches in full. Synthetic PDF bytes, 21 versions, seven investigations, extractions, a completed result and a CONFIRM review survive. |
| Backup/recovery | V7 `pg_dump -Fc` restored with `pg_restore --exit-on-error` into a **fresh database** in the same cluster. Data and V7 history match; Flyway validates; roles and ACLs remain correct. |
| Migration failure | Renaming the expected policy injects failure after helper creation. Transaction rollback leaves no V8 history entry or V8 helper residue. Restoring the policy permits one successful migration; the next run applies zero. No `repair`. |
| Functions and roles | `can_analyze_policy` is DEFINER; scope and runnable helpers are INVOKER. Owner is non-superuser, NOBYPASSRLS `investigator_owner`; runtime EXECUTE is granted, PUBLIC EXECUTE denied, search path fixed, app-to-owner membership absent. Eight content tables enforce ENABLE/FORCE RLS. An owner connection without an actor sees zero policies. |
| SQL preflight | The [operator script](../scripts/qualification_v8_preflight.sql) passes in V7/V8, rejects disabled FORCE RLS and a BYPASSRLS owner, and checks history/checksums, ownership, control-plane exposure and V8 functions. |
| Queued V7 work | Ordinary users and private/shared-READ judges complete asynchronously with four accounted attempts. An older request retaining READ after losing WRITE becomes analyzable for the judge in V8. |
| RUNNING V7 work | An unexpired lease is not stolen. After expiry, recovery uses a new token, the same deadline and an unchanged checkpoint; only three new calls are needed. The old token is rejected. |
| Revocation | A queued V7 request without membership fails before transport. Revoking a shared source during a blocked simulated call in another thread permits no extraction/result persistence: one charged attempt, FAILED. Existing regression also covers consent, expiry, revocation between retries and immediate result invisibility. |
| Ordinary users | Writer/ANALYST capability preserved; VIEWER and ordinary READ-only analysis refused. Explicit READ → WRITE restores ordinary analysis. Department/organization isolation, JDBC/JPA and existing-JWT revocation are covered. |
| Shared judges | Analysis works without `can_write_policy`. Policy/version UPDATE, ingestion, replacement PDF, consent change and review are denied on shared sources. Unknown/NULL/duplicate UUIDs, bad lineage, future/unindexed/unconsented sources fail through Java, RLS and DEFINER scheduling. |
| Quotas/budgets | Investigation/pending admissions allow at most two of six concurrent requests; individual model budget allows two of six reservations; collective budget allows one of six across judges. Persistent limits, idempotency, rollback, invalid leases, expiry after lock waits and every retry are checked. Runtime cannot access quota tables or `reserve_demo_work`. |
| Delivery tooling | **173 Python tests**, including five artifact-integrity tests. Delivery/rollback gates and SQL-drift rejection included. No delivery script executed. |
| Final JAR | Exactly V1–V8, byte-identical to sources. SHA-256: `1ce613cc96861e9c41f5a3cf9a9bd47f5035aa629df561770070a783d93d4008`. Inventory/checksums: [v8-artifact.json](verification/v8-artifact.json). |

Summaries and case names are in [v8-qualification.json](verification/v8-qualification.json).
Original Surefire reports remain under `target/surefire-reports/`; local logs are under
`/tmp/v8-qualification/`. The initial sandboxed Maven attempt could not reach Docker;
the authorized full suite subsequently passed outside the sandbox.

[v7-migrations.sha256](verification/v7-migrations.sha256) preserves the earlier local
`/tmp/judge-v8-original-migrations.sha256` reference. V1–V7 match this reference, the
JAR and local Flyway history. Production history was not inspected; the operator must
compare it with the reference and last validated release before delivery.

SQL semantics were checked through Context7 against PostgreSQL 16 documentation for
[forced RLS/BYPASSRLS](https://www.postgresql.org/docs/16/ddl-rowsecurity.html) and
[function ownership, PUBLIC EXECUTE and search paths](https://www.postgresql.org/docs/16/sql-createfunction.html).
The actual VPS configuration is not certified by local tests. Spring scheduling is
disabled for deterministic ordering; real worker processing runs asynchronously in tests.
Millisecond measurements on small fixtures do not estimate production migration time
or recovery time for production-sized data.

## Repeat the local qualification

Prerequisites: Java 21, cached Maven dependencies, local Docker and the stated image.
Dotenv loading is disabled; tests supply their own isolated database connections.

```sh
SPRINGDOTENV_ENABLED=false mvn -B -o -Pdatabase-tests verify
python3 -B -m unittest discover -s scripts/tests -v
python3 -B scripts/qualify_v8_artifact.py --output /tmp/v8-artifact.json
```

Migration tests alone:

```sh
SPRINGDOTENV_ENABLED=false mvn -B -o -Pdatabase-tests -Dtest=V8MigrationDatabaseTest test
```

The JAR audit rejects missing migrations, JAR/source differences and V1–V7 drift
against the reference. It does not start containers or access the network.

## VPS plan for later operator execution

1. **Prepare under confirmed option A.** Preserve private judge WRITE and strict shared
   READ. Retain validated V7 images/manifests and prepare immutable V8 images with an
   inventory extracted from the exact linux/amd64 JAR. Keep automatic migrations
   blocked until operator preflight and a restorable backup pass. Do not upgrade
   PostgreSQL/pgvector in this release. Check disk capacity, topology, the existing
   volume, private-file permissions without printing secrets, roles/extensions and
   exact V7 history. Use one delivery lock.
2. **Maintenance and V7 backup.** Block new requests at application ingress, finish
   RUNNING calls if possible, then stop only this project's frontend/backend. Leave
   PostgreSQL and unrelated services running. Record counters, states, deadlines and
   versions without document content. Follow the [private backup procedure](DEPLOYMENT.md#postgresql-backup):
   administrator `pg_dump -Fc`, private storage outside repositories, SHA-256, readable
   archive and **successful restoration in isolation**. Preserve role/authentication
   prerequisites separately; a database dump excludes cluster roles. Without a
   restorable backup, stop the release.
3. **V7 preflight.** Run `qualification_v8_preflight.sql` read-only through the container's
   local administration channel with `expected_database=investigator` and `target_version=7`.
   Retain output privately. Reject any role, RLS, checksum or history mismatch without
   bypassing validation or using `flyway repair`. Compare V1–V7 hashes with V7 artifacts.
4. **Apply V8.** Set the existing Compose flags `APP_WORKER_ENABLED=false` and
   `APP_INVESTIGATION_WORKER_ENABLED=false` in the operator's private configuration.
   Keep public ingress in maintenance. Explicitly permit this release's migration,
   load validated images and start V8 through existing tooling. The controller reuses
   PostgreSQL without recreation and never restores a database automatically.
5. **Verify before reopening.** Run V8 preflight, confirm eight successful migrations,
   unchanged V1–V7, preserved counters/data and correct roles/RLS/ACLs. Check internal
   health, local model readiness, HTTP 200 for health/root, anonymous auth 401, then
   authorized login and old PDFs/results/reviews plus unauthorized-source denial.
   These checks need no new real Meta processing. Health alone is insufficient.
6. **Resume and monitor.** After validation, re-enable flags and recreate only the
   backend using the same images/configuration. Check health and reopen traffic.
   Monitor QUEUED/RUNNING, leases, FAILED/PARTIAL and access/budget codes. Do not reset
   quotas or artificially extend deadlines; long maintenance may expire work. An
   already transmitted call may have been charged and its reservation stays consumed.
   Retain backups, manifests and evidence. Finalize release state only after controller
   checks and business verification pass.

Operator example, **not executed against the VPS during qualification**, using the
`backend_compose` helper from [DEPLOYMENT.md](DEPLOYMENT.md):

```sh
backend_compose exec -T --user postgres postgres psql -X -U postgres -d investigator \
  -v expected_database=investigator -v target_version=7 < scripts/qualification_v8_preflight.sql
```

Use `target_version=8` after migration. Success prints
`V8_QUALIFICATION_PREFLIGHT_PASS`, then rolls back the read-only transaction. It prints
no accounts, document text or passwords. Checksums are tied to the qualified JAR;
changing V8 requires requalification.

## Realistic rollback

- **V8 not applied, or its transaction failed:** confirm V7 history/functions, then
  restart validated V7. If SQL state is uncertain, keep the app stopped and restore.
  Do not delete Flyway history entries.
- **V8 committed:** replacing the JAR alone is not qualified. The controller rejects
  V7 against V8 history; do not bypass that gate. Neither Flyway nor this process
  provides automatic V8 reversal.
- **Restore:** stop traffic/workers, retain a V8 snapshot for diagnosis, restore the
  verified V7 dump into a **fresh database** with correct roles/extensions/ownership/ACLs.
  Check data, history and V7 preflight before switching. `pg_restore --clean` against
  V8 does not guarantee removal of functions that exist only in V8. Compose DB_URL
  explicitly targets `investigator`; from the administrative `postgres` database,
  with application connections closed, the operator can retain the old database under
  another name and rename the validated restore to `investigator`. This availability-
  affecting switch requires an explicit operator decision and is not automated here.
  Restart matching V7 images, check health/login/isolation/old results, then reopen.
  Do not delete volumes or reinitialize roles.
- **Possible loss:** writes since the backup may be lost. Restoring the database or
  rolling back application code cannot recall a Meta request or reverse its cost.
  If work resumed after backup, also preserve V8 state and reconcile counters before
  returning. Do not promise exact replay of external calls. Measure recovery time
  with production-sized restoration data.

## Automation

Available locally: V7 → V8/restore/transaction-failure tests through the Maven
`database-tests` profile, concurrency/quota/revocation tests, JAR audit and parameterized
V7/V8 SQL preflight. The controller already verifies archives/digests, Flyway compatibility,
locking, health and routing, and rejects incompatible rollback. Five artifact tests
are discovered by existing Python test discovery. No workflow or production configuration
was changed.

After review, a separate qualification step can invoke the JAR audit after `verify`,
retain summaries, and require evidence of a restorable backup, before/after SQL checks
and counter comparisons. Private dump archival, hashing and periodic restore rehearsal
can be automated. Secrets remain private. Option A is settled; release authorization
and production restore remain operator decisions. The current pipeline alone does
not prove that a restorable pre-migration backup exists.

## Files added by the original qualification

- `src/test/java/com/tewendelabs/investigator/V8MigrationDatabaseTest.java`
- `scripts/qualify_v8_artifact.py`
- `scripts/qualification_v8_preflight.sql`
- `scripts/tests/test_qualify_v8_artifact.py`
- `docs/verification/v7-migrations.sha256`
- `docs/verification/v8-artifact.json`
- `docs/verification/v8-qualification.json`
- `docs/V8_PREPRODUCTION.md`

Other outputs were ordinary Maven files under `target/` and local evidence under
`/tmp/v8-qualification/`. No pre-existing application source or V1–V8 migration changed.
The English-language audit adds this companion without altering those historical records.
