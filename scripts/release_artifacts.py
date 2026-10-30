"""Release data validation; no Docker, network, extraction to disk or credentials."""
import hashlib
import gzip
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile
import zlib

from deploy_local_images import DeploymentError, REPOSITORIES, require

SHA = r'[0-9a-f]{40}'
DIGEST = r'sha256:[0-9a-f]{64}'
RELEASE_ID = r'r[0-9]+-[0-9]+'
KEYS = (*REPOSITORIES, 'POSTGRES_IMAGE_REF')
RUNTIME_FILES = ('scripts/production_release.py', 'scripts/deploy_local_images.py',
                 'scripts/verify_production_compose.py', 'scripts/release_artifacts.py',
                 'scripts/release_safety.py', 'scripts/qualification_v8_preflight.sql',
                 'docs/verification/v8-artifact.json')
CONFIG_FILES = ('compose.yaml', 'compose.production.yaml', 'deploy/backend/compose.ghcr.yaml',
                'deploy/frontend/compose.production.yaml', 'deploy/frontend/compose.ghcr.yaml',
                'deploy/postgres/init.sh', 'frontend/compose.yaml', 'deploy/automation/compose.yaml')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def flyway_checksum(data):
    # Flyway ChecksumCalculator: UTF-8, initial BOM removed, readLine terminators excluded.
    text = data.decode('utf-8-sig')
    checksum = zlib.crc32(re.sub(r'\r\n|\r|\n', '', text).encode())
    return checksum if checksum < 2**31 else checksum - 2**32


def inventory(jar):
    rows = []
    with zipfile.ZipFile(io.BytesIO(jar)) as archive:
        for name in archive.namelist():
            if not name.startswith('BOOT-INF/classes/db/migration/') or name.endswith('/'):
                continue
            filename = name.rsplit('/', 1)[1]
            match = re.fullmatch(r'V([0-9]+)__[a-z0-9_]+\.sql', filename)
            require(match, 'UNSUPPORTED_MIGRATION_NAME')
            data = archive.read(name)
            require(b'${' not in data, 'MIGRATION_PLACEHOLDERS_REQUIRE_REVIEW')
            rows.append({'version': match[1], 'script': filename, 'checksum': flyway_checksum(data), 'sha256': sha(data)})
    rows.sort(key=lambda row: int(row['version']))
    require(rows and len({r['version'] for r in rows}) == len(rows), 'MIGRATION_INVENTORY_INVALID')
    return rows


def archive_image(path, reference, config_digest, revision=None, migrations=False, details=False):
    """Verify selected config + uncompressed layer DiffIDs in docker-save output.

    Never extract an archive to the filesystem. Reject additional tagged images. OCI
    side metadata is harmless: only the validated legacy manifest is loaded below.
    """
    with tarfile.open(path, 'r:') as archive:
        members = archive.getmembers()
        require(len({m.name for m in members}) == len(members), 'ARCHIVE_DUPLICATE_PATH')
        require(all(m.isfile() or m.isdir() for m in members), 'ARCHIVE_SPECIAL_FILE')
        require(all(not PurePosixPath(m.name).is_absolute() and '..' not in PurePosixPath(m.name).parts for m in members), 'ARCHIVE_PATH_INVALID')
        def read(name):
            try:
                member = archive.getmember(name)
            except KeyError:
                raise DeploymentError('ARCHIVE_CONTENT_MISSING') from None
            require(member.isfile(), 'ARCHIVE_FILE_INVALID')
            return archive.extractfile(member).read()
        manifest = json.loads(read('manifest.json'))
        require(isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict)
                and manifest[0]['RepoTags'] == [reference], 'ARCHIVE_IMAGE_ALLOWLIST_FAILED')
        row = manifest[0]
        expected_members = {'manifest.json', row['Config'], *row['Layers']}
        require(expected_members <= {m.name for m in members}, 'ARCHIVE_CONTENT_MISSING')
        require({m.name for m in members} == expected_members, 'ARCHIVE_UNEXPECTED_CONTENT')
        config_bytes = read(row['Config'])
        require('sha256:' + sha(config_bytes) == config_digest, 'ARCHIVE_CONFIG_DIGEST_MISMATCH')
        config = json.loads(config_bytes)
        require(isinstance(config, dict), 'ARCHIVE_CONFIG_INVALID')
        require(config.get('os') == 'linux' and config.get('architecture') == 'amd64', 'ARCHIVE_PLATFORM_MISMATCH')
        if revision:
            require(((config.get('config') or {}).get('Labels') or {}).get('org.opencontainers.image.revision') == revision,
                    'ARCHIVE_SOURCE_REVISION_MISMATCH')
        diffs = config['rootfs']['diff_ids']
        require(len(row['Layers']) == len(diffs), 'ARCHIVE_LAYER_COUNT_MISMATCH')
        jar = None
        for name, expected in zip(row['Layers'], diffs):
            with archive.extractfile(archive.getmember(name)) as stream:
                magic = stream.read(4)
                stream.seek(0)
                require(magic != b'\x28\xb5\x2f\xfd', 'ARCHIVE_ZSTD_LAYER_REQUIRES_REVIEW')
                decoded = gzip.GzipFile(fileobj=stream) if magic[:2] == b'\x1f\x8b' else stream
                checksum, size = hashlib.sha256(), 0
                while chunk := decoded.read(1024**2):
                    size += len(chunk)
                    require(size <= 2 * 1024**3, 'ARCHIVE_LAYER_TOO_LARGE')
                    checksum.update(chunk)
                require('sha256:' + checksum.hexdigest() == expected, 'ARCHIVE_LAYER_DIGEST_MISMATCH')
            if migrations:
                with tarfile.open(fileobj=archive.extractfile(archive.getmember(name)), mode='r|*') as layer:
                    for member in layer:
                        normalized = member.name.removeprefix('./').lstrip('/')
                        if normalized == 'app/.wh.investigator.jar':
                            jar = None
                        if normalized in ['app/.wh..wh..opq', '.wh.app']:
                            jar = None
                        if normalized == 'app/investigator.jar':
                            require(member.isfile() and member.size < 512 * 1024**2, 'BACKEND_JAR_INVALID')
                            jar = layer.extractfile(member).read()
        require(not migrations or jar is not None, 'BACKEND_JAR_MISSING')
        rows = inventory(jar) if migrations else []
        return {'migrations': rows, 'diffIds': diffs, 'imageConfig': config.get('config') or {}} if details else rows


