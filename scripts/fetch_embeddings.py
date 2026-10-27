#!/usr/bin/env python3
"""Fetch the already verified public ONNX artifacts; never application documents.

Default mode preserves the host setup helper. Compose uses --directory /models,
--no-env-file and --runtime-cache /runtime in its short-lived initializer.
"""
import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
BASE = f'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{REVISION}'
ARTIFACTS = {
    'model.onnx': ('onnx/model.onnx', 90405214, 'sha256', '6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452'),
    'tokenizer.json': ('tokenizer.json', 466247, 'sha256', 'be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037'),
}
ATTEMPTS = 3
DOWNLOAD_BUDGET_SECONDS = 300


class ArtifactFailure(Exception):
    """Only stable codes and fixed artifact names are printed, never network URLs/errors."""
    def __init__(self, code, name):
        self.code, self.name = code, name
        super().__init__(code)


def verified(path, expected_size, algorithm, expected):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
        return False
    digest = hashlib.sha256() if algorithm == 'sha256' else hashlib.sha1()
    if algorithm == 'git-sha1':
        digest.update(f'blob {expected_size}\0'.encode())
    with path.open('rb') as source:
        for block in iter(lambda: source.read(65536), b''):
            digest.update(block)
    return digest.hexdigest() == expected


def ensure_artifact(directory, name, artifact, opener=urllib.request.urlopen, pause=time.sleep):
    remote, size, algorithm, expected = artifact
    target = directory / name
    if target.exists() or target.is_symlink():
        if not verified(target, size, algorithm, expected):
            raise ArtifactFailure('INVALID_CACHED_ARTIFACT', name)
        target.chmod(0o444)
        print(f'Embedding cache verified: {name}', flush=True)
        return 'cached'
    for attempt in range(ATTEMPTS):
        partial = None
        try:
            print(f'Downloading pinned embedding artifact: {name} (attempt {attempt + 1}/{ATTEMPTS})', flush=True)
            request = urllib.request.Request(f'{BASE}/{remote}', headers={'User-Agent': 'ai-policy-investigator-artifact-fetch'})
            started = time.monotonic()
            with opener(request, timeout=30) as response:
                with tempfile.NamedTemporaryFile(mode='wb', prefix='.' + name + '.', suffix='.part', dir=directory, delete=False) as out:
                    partial = Path(out.name)
                    count = 0
                    for block in iter(lambda: response.read(65536), b''):
                        if time.monotonic() - started > DOWNLOAD_BUDGET_SECONDS:
                            raise TimeoutError()
                        count += len(block)
                        if count > size:
                            raise ArtifactFailure('DOWNLOAD_SIZE_MISMATCH', name)
                        out.write(block)
                    out.flush()
                    os.fsync(out.fileno())
            if not verified(partial, size, algorithm, expected):
                raise ArtifactFailure('DOWNLOADED_ARTIFACT_INTEGRITY_FAILED', name)
            partial.chmod(0o444)
            partial.replace(target)
            print(f'Embedding download verified: {name}', flush=True)
            return 'downloaded'
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == ATTEMPTS:
                raise ArtifactFailure('DOWNLOAD_HTTP_' + str(error.code), name) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt + 1 == ATTEMPTS:
                raise ArtifactFailure('DOWNLOAD_NETWORK_OR_IO_FAILED', name) from None
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)
        pause(1 << attempt)
    raise ArtifactFailure('DOWNLOAD_FAILED', name)


def prepare(directory, runtime_cache=None):
    # POSIX locking serializes initializers sharing a volume; Linux containers/macOS tooling.
    import fcntl
    directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    directory.chmod(0o755)
    with (directory / '.embedding-init.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        counts = {'downloaded': 0, 'cached': 0}
        for name, artifact in ARTIFACTS.items():
            counts[ensure_artifact(directory, name, artifact)] += 1
        if runtime_cache is not None:
            runtime_cache.mkdir(parents=True, exist_ok=True, mode=0o750)
            if runtime_cache.is_symlink():
                raise ArtifactFailure('INVALID_RUNTIME_CACHE', 'runtime')
            os.chown(runtime_cache, 10001, 10001)
            runtime_cache.chmod(0o750)
        return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify/download the pinned 384-dimensional ONNX model and tokenizer.')
    parser.add_argument('--directory', type=Path, default=ROOT / '.local/models')
    parser.add_argument('--no-env-file', action='store_true', help='Container mode: do not write host fallback configuration.')
    parser.add_argument('--runtime-cache', type=Path, help='Prepare a public native cache volume for backend UID/GID 10001.')
    args = parser.parse_args(argv)
    try:
        directory = args.directory.resolve()
        counts = prepare(directory, args.runtime_cache)
        if not args.no_env_file:
            model, tokenizer = directory / 'model.onnx', directory / 'tokenizer.json'
            def sha(path):
                with path.open('rb') as source:
                    return hashlib.file_digest(source, 'sha256').hexdigest()
            content = f'EMBEDDING_MODEL_URI={model.as_uri()}\nEMBEDDING_TOKENIZER_URI={tokenizer.as_uri()}\nEMBEDDING_REVISION={sha(model)}:{sha(tokenizer)}\n'
            (ROOT / '.local').mkdir(parents=True, exist_ok=True, mode=0o700)
            (ROOT / '.local/embeddings.env').write_text(content)
        print(f'Embedding artifacts ready: revision={REVISION} dimensions=384 downloaded={counts["downloaded"]} cached={counts["cached"]}', flush=True)
        return 0
    except ArtifactFailure as failure:
        print(f'Embedding initialization failed: {failure.code} ({failure.name})', file=sys.stderr)
    except (OSError, ValueError):
        print('Embedding initialization failed: FILESYSTEM_OR_CONFIGURATION_ERROR', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
