#!/usr/bin/env python3
"""Offline follow-up to preparation run 41196074748; never execute image/application code.

The GitHub artifact ZIP digest is an independent trust anchor, not SHA256SUMS
from an arbitrary directory. Reuse the successful image/migration checks after
checking that anchor. Compare complete JAR bytes; payload equivalence is separate.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from deploy_local_images import require
from release_artifacts import file_sha, sha
from release_safety import EVIDENCE_SHA256

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = '41196074748'
ARTIFACT_ID = '13040377866'
ARTIFACT_SHA256 = '08cbb4078946660503280efe740d172c1c56c62d2e0aa9428436f0f76ebe202b'
TOOLING_REVISION = 'afa68f0c62ba502f213a4235e6f281a1a5fb17cd'
SOURCE_REVISION = '48669d57b32cd1acb83acc57bd9da50b02ee3cd0'
MANIFEST_DIGEST = 'sha256:dca3389c5555b09c13e4f643074a6c7684d9ba7d3d73f931b34d53fcb9276eea'
CONFIG_DIGEST = 'sha256:baf9cf5911c21e0129afa1700a91abec14f88bd4c4ff9d74b8943efd45baf76d'
QUALIFICATION_SHA256 = '42f092a28a73a5520b3faa1a2e60e274872e3bce61b57320810231310c20fc36'
REPOSITORY = 'ghcr.io/thierryte/ai-policy-invetigator'
FILES = {'BACKEND_IMAGE_REF.tar', 'evidence.json', 'SHA256SUMS'}
MAX_JAR = 512 * 1024**2


def baseline(jar, reports):
    require(file_sha(ROOT / 'docs/verification/v8-artifact.json') == EVIDENCE_SHA256,
            'HISTORICAL_ARTIFACT_EVIDENCE_CHANGED')
    record = json.loads((ROOT / 'docs/verification/v8-artifact.json').read_text())
    require(file_sha(jar) == record['jar_sha256'], 'HISTORICAL_JAR_CHANGED')
    qualification = ROOT / 'docs/verification/v8-qualification.json'
    require(file_sha(qualification) == QUALIFICATION_SHA256, 'HISTORICAL_QUALIFICATION_CHANGED')
    historical = json.loads(qualification.read_text())
    total = 0
    for suite in historical['suites']:
        path = reports / ('TEST-' + suite['suite'] + '.xml')
        require(file_sha(path) == suite['report_sha256'], 'HISTORICAL_REPORT_CHANGED')
        xml = ET.parse(path).getroot()
        require(xml.tag == 'testsuite' and xml.get('name') == suite['suite'], 'HISTORICAL_SUITE_MISMATCH')
        for key in ('tests', 'failures', 'errors', 'skipped'):
            require(int(xml.get(key, '-1')) == suite[key], 'HISTORICAL_TEST_COUNTS_CHANGED')
        require(all(suite[key] == 0 for key in ('failures', 'errors', 'skipped')), 'HISTORICAL_TESTS_NOT_PASSING')
        total += suite['tests']
    require(total == historical['java_tests'], 'HISTORICAL_TEST_TOTAL_MISMATCH')
    return {'jarSha256': record['jar_sha256'], 'artifactEvidenceSha256': EVIDENCE_SHA256,
            'qualificationEvidenceSha256': QUALIFICATION_SHA256,
            'reportHashesVerified': len(historical['suites']), 'javaTests': total,
            'failures': 0, 'errors': 0, 'skipped': 0, 'testsRerun': False}


def unpack_verified_bundle(bundle, work):
    require(file_sha(bundle) == ARTIFACT_SHA256, 'GITHUB_ARTIFACT_ZIP_DIGEST_MISMATCH')
    with zipfile.ZipFile(bundle) as archive:
        members = archive.infolist()
        require(len(members) == 3 and {m.filename for m in members} == FILES,
                'QUALIFICATION_BUNDLE_CONTENT_INVALID')
        for member in members:
            require(not member.is_dir() and member.file_size < 2 * 1024**3,
                    'QUALIFICATION_BUNDLE_MEMBER_INVALID')
            with archive.open(member) as source, (work / member.filename).open('xb') as target:
                while block := source.read(1024**2):
                    target.write(block)
    lines = (work / 'SHA256SUMS').read_text().splitlines()
    expected = {}
    for line in lines:
        match = re.fullmatch(r'([0-9a-f]{64})  (BACKEND_IMAGE_REF\.tar|evidence\.json)', line)
        require(match is not None and match[2] not in expected, 'QUALIFICATION_CHECKSUMS_INVALID')
        expected[match[2]] = match[1]
    require(set(expected) == FILES - {'SHA256SUMS'}, 'QUALIFICATION_CHECKSUMS_INCOMPLETE')
    for name, digest in expected.items():
        require(file_sha(work / name) == digest, 'QUALIFICATION_FILE_DIGEST_MISMATCH')
    evidence = json.loads((work / 'evidence.json').read_text())
    checks = {'format': 1, 'result': 'PASS', 'platform': 'linux/amd64',
              'sourceRevision': SOURCE_REVISION, 'manifestDigest': MANIFEST_DIGEST,
              'configDigest': CONFIG_DIGEST, 'archive': 'BACKEND_IMAGE_REF.tar',
              'archiveSha256': expected['BACKEND_IMAGE_REF.tar'],
              'sourceRepository': 'https://github.com/ThierryTe/ai-policy-invetigator',
              'sourceRef': REPOSITORY + '@' + MANIFEST_DIGEST,
              'localRef': REPOSITORY + ':deploy-' + MANIFEST_DIGEST[7:],
              'qualifiedEvidenceSha256': EVIDENCE_SHA256,
              'migrationEquivalenceVerified': True, 'binaryIdentityVerified': False,
              'productionBuildProfileQualified': False}
    require(all(type(evidence.get(k)) is type(v) and evidence[k] == v for k, v in checks.items()),
            'QUALIFICATION_EVIDENCE_BINDING_MISMATCH')
    require(evidence.get('github') == {'repository': 'ThierryTe/ai-policy-invetigator',
            'toolingRevision': TOOLING_REVISION, 'runId': RUN_ID, 'runAttempt': '1'},
            'QUALIFICATION_RUN_BINDING_MISMATCH')
    require(evidence.get('migrations') == json.loads(
        (ROOT / 'docs/verification/v8-artifact.json').read_text())['migrations'],
        'QUALIFICATION_HISTORICAL_REFERENCE_MISMATCH')
    return evidence


def image_jar(path, evidence):
    """Read the effective JAR without loading Docker or rehashing passed layer DiffIDs.

    The outer ZIP digest and per-file checksums must be verified first. Whiteouts
    apply to lower layers, independent of member ordering within the current layer.
    Refuse links/duplicate entries affecting the JAR instead of following them.
    """
    jar = None
    with tarfile.open(path, 'r:') as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        require(len(manifest) == 1 and manifest[0]['RepoTags'] == [evidence['localRef']],
                'QUALIFICATION_ARCHIVE_REFERENCE_MISMATCH')
        row = manifest[0]
        config_bytes = archive.extractfile(row['Config']).read()
        require('sha256:' + sha(config_bytes) == CONFIG_DIGEST, 'QUALIFICATION_CONFIG_MISMATCH')
        config = json.loads(config_bytes)
        require(config['rootfs']['diff_ids'] == evidence['layerDiffIds'], 'QUALIFICATION_LAYERS_MISMATCH')
        for name in row['Layers']:
            replacement, deleted, seen = None, False, set()
            with tarfile.open(fileobj=archive.extractfile(name), mode='r|*') as layer:
                for member in layer:
                    normalized = member.name.removeprefix('./').rstrip('/')
                    if normalized not in {'app', 'app/investigator.jar', '.wh.app',
                                          'app/.wh.investigator.jar', 'app/.wh..wh..opq', '.wh..wh..opq'}:
                        continue
                    require(normalized not in seen, 'AMBIGUOUS_JAR_LAYER_ENTRY')
                    seen.add(normalized)
                    if normalized == 'app':
                        require(member.isdir(), 'JAR_PARENT_MUST_BE_DIRECTORY')
                    elif normalized == 'app/investigator.jar':
                        require(member.isfile() and 0 < member.size < MAX_JAR, 'IMAGE_JAR_INVALID')
                        replacement = layer.extractfile(member).read()
                    else:
                        require(member.isfile(), 'IMAGE_WHITEOUT_INVALID')
                        deleted = True
            if deleted:
                jar = None
            if replacement is not None:
                jar = replacement
    require(jar is not None, 'IMAGE_JAR_MISSING')
    return jar


def jar_inventory(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        require(len({m.filename for m in members}) == len(members), 'DUPLICATE_JAR_ENTRY')
        result = {}
        total = 0
        for member in members:
            total += member.file_size
            require(total < 2 * 1024**3, 'JAR_EXPANSION_TOO_LARGE')
            if not member.is_dir():
                with archive.open(member) as stream:
                    result[member.filename] = hashlib.file_digest(stream, 'sha256').hexdigest()
        return result


def payload_delta(old, new):
    return {'added': sorted(new.keys() - old.keys()), 'removed': sorted(old.keys() - new.keys()),
            'changed': sorted(k for k in old.keys() & new.keys() if old[k] != new[k])}


def compare_jars(historical, prepared):
    old, new = jar_inventory(historical), jar_inventory(prepared)
    delta = payload_delta(old, new)
    classes = 'BOOT-INF/classes/'
    libraries = 'BOOT-INF/lib/'
    old_classes = {k: v for k, v in old.items() if k.startswith(classes)}
    require(bool(old_classes), 'HISTORICAL_APPLICATION_PAYLOAD_MISSING')
    return {'historicalJarSha256': sha(historical), 'preparedJarSha256': sha(prepared),
            'binaryIdentityVerified': sha(historical) == sha(prepared),
            'binaryIdentityStatus': 'MATCH' if sha(historical) == sha(prepared) else 'MISMATCH',
            'allEntryPayloadsIdentical': not any(delta.values()),
            'applicationPayloadIdentical': old_classes == {k: v for k, v in new.items() if k.startswith(classes)},
            'entryDelta': delta,
            'dependencyDelta': payload_delta({k: v for k, v in old.items() if k.startswith(libraries)},
                                            {k: v for k, v in new.items() if k.startswith(libraries)}),
            'transformerLibrariesPresent': all(any(k.startswith(libraries + prefix) for k in new)
                for prefix in ('spring-ai-transformers-', 'spring-ai-autoconfigure-model-transformers-',
                               'onnxruntime-', 'tokenizers-')),
            'productionBuildProfileQualified': False,
            'profileQualificationReason': 'Packaged dependencies are static evidence only; no real embedding runtime was tested.'}


def verify(bundle, jar, reports):
    result = {'scope': 'Offline preparation evidence only; no production authorization.',
              'historicalEvidence': baseline(jar, reports), 'productionBuildProfileQualified': False}
    if bundle is None:
        result.update(result='BLOCKED', binaryIdentityVerified=False,
                      binaryIdentityStatus='NOT_CHECKED',
                      blockers=['APPROVED_PREPARATION_ARTIFACT_REQUIRED', 'PRODUCTION_PROFILE_RUNTIME_EVIDENCE_REQUIRED'])
        return result
    with tempfile.TemporaryDirectory(prefix='backend-gates-') as temporary:
        work = Path(temporary)
        evidence = unpack_verified_bundle(bundle, work)
        comparison = compare_jars(jar.read_bytes(), image_jar(work / 'BACKEND_IMAGE_REF.tar', evidence))
    result.update(result='BLOCKED', preparationRunId=RUN_ID, artifactId=ARTIFACT_ID,
                  artifactZipSha256=ARTIFACT_SHA256, migrationEquivalenceReused=True,
                  registryOrMigrationChecksRerun=False, comparison=comparison,
                  binaryIdentityVerified=comparison['binaryIdentityVerified'],
                  binaryIdentityStatus=comparison['binaryIdentityStatus'],
                  blockers=([] if comparison['binaryIdentityVerified'] else ['FULL_JAR_BINARY_IDENTITY_MISMATCH'])
                  + ['PRODUCTION_PROFILE_RUNTIME_EVIDENCE_REQUIRED'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-zip', type=Path, help='Original ZIP downloaded from the pinned successful run.')
    parser.add_argument('--historical-jar', type=Path, default=ROOT / 'target/ai-policy-investigator-0.1.0-SNAPSHOT.jar')
    parser.add_argument('--historical-reports', type=Path, default=ROOT / 'target/surefire-reports')
    parser.add_argument('--output', type=Path, help='New JSON file outside the repository; never overwritten.')
    args = parser.parse_args(argv)
    try:
        if args.output:
            require(not args.output.is_symlink() and not args.output.exists()
                    and not args.output.resolve().is_relative_to(ROOT), 'NEW_EXTERNAL_OUTPUT_REQUIRED')
        result = verify(args.artifact_zip, args.historical_jar, args.historical_reports)
        serialized = json.dumps(result, indent=2) + '\n'
        if args.output:
            with args.output.open('x') as stream:
                stream.write(serialized)
        print(serialized, end='')
        return 2  # Neither static comparison nor baseline validation certifies runtime qualification.
    except Exception:
        print('BACKEND_GATE_VERIFICATION_FAILED; no new qualification evidence is valid.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
