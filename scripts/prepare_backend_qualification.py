#!/usr/bin/env python3
"""Prepare one approved backend image and migration evidence; never deploy or run it."""
import argparse
import errno
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import zipfile

from deploy_local_images import DeploymentError, REPOSITORIES, require
from prepare_production_release import ghcr_manifest, run, verify_runner_platform
from release_artifacts import SHA, DIGEST, archive_image, normalized_archive, file_sha
from release_safety import EVIDENCE_SHA256, qualified_migrations

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = REPOSITORIES['BACKEND_IMAGE_REF']
SOURCE = 'https://github.com/ThierryTe/ai-policy-invetigator'

# Exact, reviewed codes only. Never echo an arbitrary DeploymentError, even if it
# resembles a code: dependency messages can contain paths or untrusted data.
SAFE_CODES = frozenset('''
EXPLICIT_PREPARATION_AUTHORIZATION_REQUIRED FULL_SOURCE_SHA_REQUIRED
APPROVED_MANIFEST_DIGEST_REQUIRED APPROVED_CONFIG_DIGEST_REQUIRED
NONSECRET_CHANGE_RECORD_REFERENCE_REQUIRED MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED
TOOLING_REVISION_REQUIRED GITHUB_RUN_ID_INVALID
V8_QUALIFICATION_EVIDENCE_CHANGED V8_QUALIFICATION_INVENTORY_INVALID
QUALIFICATION_OUTPUT_SYMLINK_FORBIDDEN QUALIFICATION_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY
QUALIFICATION_OUTPUT_ALREADY_EXISTS APPROVED_DIGEST_MUST_BE_PLATFORM_MANIFEST
APPROVED_CONFIG_DIGEST_MISMATCH REGISTRY_JOB_TOKEN_REQUIRED
REGISTRY_RESPONSE_TOO_LARGE REGISTRY_AUTH_OR_REFERENCE_FAILED
REGISTRY_NETWORK_RETRIES_EXHAUSTED REGISTRY_MANIFEST_DIGEST_MISMATCH
REGISTRY_HEADER_DIGEST_MISMATCH REGISTRY_AMD64_VARIANT_NOT_UNIQUE
REGISTRY_CONFIG_DIGEST_INVALID RUNNER_IMAGE_PLATFORM_MISMATCH
ARCHIVE_DUPLICATE_PATH ARCHIVE_SPECIAL_FILE ARCHIVE_PATH_INVALID
ARCHIVE_CONTENT_MISSING ARCHIVE_FILE_INVALID ARCHIVE_IMAGE_ALLOWLIST_FAILED
ARCHIVE_UNEXPECTED_CONTENT ARCHIVE_CONFIG_DIGEST_MISMATCH ARCHIVE_CONFIG_INVALID
ARCHIVE_PLATFORM_MISMATCH ARCHIVE_SOURCE_REVISION_MISMATCH
ARCHIVE_LAYER_COUNT_MISMATCH ARCHIVE_ZSTD_LAYER_REQUIRES_REVIEW
ARCHIVE_LAYER_TOO_LARGE ARCHIVE_LAYER_DIGEST_MISMATCH BACKEND_JAR_INVALID
BACKEND_JAR_MISSING UNSUPPORTED_MIGRATION_NAME MIGRATION_PLACEHOLDERS_REQUIRE_REVIEW
MIGRATION_INVENTORY_INVALID ARCHIVE_SOURCE_REPOSITORY_MISMATCH
IMAGE_MIGRATIONS_NOT_QUALIFIED_V8
'''.split())
DOCKER_CATEGORIES = frozenset('''
PLATFORM_OPTION_UNSUPPORTED API_VERSION_UNSUPPORTED PLATFORM_UNAVAILABLE
ACCESS_DENIED IMAGE_NOT_FOUND DISK_FULL DAEMON_UNAVAILABLE TLS_ERROR
REGISTRY_RATE_LIMIT NETWORK_ERROR UNCLASSIFIED
'''.split())


