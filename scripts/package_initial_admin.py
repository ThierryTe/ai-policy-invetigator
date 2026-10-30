#!/usr/bin/env python3
"""Package only public initial-admin tools. Never invoke Git, Docker, SSH or read .env files."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

from provision_initial_admin import BootstrapError, MIGRATION_INVENTORY, ROOT, expected_migrations

FILES = ('compose.yaml', 'compose.production.yaml', 'scripts/provision_initial_admin.py',
         'deploy/postgres/provision-initial-admin.sql', 'docs/FIRST_LOGIN.md')


def package(output, root=ROOT):
    checksum = Path(str(output) + '.sha256')
    if output.exists() or output.is_symlink() or checksum.exists() or checksum.is_symlink():
        raise BootstrapError('INITIAL_ADMIN_PACKAGE_OUTPUT_EXISTS')
    entries = {}
    for name in FILES:
        source = root / name
        if not source.is_file() or source.is_symlink():
            raise BootstrapError('INITIAL_ADMIN_PACKAGE_SOURCE_INVALID')
        entries[name] = source.read_bytes()
    entries[MIGRATION_INVENTORY] = (json.dumps(expected_migrations(root), indent=2) + '\n').encode()
    entries['FILES.sha256'] = ''.join(
        hashlib.sha256(content).hexdigest() + '  ' + name + '\n'
        for name, content in sorted(entries.items())).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, content in sorted(entries.items()):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            member.mtime = member.uid = member.gid = 0
            archive.addfile(member, io.BytesIO(content))
    with checksum.open('x') as stream:
        stream.write(hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name + '\n')
    return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        count = package(args.output)
    except (BootstrapError, OSError, ValueError) as error:
        print(str(error) if isinstance(error, BootstrapError) else 'INITIAL_ADMIN_PACKAGE_FAILED', file=sys.stderr)
        return 2
    print(f'Initial-admin package ready: {count} public files and archive SHA-256. No credentials included.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
