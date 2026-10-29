#!/usr/bin/env python3
"""Build a non-secret, allowlisted configuration bundle; never runs Git/Docker/SSH."""
import argparse
import hashlib
from pathlib import Path
import sys
import tarfile

from deploy_local_images import ROOT, DeploymentError, release_images, require

FILES = (
    'compose.yaml', 'compose.production.yaml',
    'deploy/backend/compose.ghcr.yaml', 'deploy/frontend/compose.production.yaml',
    'deploy/frontend/compose.ghcr.yaml', 'deploy/postgres/init.sh',
    'deploy/postgres/provision-initial-admin.sql',
    'scripts/deploy_local_images.py', 'scripts/verify_production_compose.py',
    'scripts/provision_initial_admin.py', 'docs/DEPLOYMENT.md', '.env.example',
)


def package(frontend, release_file, output, root=ROOT):
    release_images(release_file)
    source = frontend / 'compose.yaml'
    require(source.is_file() and not source.is_symlink(), 'FRONTEND_COMPOSE_MISSING')
    require(source.read_bytes() == (root / '.ci/frontend/compose.yaml').read_bytes(), 'FRONTEND_CONTRACT_REQUIRES_REVIEW')
    require(not output.is_symlink(), 'BUNDLE_OUTPUT_SYMLINK_FORBIDDEN')
    output = output.resolve()
    for directory in [root.resolve(), frontend.resolve()]:
        require(not output.is_relative_to(directory), 'BUNDLE_OUTPUT_MUST_BE_OUTSIDE_REPOSITORIES')
    entries = [(root / f, f) for f in FILES] + [(source, 'frontend/compose.yaml'), (release_file, 'deploy/release.images.json')]
    require(all(p.is_file() and not p.is_symlink() for p, _ in entries), 'BUNDLE_SOURCE_FILE_MISSING_OR_SYMLINK')
    require(not output.exists() and not Path(str(output) + '.sha256').exists(), 'BUNDLE_OUTPUT_ALREADY_EXISTS')
    output.parent.mkdir(parents=True, exist_ok=True)

    def public_metadata(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        info.mode = 0o755 if info.mode & 0o111 else 0o644
        return info

    with tarfile.open(output, 'x:gz') as archive:
        for path, destination in entries:
            archive.add(path, arcname=destination, recursive=False, filter=public_metadata)
    with output.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    with Path(str(output) + '.sha256').open('x') as checksum:
        checksum.write(digest + '  ' + output.name + '\n')
    return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend-directory', required=True, type=Path)
    parser.add_argument('--release-file', type=Path, default=ROOT / 'deploy/release.images.json')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        count = package(args.frontend_directory.resolve(), args.release_file.resolve(), args.output)
    except (DeploymentError, OSError, ValueError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'BUNDLE_CREATION_FAILED', file=sys.stderr)
        return 2
    print(f'Configuration bundle ready: {count} allowlisted public files; no secrets, Git history or application source.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
