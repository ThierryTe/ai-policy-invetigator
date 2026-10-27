#!/usr/bin/env python3
"""Verify imported source and destination hashes without modifying either source repo."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
source = root.parent / 'spring-ai-rag'
for entry in json.loads((root / 'docs/provenance/allowlist.json').read_text()):
    data = subprocess.check_output(['git', '-C', str(source), 'show', entry['commit'] + ':' + entry['source_path']])
    assert hashlib.sha256(data).hexdigest() == entry['source_sha256'], entry['source_path']
    actual = hashlib.sha256((root / entry['destination']).read_bytes()).hexdigest()
    assert actual == entry['import_sha256'], entry['destination']
print('All four allowlisted imports match their recorded source and destination hashes.')