def error_category(error):
    if isinstance(error, DeploymentError):
        message = str(error)
        if message in SAFE_CODES:
            return message
        if message.startswith('RUNNER_DOCKER_OPERATION_FAILED: '):
            category = message.partition('; ')[2].partition(':')[0]
            return category if category in DOCKER_CATEGORIES else 'DOCKER_OPERATION_FAILED'
        if message.startswith('RUNNER_DOCKER_UNAVAILABLE_OR_TIMEOUT: '):
            return 'DOCKER_START_FAILED' if ' START_FAILED:' in message else 'DOCKER_TIMEOUT'
        return 'UNCLASSIFIED_DEPLOYMENT_ERROR'
    if isinstance(error, OSError):
        return {errno.ENOSPC: 'DISK_FULL', errno.EDQUOT: 'DISK_FULL',
                errno.EACCES: 'PERMISSION_DENIED', errno.EPERM: 'PERMISSION_DENIED',
                errno.ENOENT: 'FILE_NOT_FOUND', errno.EEXIST: 'FILE_ALREADY_EXISTS'}.get(error.errno, 'IO_ERROR')
    if isinstance(error, (tarfile.TarError, zipfile.BadZipFile, EOFError)):
        return 'INVALID_ARCHIVE'
    if isinstance(error, (ValueError, KeyError, TypeError, IndexError, AttributeError)):
        return 'INVALID_METADATA'
    return 'INTERNAL_ERROR'


class PreparationFailure(DeploymentError):
    def __init__(self, stage, error):
        self.stage = stage
        self.category = error_category(error)
        super().__init__(self.category)


