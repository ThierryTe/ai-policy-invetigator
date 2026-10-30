#!/usr/bin/env python3
"""Offline V8 JAR audit. Reads local files only; no database, Git or deployment."""
import argparse
import json
from pathlib import Path
import re
import sys

from release_artifacts import file_sha, inventory, sha

ROOT = Path(__file__).resolve().parent.parent


def audit(jar, baseline):
    expected = {}
    for line in baseline.read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  src/main/resources/db/migration/(V([1-7])__[a-z0-9_]+\.sql)', line)
        if not match or match[2] in expected:
            raise ValueError('V7_BASELINE_INVALID')
        expected[match[2]] = match[1]
    if len(expected) != 7 or {name.split('__')[0] for name in expected} != {f'V{n}' for n in range(1, 8)}:
        raise ValueError('V7_BASELINE_INCOMPLETE')
    rows = inventory(jar.read_bytes())
    if [row['version'] for row in rows] != [str(n) for n in range(1, 9)]:
        raise ValueError('EXACTLY_EIGHT_MIGRATIONS_REQUIRED')
    sources = ROOT / 'src/main/resources/db/migration'
    if {p.name for p in sources.glob('V*.sql')} != {row['script'] for row in rows}:
        raise ValueError('JAR_SOURCE_INVENTORY_MISMATCH')
    for row in rows:
        if row['sha256'] != sha((sources / row['script']).read_bytes()):
            raise ValueError('JAR_SOURCE_BYTES_MISMATCH')
        if row['version'] != '8' and expected.get(row['script']) != row['sha256']:
            raise ValueError('V1_V7_CHANGED')
    return {'artifact_verdict': 'PASS', 'jar': jar.name, 'jar_sha256': file_sha(jar),
            'baseline_sha256': file_sha(baseline), 'migrations': rows,
            'v1_v7_unchanged': True, 'jar_matches_sources': True,
            'scope': 'local artifact only; not VPS or production qualification'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar', type=Path, default=ROOT / 'target/ai-policy-investigator-0.1.0-SNAPSHOT.jar')
    parser.add_argument('--baseline', type=Path, default=ROOT / 'docs/verification/v7-migrations.sha256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = audit(args.jar, args.baseline)
        result = json.dumps(report, indent=2) + '\n'
        if args.output:
            args.output.write_text(result)
        print(result, end='')
        return 0
    except Exception:
        # Never echo paths, SQL, environment variables or opaque exception content.
        print('V8_ARTIFACT_QUALIFICATION_FAILED', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
