# Follow-up for preparation run 41196074748

This is a preparation-only procedure. It neither authorizes production nor changes
the historical V8 qualification. Do not rebuild or republish an image to perform
the comparison. Preserve the historical JAR and Surefire reports before any new
Maven invocation: `package`/`verify` in the original workspace can replace them.

## Established evidence

The public GitHub API reports success for [run 41196074748](https://github.com/ThierryTe/ai-policy-invetigator/actions/runs/41196074748),
attempt 1, on `main`, tooling revision
`afa68f0c62ba502f213a4235e6f281a1a5fb17cd`. Its preparation and upload steps succeeded.
The retained artifact is `backend-qualification-41196074748-1`, ID `13040377866`.
The API records its ZIP digest as
`sha256:08cbb4078946660503280efe740d172c1c56c62d2e0aa9428436f0f76ebe202b`
and its expiry as November 7, 2026, 11:15:29 UTC. These are artifact metadata;
they do not establish the two outstanding gates.

The existing local historical JAR hashes to
`1ce613cc96861e9c41f5a3cf9a9bd47f5035aa629df561770070a783d93d4008`,
exactly matching `docs/verification/v8-artifact.json`. All 15 historical XML
report hashes match `v8-qualification.json`: 172 tests, zero failures, errors or
skips. This is reuse of existing results, not a new Java test run.

The image Dockerfile packages with `-Pneural-embeddings -Dmaven.test.skip=true`.
That profile adds `spring-ai-starter-model-transformers`. The historical JAR has
no packaged transformer, ONNX Runtime or tokenizer library. CI runs Java tests
with `database-tests`, then builds the production image without executing its
embedding implementation. `SecurityDatabaseTest`, `V8MigrationDatabaseTest` and
the documentation contexts explicitly disable real embeddings and inject a mock.
Those tests remain useful evidence for their original dependency set and scope;
they do not prove real production-profile embedding initialization or inference.
The approved source revision's public `pom.xml` was retrieved read-only and is
byte-identical to the current local POM.

## Smallest first step: compare the existing artifact offline

Download the **original ZIP** for artifact `13040377866` through an authenticated
GitHub session. Do not re-ZIP an extracted directory: the ZIP's independent digest
is the trust anchor. No preparation workflow rerun or registry pull is needed.
GitHub returned HTTP 401 to the unauthenticated ZIP request in this session;
there was no available browser session or cached approved Docker image.

From the repository, run the following with the actual downloaded path and a new
output filename:

```sh
python3 -B scripts/verify_backend_qualification.py \
  --artifact-zip /absolute/path/backend-qualification-41196074748-1.zip \
  --output /tmp/backend-gates-with-prepared-image.json
```

The tool verifies the ZIP digest, its fixed three-file inventory, file checksums,
run/tooling identity, approved source revision, manifest/config digests and receipt
scope. It binds the receipt to the unchanged historical evidence. It reads the
effective `/app/investigator.jar` directly from the saved layers, including
whiteout/replacement handling, without loading Docker or running application code.
It reuses image integrity and migration equivalence rather than redoing the
registry checks, layer DiffID hashing or migration qualification.

It reports both complete JAR hashes, all entry additions/removals/changes,
application class/resource equality, and dependency names **and bytes**. ZIP
timestamp/compression changes can produce different complete JAR hashes even if
all entry payloads match. Such a result is payload equivalence, not binary identity.
Presence of transformer libraries is also reported as static evidence only.

Exit codes: `1` means invalid/unusable input or evidence; `2` means a valid scoped
report with outstanding qualification gates. The tool deliberately has no overall
PASS exit: static inspection cannot certify production-profile behavior. Without
`--artifact-zip`, it checks the historical evidence and emits explicit blockers;
`binaryIdentityStatus=NOT_CHECKED` is distinct from a measured `MISMATCH`.
Outputs are new files outside the repository and cannot overwrite existing files.

## Decisions after comparison

1. **Full JAR identity:** only a complete SHA-256 match to the historical JAR closes
   this gate. If the image contains the additional neural runtime dependencies,
   a mismatch is expected, but remains an assumption until measured. No test run,
   normalized ZIP hash, matching source revision or matching SQL can turn different
   immutable JAR bytes into an identity match. An authorized operator must then
   decide whether to qualify the exact prepared JAR directly as a new artifact,
   retaining the old qualification and recording that identity was not established.
   This changes the qualification basis; it does not close the historical identity
   assertion. Do not silently set its boolean to true or replace historical evidence.

2. **Production build-profile qualification:** use the comparison to select the
   smallest justified new tests. First inspect all application/resource and core
   dependency differences. Unchanged code and dependencies support reuse of the
   corresponding historical results; unexplained changes require affected tests.
   A different Maven profile name or dependency presence alone is insufficient.
   For the neural dependency addition, new evidence must at least exercise real
   transformer auto-configuration, model/tokenizer hash verification, native library
   loading, and synthetic single/batched inference yielding finite, nonzero
   384-dimensional vectors through the application's `EmbeddingGateway`.
   Include an isolated application-context startup to detect conflicts introduced
   by the additional auto-configuration. No real Meta service is needed.

Use the **exact prepared JAR and its packaged dependency bytes**, on the approved
image's Linux/amd64 Java runtime. Override the image entrypoint with a dedicated
test harness so starting a verification container cannot accidentally start the
application, workers or migrations. Use only synthetic inputs and disposable local
fixtures; isolate outbound networking and provide pinned local model files. Any
database context test must use a disposable local database with synthetic settings.
Never mount production env files, credentials, application storage or Docker's socket
inside the test container. The pinned models already exist under `.local/models`;
validate their sizes/hashes using `scripts/fetch_embeddings.py`'s `verified` function
and `ARTIFACTS` constants, without fetching or rewriting production configuration.

Record the prepared JAR hash, image/config/manifest digests, packaged dependency
inventory, harness hash, model/tokenizer hashes, platform/runtime and exact test
results in new evidence. A local Maven rebuild with neural dependencies can help
develop tests, but its tests transfer to the prepared image only after the tested
application and runtime dependency bytes are shown to match. A successful isolated
embedding probe does not by itself establish whole-application compatibility.

The exact new test selection depends on the unavailable JAR delta. Do not rerun the
historical V1–V8 migration qualification or all historical suites solely to obtain
another green result. Target-side preflight, backups, operational acceptance and
deployment authorization remain separate from these preparation gates.

## Results of this follow-up

`python3 -B -m unittest discover -s scripts/tests -p test_verify_backend_qualification.py -v`
passed **22 tests** with zero failures/errors. Tests cover artifact provenance,
checksum and receipt bindings, duplicate/path ambiguity, layer replacement and
whiteout semantics, complete-byte versus payload comparison, dependency drift,
preservation of historical evidence, and blocked/report exit behavior.

The real baseline invocation verified the historical hash and 15 reports, then
returned exit `2` with `APPROVED_PREPARATION_ARTIFACT_REQUIRED` and
`PRODUCTION_PROFILE_RUNTIME_EVIDENCE_REQUIRED`. It performed no Java test execution,
new build or runtime qualification. Both requested gates remain unverified.
Both existing local model files passed their pinned size/SHA-256 checks without
downloads or writes. All 13 protected build, historical evidence and migration
files retained their original hashes.
No historical migrations, judge accounts, quotas or production configuration were
changed. No Git commands, VPS access, workflow dispatch or deployment occurred.