def validate_inputs(revision, manifest_digest, config_digest, evidence_ref, authorized):
    require(authorized is True, 'EXPLICIT_PREPARATION_AUTHORIZATION_REQUIRED')
    require(re.fullmatch(SHA, revision or ''), 'FULL_SOURCE_SHA_REQUIRED')
    require(re.fullmatch(DIGEST, manifest_digest or ''), 'APPROVED_MANIFEST_DIGEST_REQUIRED')
    require(re.fullmatch(DIGEST, config_digest or ''), 'APPROVED_CONFIG_DIGEST_REQUIRED')
    require(re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{2,79}', evidence_ref or ''),
            'NONSECRET_CHANGE_RECORD_REFERENCE_REQUIRED')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
                and os.environ.get('GITHUB_REF') == 'refs/heads/main'
                and os.environ.get('GITHUB_REPOSITORY') == 'ThierryTe/ai-policy-invetigator',
                'MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED')
        require(re.fullmatch(SHA, os.environ.get('GITHUB_SHA', '')),
                'TOOLING_REVISION_REQUIRED')
        require(all(os.environ.get(k, '').isdecimal() for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')),
                'GITHUB_RUN_ID_INVALID')


def prepare(output, revision, manifest_digest, config_digest, evidence_ref, authorized=False):
    stage = 'INPUT_VALIDATION'
    try:
        validate_inputs(revision, manifest_digest, config_digest, evidence_ref, authorized)
        stage = 'QUALIFIED_MIGRATIONS'
        expected = qualified_migrations()  # Checks historical evidence before network I/O.
        stage = 'OUTPUT_VALIDATION'
        require(not output.is_symlink(), 'QUALIFICATION_OUTPUT_SYMLINK_FORBIDDEN')
        output = output.resolve()
        require(not output.is_relative_to(ROOT), 'QUALIFICATION_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY')
        require(not output.exists(), 'QUALIFICATION_OUTPUT_ALREADY_EXISTS')
        stage = 'REGISTRY_MANIFEST'
        metadata = ghcr_manifest(REPOSITORY, manifest_digest)
        stage = 'APPROVED_DIGESTS'
        require(metadata['manifestDigest'] == manifest_digest and metadata['indexDigest'] == manifest_digest,
                'APPROVED_DIGEST_MUST_BE_PLATFORM_MANIFEST')
        require(metadata['configDigest'] == config_digest, 'APPROVED_CONFIG_DIGEST_MISMATCH')
        stage = 'OUTPUT_STAGING'
        output.parent.mkdir(parents=True, exist_ok=True)
        # A same-filesystem private directory is removed on failure. Only rename
        # it to the upload path once all verification and checksum writes pass.
        with tempfile.TemporaryDirectory(prefix='backend-qualification-', dir=output.parent) as temporary:
            return _prepare_archive(Path(temporary), output, revision, manifest_digest,
                                    config_digest, evidence_ref, expected)
    except PreparationFailure:
        raise
    except Exception as error:
        raise PreparationFailure(stage, error) from None


def _prepare_archive(work, output, revision, manifest_digest, config_digest, evidence_ref, expected):
    pinned = REPOSITORY + '@' + manifest_digest
    local_ref = REPOSITORY + ':deploy-' + manifest_digest[7:]
    stage = 'DOCKER_PULL'
    try:
        run(['docker', 'pull', '--platform', 'linux/amd64', pinned])
        stage = 'DOCKER_INSPECT'
        image = json.loads(run(['docker', 'image', 'inspect', pinned]))[0]
        stage = 'RUNNER_PLATFORM'
        verify_runner_platform(image)
        stage = 'DOCKER_TAG'
        run(['docker', 'image', 'tag', pinned, local_ref])
        archive = work / 'BACKEND_IMAGE_REF.tar'
        raw = work / 'backend.raw'
        stage = 'DOCKER_SAVE'
        run(['docker', 'image', 'save', '--output', str(raw), local_ref])
        stage = 'ARCHIVE_NORMALIZATION'
        normalized_archive(raw, archive)
        raw.unlink()
        stage = 'ARCHIVE_VERIFICATION'
        proof = archive_image(archive, local_ref, config_digest, revision, migrations=True, details=True)
        stage = 'SOURCE_REPOSITORY'
        require(proof['imageConfig'].get('Labels', {}).get('org.opencontainers.image.source') == SOURCE,
                'ARCHIVE_SOURCE_REPOSITORY_MISMATCH')
        stage = 'MIGRATION_EQUIVALENCE'
        require(proof['migrations'] == expected, 'IMAGE_MIGRATIONS_NOT_QUALIFIED_V8')
        stage = 'EVIDENCE_WRITE'
        report = _write_evidence(work, archive, pinned, local_ref, revision, manifest_digest,
                                 config_digest, evidence_ref, proof)
        stage = 'OUTPUT_COMMIT'
        require(not output.exists() and not output.is_symlink(), 'QUALIFICATION_OUTPUT_ALREADY_EXISTS')
        work.rename(output)
        return report
    except PreparationFailure:
        raise
    except Exception as error:
        raise PreparationFailure(stage, error) from None


def _write_evidence(work, archive, pinned, local_ref, revision, manifest_digest, config_digest, evidence_ref, proof):
    report = {
        'format': 1,
        'result': 'PASS',
        'scope': 'Published image integrity and V1-V8 migration equivalence only; no production authorization.',
        'evidenceRef': evidence_ref,
        'sourceRevision': revision,
        'sourceRepository': SOURCE,
        'sourceRef': pinned,
        'platform': 'linux/amd64',
        'manifestDigest': manifest_digest,
        'configDigest': config_digest,
        'localRef': local_ref,
        'archive': archive.name,
        'archiveSha256': file_sha(archive),
        'qualifiedEvidenceSha256': EVIDENCE_SHA256,
        'migrations': proof['migrations'],
        'layerDiffIds': proof['diffIds'],
        'migrationEquivalenceVerified': True,
        'binaryIdentityVerified': False,
        'productionBuildProfileQualified': False,
        'limitations': [
            'Embedded SQL identity does not establish whole-JAR binary identity with the historical qualified JAR.',
            'The neural-embeddings production build profile and image behavior require separate qualification.',
            'No image execution, target preflight, backup, restore, production acceptance or deployment was performed.',
        ],
    }
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        report['github'] = {
            'repository': 'ThierryTe/ai-policy-invetigator',
            'toolingRevision': os.environ['GITHUB_SHA'],
            'runId': os.environ['GITHUB_RUN_ID'],
            'runAttempt': os.environ['GITHUB_RUN_ATTEMPT'],
        }
    report_path = work / 'evidence.json'
    with report_path.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    try:
        with (work / 'SHA256SUMS').open('x') as stream:
            for path in (archive, report_path):
                stream.write(file_sha(path) + '  ' + path.name + '\n')
    except Exception as error:
        raise PreparationFailure('CHECKSUMS_WRITE', error) from None
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--manifest-digest', required=True)
    parser.add_argument('--config-digest', required=True)
    parser.add_argument('--evidence-ref', required=True)
    parser.add_argument('--confirm-authorized', action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        prepare(args.output, args.revision, args.manifest_digest, args.config_digest,
                args.evidence_ref, args.confirm_authorized)
    except Exception as error:
        # Only constants reach either stream; stdout is the workflow Step Summary.
        stage = error.stage if isinstance(error, PreparationFailure) else 'PREPARATION'
        category = error.category if isinstance(error, PreparationFailure) else error_category(error)
        message = ('BACKEND_PREPARATION_FAILED stage=' + stage + ' category=' + category
                   + '; no qualification artifact should be used.')
        print(message, file=sys.stderr)
        print(message)
        return 2
    print('PASS: image integrity and V1-V8 migration equivalence. '
          'JAR binary identity and production build-profile qualification remain unverified.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