def normalized_archive(source, destination):
    """Drop OCI side indexes/tags; load exactly one validated docker-save manifest."""
    with tarfile.open(source, 'r:') as src, tarfile.open(destination, 'x:') as dst:
        manifest = json.loads(src.extractfile('manifest.json').read())
        require(len(manifest) == 1, 'ARCHIVE_IMAGE_ALLOWLIST_FAILED')
        names = ['manifest.json', manifest[0]['Config'], *manifest[0]['Layers']]
        require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names), 'ARCHIVE_PATH_INVALID')
        for name in dict.fromkeys(names):
            try:
                member = src.getmember(name)
            except KeyError:
                raise DeploymentError('ARCHIVE_CONTENT_MISSING') from None
            require(member.isfile(), 'ARCHIVE_FILE_INVALID')
            dst.addfile(member, src.extractfile(member))


def validate_manifest(data):
    require(isinstance(data, dict), 'RELEASE_MANIFEST_INVALID')
    require(data.get('format') == 1 and re.fullmatch(RELEASE_ID, data.get('id', '')), 'RELEASE_MANIFEST_INVALID')
    require(re.fullmatch(SHA, data.get('backendSha', '')) and re.fullmatch(SHA, data.get('frontendSha', ''))
            and re.fullmatch(SHA, data.get('configurationSha', '')), 'RELEASE_SOURCE_INVALID')
    require(isinstance(data['images'], dict) and set(data['images']) == set(KEYS), 'RELEASE_IMAGE_KEYS_INVALID')
    for key, image in data['images'].items():
        require(isinstance(image, dict), 'RELEASE_IMAGE_INVALID')
        repo = REPOSITORIES.get(key, 'ai-policy-investigator-postgres')
        require(re.fullmatch(DIGEST, image['configDigest']) and re.fullmatch(DIGEST, image['manifestDigest']), 'RELEASE_DIGEST_INVALID')
        require(image['localRef'] == repo + ':deploy-' + image['manifestDigest'][7:], 'RELEASE_LOCAL_REFERENCE_INVALID')
        require(re.fullmatch(r'[0-9a-f]{64}', image['archiveSha256']), 'RELEASE_ARCHIVE_DIGEST_INVALID')
        require(image['archive'] == key + '.tar', 'RELEASE_ARCHIVE_NAME_INVALID')
        if key != 'POSTGRES_IMAGE_REF':
            expected_sha = data['frontendSha'] if key == 'FRONTEND_IMAGE_REF' else data['backendSha']
            require(image['sourceRef'] == repo + ':sha-' + expected_sha, 'RELEASE_SOURCE_PAIR_MISMATCH')
        else:
            require(image['sourceRef'] == 'pgvector/pgvector:0.8.0-pg16', 'POSTGRES_UPGRADE_FORBIDDEN')
    require(isinstance(data['configuration'], dict) and set(data['configuration']) == set(CONFIG_FILES), 'RELEASE_CONFIG_ALLOWLIST_INVALID')
    require(all(re.fullmatch(r'[0-9a-f]{64}', v) for v in data['configuration'].values()), 'RELEASE_CONFIG_DIGEST_INVALID')
    if 'expectedPrevious' in data:
        require(data['expectedPrevious'] is None or re.fullmatch(RELEASE_ID, data['expectedPrevious']), 'RELEASE_BASE_INVALID')
    if 'runtime' in data:
        require(isinstance(data['runtime'], dict) and set(data['runtime']) == set(RUNTIME_FILES), 'RELEASE_RUNTIME_ALLOWLIST_INVALID')
        require(all(re.fullmatch(r'[0-9a-f]{64}', v) for v in data['runtime'].values()), 'RELEASE_RUNTIME_DIGEST_INVALID')
    return data


def migration_gate(applied, target, previous=None, rollback=False, allow_migrations=False):
    """Only known versioned SQL history; application rollback never rewinds the DB."""
    require(all(row.get('success') is True and row.get('type') == 'SQL' for row in applied), 'DATABASE_HISTORY_UNSUPPORTED_OR_FAILED')
    target_rows = {r['version']: r for r in target}
    require(len(target_rows) == len(target), 'MIGRATION_INVENTORY_INVALID')
    for row in applied:
        require(row['version'] in target_rows and all(row[k] == target_rows[row['version']][k] for k in ['script', 'checksum']),
                'DATABASE_MIGRATION_INCOMPATIBLE')
    require([r['version'] for r in applied] == [r['version'] for r in target[:len(applied)]], 'DATABASE_MIGRATION_ORDER_INVALID')
    if previous:
        require(target[:len(previous)] == previous if not rollback else True, 'PREVIOUS_MIGRATION_CHANGED')
    pending = len(target) != len(applied)
    require(not rollback or not pending, 'ROLLBACK_DATABASE_NOT_EXACT')
    require(not pending or allow_migrations, 'PENDING_MIGRATIONS_REQUIRE_APPROVAL')
