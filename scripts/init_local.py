#!/usr/bin/env python3
"""Generate new local-only credentials. Never reads or imports another project's environment."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
local = root / '.local'
local.mkdir(mode=0o700, exist_ok=True)
local.chmod(0o700)
cache = local / 'native-cache'
cache.mkdir(exist_ok=True)
cache.chmod(0o777)  # public dependency cache inside owner-only parent; nonroot container writes here
path = local / 'runtime.env'
keys = ['POSTGRES_ADMIN_PASSWORD', 'OWNER_DB_PASSWORD', 'APP_DB_PASSWORD', 'JWT_SECRET']
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as out:
    for key in keys:
        out.write(f'{key}={secrets.token_hex(32)}\n')
print('Created .local/runtime.env with new credentials; existing files are never overwritten.')
