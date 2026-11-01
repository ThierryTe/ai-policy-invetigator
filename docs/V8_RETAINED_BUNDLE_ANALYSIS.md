# Exact V8 migration bundle reuse

Analysis performed on 2026-11-01 for migration release `r041243000818-11`.
No Git command, VPS connection, workflow dispatch, deployment, migration or worker
activation was performed. All verification tests use synthetic files locally.

## Evidence available outside production

| Source inspected | Observation |
| --- | --- |
| [Preparation run 41243000818 artifacts](https://api.github.com/repos/ThierryTe/ai-policy-invetigator/actions/runs/41243000818/artifacts) | `total_count=0` |
| [Previously identified migration run 41248256583 artifacts](https://api.github.com/repos/ThierryTe/ai-policy-invetigator/actions/runs/41248256583/artifacts) | `total_count=0` |
| [Repository releases](https://api.github.com/repos/ThierryTe/ai-policy-invetigator/releases?per_page=30) | No releases/assets returned |
| [Workflow at preparation revision a5b867b79504a59292cd52190908b51ec8c22080](https://github.com/ThierryTe/ai-policy-invetigator/blob/a5b867b79504a59292cd52190908b51ec8c22080/.github/workflows/deploy-production.yml) | No upload of the prepared configuration/runtime bundle |
| Accessible `.local` and temporary files | No retained `release.json` or `validated.json` for this release found |
| Local `ai-policy-config-b97c0d7-0208045*.tar.gz` and `configuration-public-check.tar.gz` | Generic 14-file packages, without a release manifest or V8 safety runtime; insufficient |

There is no recoverable immutable preparation/migration artifact in these sources.
The zero counts alone do not distinguish expiration, deletion or no upload. The
historical workflow establishes that this path did not upload its release bundle.
This inventory does not establish whether a private offsite copy exists.

The code retains `configuration/`, the versioned runtime, image archives,
`release.json`, `prepared.json` and `validated.json` beneath
`/opt/ai-policy-investigator/releases/r041243000818-11/`. This is a code-level
expectation, not a claim that those files are currently present or intact. That
location was not accessed. `last-successful.json` can later advance; the original
migration's `validated.json` is the appropriate success identity to preserve.

## What would prove exact reuse

An eligible configuration/runtime archive contains exactly:

- `configuration/<path>` for every entry of `release_artifacts.CONFIG_FILES`;
- the unmodified files at every entry of `release_artifacts.RUNTIME_FILES`.

No image archive, secret environment file, SSH material, dump, database evidence,
approval file or arbitrary extra path belongs in this configuration-only archive.
Directory entries for those fixed paths are permitted. A full retained release
may contain more material: it must not be uploaded publicly as a directory glob.

The archive digest and the digest of the original migration success record must
be pinned independently through an authenticated artifact identity, signed
provenance or the protected change record. A checksum distributed inside an
untrusted candidate archive does not establish its authenticity. A digest
calculated today establishes an initial inventory, not a historical approval.

Before reuse, check the success record's release ID, `result=VALIDATED`,
`rollback=false`, `releaseSafety.phase=migrate-v8`, migration acceptance flags,
qualified migration inventory and all configuration/runtime SHA-256 entries.
The record must describe the actual successful migration, not just successful
preparation. `prepared.json.releaseManifestSha256` additionally binds the original
preparation manifest; the migration success record binds the resulting deployed
identity. They are distinct proofs and must not be substituted for one another.

The offline tool `scripts/verify_retained_v8_bundle.py` implements configuration
and runtime byte verification against a pinned migration record:

```text
python3 -B scripts/verify_retained_v8_bundle.py \
  --bundle <retained-configuration-runtime.tar.gz> \
  --bundle-sha256 <independently-approved-archive-sha256> \
  --migration-record <original-migration-validated.json> \
  --migration-record-sha256 <independently-approved-record-sha256> \
  --release-id r041243000818-11
```

These are placeholders, not available artifacts or newly invented fingerprints.
The tool is read-only: it hashes bounded input bytes, rejects links, duplicates,
unexpected paths and missing files, and streams archive members without
extracting or executing them. It prints only fixed verification fields. It does
not authenticate the source of user-supplied digests, inspect production, verify
image archives, or authorize activation. No real verification of this migration's
bundle has succeeded in this session because the required inputs are unavailable.

## Assembly for a later separately authorized activation

Keep the reviewed workflow/driver on `main`; treat the historical bundle as data.
Use the fixed artifact ID and digest, not an artifact name that could refer to a
replacement upload. [GitHub's artifact documentation](https://github.com/actions/upload-artifact/blob/v7.0.1/README.md)
describes immutable artifacts; deletion/overwrite creates a new artifact identity.
Retention must cover the approval/recovery window and needs a separately retained
copy and provenance if a longer recovery period is required.

The intended assembly sequence is:

1. Verify the downloaded artifact's exact outer bytes and trusted migration record.
   If GitHub stores a ZIP containing a TAR, the ZIP artifact digest and inner TAR
   digest are different checks. Validate both; do not compare one with the other.
2. Validate every retained configuration/runtime file against the migration record
   before any registry/SSH step. Copy those exact verified bytes to a new activation
   directory. Preserve file modes needed by the original runtime and validate
   them against trusted packaging metadata; file content SHA-256 alone does not
   prove executable modes or ownership. Never execute an archive member while
   validating it.
3. Preserve the immutable archive and original manifests. Create a separate
   activation manifest with a new activation ID, fresh operator approvals and
   `expectedPrevious=r041243000818-11`. Derive its source identity and hash tables
   from the trusted migration record and the verified historical bytes.
   Do not replace its runtime scripts with current diagnostic scripts.
4. Reuse retained images, or resolve exactly the same approved digest identities
   and verify image contents/archives using the existing checks. Compare all
   fields enforced by `validate_target`, including image manifest/config/source
   and local references. Re-exporting an identical image can yield a different
   archive checksum; archive-byte identity and deployed image identity are
   separate checks. No substitute image or tag is approved by this analysis.
5. Keep `prepared_release=expected_previous=r041243000818-11`,
   `allow_migrations=false` and the exact activation confirmations. The server
   must still compare the candidate to the actual successful migration under the
   deployment lock and verify the V8 database history before changing services.

This would require an explicit verified-bundle assembly path in
`run_production_deploy.py`/`prepare_production_release.py`; the current path always
copies checkout files. No automatic fallback or activation workflow integration
has been enabled in this change. Implementing it before a real trust anchor is
available would not recover this release. Updating `configurationSha` alone, or
packaging current runtime code under an old revision, is forbidden.

## Options when no independent preparation artifact remains

| Option | Evidence needed | Consequence |
| --- | --- | --- |
| Recover an existing offsite immutable copy | Archive identity/provenance and independently pinned migration record; complete byte checks | Preferred; permits genuine reuse without editing historical content. No such copy was found here. |
| Export the retained migration directory in a future read-only VPS investigation | Separate authorization for VPS access; trusted `prepared.json`, original manifest and migration success record; custody/backup evidence | Can recover original bytes and verify mutual consistency. A new export is not retroactively an independently published artifact; document this trust limitation and have the recovered baseline reviewed. No migration or worker activation is needed for collection. |
| Reconstruct only the fixed files from the exact historical source revision | Source archive at `a5b867b79504a59292cd52190908b51ec8c22080`, authenticated source provenance, and independent migration file digests | A reconstruction, not the original preparation artifact. Every configuration/runtime byte must match the migration record, including the frontend contract mapping `.ci/frontend/compose.yaml` → `configuration/frontend/compose.yaml`. Without the migration record, equivalence to production cannot be established. Do not dispatch an old workflow ref to bypass the `main` guard. |
| Establish a new approved configuration/runtime baseline | Explicit new change scope, qualification and approval of the already-V8 target and a designed transition | A new release identity, not reuse of the migration bundle. Existing exact-reuse checks intentionally reject it. This is not authorized or implemented here and does not justify rerunning V8 migration. |
| Keep the current state pending evidence | No production action | Preserves disabled workers; activation remains blocked until a verifiable reuse path or separately approved transition exists. |

When the original success record and any independent trust anchor are both lost,
neither a current checkout nor a self-generated checksum can prove historical
bundle identity. The correct result is an unresolved evidence gap, not a fabricated
successful reuse claim.

## Local validation

`python3 -B -m unittest discover -s scripts/tests -v`: **327 tests passed**.
The eleven new retained-bundle tests cover independent digest anchors, unchanged
historical bytes, metadata-only substitution, altered configuration/runtime,
wrong or incomplete migration evidence, unsafe archive members and CLI failures
without private input disclosure. These synthetic results do not assert recovery
of the real production bundle.
