#!/usr/bin/env python3
"""Verify a retained configuration/runtime archive offline; never extract or execute it.

Both SHA-256 anchors must come from independently trusted records, not checksum
files supplied by the candidate archive. This verifies bytes against the supplied
migration evidence; it does not authenticate the provenance of those anchors or
verify images, current production state, or approval to activate workers.
"""
import argparse
import io
import json
from pathlib import Path
import re
import sys
import tarfile

from deploy_local_images import DeploymentError, require
from release_artifacts import CONFIG_FILES, RUNTIME_FILES, RELEASE_ID, SHA, sha
from release_safety import qualified_migrations, validate_attestation

MAX_BUNDLE = 64 * 1024**2
MAX_RECORD = 4 * 1024**2
MAX_FILE = 16 * 1024**2


def pinned_bytes(path, expected, maximum, code):
    require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected),
            'INDEPENDENT_SHA256_ANCHOR_REQUIRED')
    require(path.is_file() and not path.is_symlink(), code + '_FILE_INVALID')
    # Hash and consume the same bounded bytes, so a later path replacement cannot
    # change the archive/record between its digest check and its parsing.
    with path.open('rb') as source:
        content = source.read(maximum + 1)
    require(len(content) <= maximum, code + '_SIZE_INVALID')
    require(sha(content) == expected, code + '_DIGEST_MISMATCH')
    return content


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'MIGRATION_RECORD_DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def record_digests(record, identity):
    require(isinstance(record, dict) and record.get('id') == identity
            and record.get('result') == 'VALIDATED' and record.get('rollback') is False,
            'SUCCESSFUL_MIGRATION_RECORD_REQUIRED')
    require(validate_attestation(record.get('releaseSafety')) == 'migrate-v8',
            'DISABLED_WORKER_MIGRATION_RECORD_REQUIRED')
    require(record.get('targetPreflightVerified') is True
            and record.get('qualifiedMigrationInventoryVerified') is True,
            'VERIFIED_MIGRATION_RECORD_REQUIRED')
    for field in ('backendSha', 'frontendSha', 'configurationSha'):
        require(isinstance(record.get(field), str) and re.fullmatch(SHA, record[field]),
                'MIGRATION_SOURCE_IDENTITY_INVALID')
    require(record.get('migrations') == qualified_migrations(), 'IMAGE_MIGRATIONS_NOT_QUALIFIED_V8')
    expected = {}
    for field, names, prefix in [('configuration', CONFIG_FILES, 'configuration/'),
                                 ('runtime', RUNTIME_FILES, '')]:
        table = record.get(field)
        require(isinstance(table, dict) and set(table) == set(names), 'MIGRATION_BUNDLE_ALLOWLIST_INVALID')
        require(all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                    for value in table.values()), 'MIGRATION_BUNDLE_DIGEST_INVALID')
        expected.update({prefix + name: table[name] for name in names})
    return expected


def verify(bundle, bundle_sha256, migration_record, migration_record_sha256, identity):
    require(isinstance(identity, str) and re.fullmatch(RELEASE_ID, identity), 'RELEASE_ID_INVALID')
    record_bytes = pinned_bytes(migration_record, migration_record_sha256, MAX_RECORD, 'MIGRATION_RECORD')
    record = json.loads(record_bytes, object_pairs_hook=unique_object)
    expected = record_digests(record, identity)
    content = pinned_bytes(bundle, bundle_sha256, MAX_BUNDLE, 'RETAINED_BUNDLE')
    directories = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != '.'}
    seen, verified, total = set(), set(), 0
    with tarfile.open(fileobj=io.BytesIO(content), mode='r|*') as archive:
        for member in archive:
            require(member.name not in seen, 'RETAINED_BUNDLE_DUPLICATE_PATH')
            seen.add(member.name)
            require(len(seen) <= len(expected) + len(directories), 'RETAINED_BUNDLE_TOO_MANY_MEMBERS')
            if member.isdir():
                require(member.name in directories and member.size == 0, 'RETAINED_BUNDLE_DIRECTORY_INVALID')
                continue
            require(member.isfile() and member.name in expected, 'RETAINED_BUNDLE_FILE_NOT_ALLOWLISTED')
            require(0 <= member.size <= MAX_FILE, 'RETAINED_BUNDLE_MEMBER_SIZE_INVALID')
            total += member.size
            require(total <= MAX_BUNDLE, 'RETAINED_BUNDLE_EXPANDED_SIZE_INVALID')
            payload = archive.extractfile(member).read(MAX_FILE + 1)
            require(len(payload) == member.size, 'RETAINED_BUNDLE_MEMBER_SIZE_INVALID')
            require(sha(payload) == expected[member.name], 'RETAINED_BUNDLE_CONTENT_DIGEST_MISMATCH')
            verified.add(member.name)
    require(verified == set(expected), 'RETAINED_BUNDLE_INCOMPLETE')
    return {'result': 'CONFIGURATION_RUNTIME_BYTES_VERIFIED', 'release': identity,
            'configurationSha': record['configurationSha'], 'bundleSha256': bundle_sha256,
            'migrationRecordSha256': migration_record_sha256,
            'configurationFiles': len(CONFIG_FILES), 'runtimeFiles': len(RUNTIME_FILES),
            'provenanceAuthenticated': False, 'imagesVerified': False, 'productionStateVerified': False,
            'activationAuthorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--bundle-sha256', required=True)
    parser.add_argument('--migration-record', required=True, type=Path)
    parser.add_argument('--migration-record-sha256', required=True)
    parser.add_argument('--release-id', required=True)
    args = parser.parse_args()
    try:
        result = verify(args.bundle, args.bundle_sha256, args.migration_record,
                        args.migration_record_sha256, args.release_id)
        print(json.dumps(result, indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'RETAINED_BUNDLE_VERIFICATION_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
