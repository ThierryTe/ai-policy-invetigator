#!/usr/bin/env python3
"""Run with Spring dotenv; legacy local files are optional fallbacks, never overrides."""
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
env = os.environ.copy()
# This is an explicit development launcher; production starts Java with runtime secrets.
# A real process setting (including false) always takes precedence.
env.setdefault('SPRINGDOTENV_ENABLED', 'true')
dotenv_keys = set()
if (root / '.env').exists():
    for line in (root / '.env').read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            dotenv_keys.add(line.split('=', 1)[0].removeprefix('export ').strip())
for config in ['runtime.env', 'embeddings.env']:
    path = root / '.local' / config
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                if key not in dotenv_keys:
                    env.setdefault(key, value)
os.execvpe('java', ['java', '-jar', 'target/ai-policy-investigator-0.1.0-SNAPSHOT.jar'], env)
