#!/usr/bin/env python3
"""Prepare one approved backend image and migration evidence; never deploy or run it."""
import argparse
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
    validate_inputs(revision, manifest_digest, config_digest, evidence_ref, authorized)
    expected = qualified_migrations()  # Checks the historical evidence hash before network I/O.
    require(not output.is_symlink(), 'QUALIFICATION_OUTPUT_SYMLINK_FORBIDDEN')
    output = output.resolve()
    require(not output.is_relative_to(ROOT), 'QUALIFICATION_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY')
    require(not output.exists(), 'QUALIFICATION_OUTPUT_ALREADY_EXISTS')
    metadata = ghcr_manifest(REPOSITORY, manifest_digest)
    require(metadata['manifestDigest'] == manifest_digest and metadata['indexDigest'] == manifest_digest,
            'APPROVED_DIGEST_MUST_BE_PLATFORM_MANIFEST')
    require(metadata['configDigest'] == config_digest, 'APPROVED_CONFIG_DIGEST_MISMATCH')
    output.mkdir(parents=True, mode=0o700)
    pinned = REPOSITORY + '@' + manifest_digest
    local_ref = REPOSITORY + ':deploy-' + manifest_digest[7:]
    run(['docker', 'pull', '--platform', 'linux/amd64', pinned])
    image = json.loads(run(['docker', 'image', 'inspect', pinned]))[0]
    verify_runner_platform(image)
    run(['docker', 'image', 'tag', pinned, local_ref])
    archive = output / 'BACKEND_IMAGE_REF.tar'
    with tempfile.TemporaryDirectory(prefix='backend-save-', dir=output) as temporary:
        raw = Path(temporary) / 'backend.raw'
        run(['docker', 'image', 'save', '--output', str(raw), local_ref])
        normalized_archive(raw, archive)
    proof = archive_image(archive, local_ref, config_digest, revision, migrations=True, details=True)
    require(proof['imageConfig'].get('Labels', {}).get('org.opencontainers.image.source') == SOURCE,
            'ARCHIVE_SOURCE_REPOSITORY_MISMATCH')
    require(proof['migrations'] == expected, 'IMAGE_MIGRATIONS_NOT_QUALIFIED_V8')
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
    report_path = output / 'evidence.json'
    with report_path.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    with (output / 'SHA256SUMS').open('x') as stream:
        for path in (archive, report_path):
            stream.write(file_sha(path) + '  ' + path.name + '\n')
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
    except (DeploymentError, OSError, ValueError, KeyError, TypeError, IndexError, EOFError,
            tarfile.TarError, zipfile.BadZipFile):
        # Do not print raw registry/Docker errors, config environments or credential-bearing paths.
        print('BACKEND_PREPARATION_FAILED; no qualification artifact should be used.', file=sys.stderr)
        return 2
    print('PASS: image integrity and V1-V8 migration equivalence. '
          'JAR binary identity and production build-profile qualification remain unverified.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
