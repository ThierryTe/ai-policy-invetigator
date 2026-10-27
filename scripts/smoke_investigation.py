#!/usr/bin/env python3
"""Real Meta + packaged Linux backend demonstration. Synthetic documents only.

No provider substitutions. Credentials are supplied through Compose env files and
process memory. Only synthetic evidence and safe usage metadata are recorded.
"""
import datetime
import http.client
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import uuid

from smoke_workflow import ROOT, completed, pdf, request, sql, upload

COMPOSE = ['docker', 'compose', '--env-file', '.local/runtime.env',
           '--env-file', '.local/embeddings.env', '--env-file', '.env', '--profile', 'app']


def api(method, path, token, payload=None, expected=200, headers=None):
    status, value = request(method, path, token, payload, headers)
    if status != expected:
        raise RuntimeError(f'{method} {path} returned HTTP {status}')
    return value


def main():
    result = {'recordedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'provider': 'Meta Model API', 'model': 'muse-spark-1.3',
              'syntheticOnly': True, 'result': 'NOT_COMPLETED'}
    golden = json.loads((ROOT / 'evaluation/phase3-golden.json').read_text())
    result['goldenDatasetVersion'] = golden['version']
    output = ROOT / 'docs/verification/phase3-demo.json'
    if output.exists():
        archive = ROOT / 'docs/verification/phase3-attempts'
        archive.mkdir(exist_ok=True)
        (archive / (str(time.time_ns()) + '.json')).write_bytes(output.read_bytes())
    try:
        started = subprocess.run(COMPOSE + ['up', '-d', 'backend'], cwd=ROOT, capture_output=True)
        if started.returncode:
            raise RuntimeError('Backend container could not start')
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if request('GET', '/actuator/health')[0] == 200:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.RemoteDisconnected):
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Packaged backend startup timed out')
        organization, security, hr, actor, outsider = [str(uuid.uuid4()) for _ in range(5)]
        password = secrets.token_urlsafe(24)
        sql(fr'''\getenv password SMOKE_USER_PASSWORD
BEGIN;
INSERT INTO organizations VALUES ('{organization}','Synthetic Phase 3 demonstration');
INSERT INTO departments VALUES ('{security}','{organization}','Security'),('{hr}','{organization}','HR');
INSERT INTO app_users(id,organization_id,email,password_hash) VALUES
 ('{actor}','{organization}','{actor}@test.invalid',crypt(:'password',gen_salt('bf',10))),
 ('{outsider}','{organization}','{outsider}@test.invalid',crypt(:'password',gen_salt('bf',10)));
INSERT INTO memberships VALUES ('{actor}','{security}','ADMIN'),('{actor}','{hr}','ADMIN'),('{outsider}','{hr}','ANALYST');
COMMIT;
''', password)
        token = api('POST', '/api/auth/login', None, {'email': actor + '@test.invalid', 'password': password})['token']
        other_token = api('POST', '/api/auth/login', None, {'email': outsider + '@test.invalid', 'password': password})['token']
        baseline = upload(token, pdf(golden['baseline']),
                          {'title': 'Synthetic sensitive-system training policy', 'kind': 'POLICY', 'departmentId': security, 'effectiveDate': '2026-10-26'})
        completed(token, baseline['jobId'])
        replacement = upload(token, pdf(golden['replacement']),
                             {'previousVersionId': baseline['versionId'], 'effectiveDate': '2026-10-27'}, '/api/policies/' + baseline['policyId'] + '/versions')
        completed(token, replacement['jobId'])
        bad = upload(token, pdf(golden['cases'][0]['procedure']),
                     {'title': 'Synthetic incompatible HR access procedure', 'kind': 'PROCEDURE', 'departmentId': hr, 'effectiveDate': '2026-10-26'})
        good = upload(token, pdf(golden['cases'][1]['procedure']),
                      {'title': 'Synthetic compatible HR access procedure', 'kind': 'PROCEDURE', 'departmentId': hr, 'effectiveDate': '2026-10-26'})
        for document in (bad, good):
            completed(token, document['jobId'])
        for document in (baseline, bad, good):
            api('POST', '/api/policies/' + document['policyId'] + '/external-processing', token, {'allowed': True}, expected=204)
        scope = {'baselineVersionId': baseline['versionId'], 'replacementVersionId': replacement['versionId'],
                 'procedureVersionIds': [bad['versionId'], good['versionId']], 'analysisDate': '2026-10-27'}
        began = time.monotonic()
        investigation = api('POST', '/api/investigations', token, scope, expected=202, headers={'Idempotency-Key': str(uuid.uuid4())})
        route = '/api/investigations/' + investigation['id']
        result.update({'investigationId': investigation['id'], 'scope': scope,
                       'expectedContradictionProcedure': bad['versionId'], 'expectedCompatibleProcedure': good['versionId']})
        deadline = time.monotonic() + 270
        while time.monotonic() < deadline:
            progress = api('GET', route, token)
            if progress['state'] in ('COMPLETED', 'PARTIAL', 'FAILED'):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Investigation polling deadline exceeded')
        result['elapsedMs'] = round((time.monotonic() - began) * 1000)
        result['progress'] = progress
        result['extractions'] = api('GET', route + '/requirements', token)
        result['findings'] = api('GET', route + '/findings', token)
        if progress['state'] != 'COMPLETED':
            raise RuntimeError('Real investigation stopped: ' + str(progress.get('error_code')))
        findings = result['findings']['payload']
        assessments = findings['assessments']
        if any(f['reviewStatus'] != 'PENDING_REVIEW' for f in assessments if f['classification'] != 'NO_CONFLICT'):
            raise RuntimeError('Actionable finding did not require human review')
        incompatible = [f for f in assessments if f['procedureVersionId'] == bad['versionId']]
        compatible = [f for f in assessments if f['procedureVersionId'] == good['versionId']]
        if not any(f['classification'] == 'CONTRADICTION' for f in incompatible):
            raise RuntimeError('Known contradiction was not identified')
        if not compatible or any(f['classification'] != 'NO_CONFLICT' for f in compatible):
            raise RuntimeError('Compatible procedure produced a false positive')
        references = []
        for extraction in result['extractions']:
            for requirement in extraction['payload']['requirements']:
                references.extend(requirement['sourceReferences'])
        for finding in assessments + findings['changes']:
            references.extend(finding['sourceReferences'])
        verified = []
        for ref in references:
            evidence = api('GET', '/api/evidence/' + ref['sourceId'], token)
            if ref['quote'] not in evidence['excerpt']:
                raise RuntimeError('Citation did not match persisted PDF evidence')
            verified.append({'sourceId': ref['sourceId'], 'page': evidence['page_number'], 'quoteMatches': True})
        for endpoint in (route, route + '/findings', route + '/requirements'):
            api('GET', endpoint, other_token, expected=404)
        # A still-valid JWT must immediately lose access after membership revocation.
        sql(f"DELETE FROM memberships WHERE user_id='{actor}' AND department_id='{security}';")
        api('GET', route + '/findings', token, expected=404)
        result.update({'result': 'PASS', 'verifiedCitations': verified,
                       'checks': ['real Meta extraction', 'real Meta comparison', 'pending human review', 'non-conflict control', 'citation lookup', 'cross-department denial', 'current permission revocation'],
                       'evaluation': {'positiveProcedureCases': 1, 'negativeProcedureCases': 1,
                                      'truePositives': 1, 'falsePositives': 0, 'falseNegatives': 0,
                                      'precision': 1.0, 'recall': 1.0, 'citationCorrectness': 1.0,
                                      'limitation': 'Two selected synthetic procedure cases; does not establish general accuracy.'}})
        print(json.dumps({'result': result['result'], 'state': progress['state'], 'elapsedMs': result['elapsedMs'],
                          'usage': {k: v for k, v in progress.items() if 'token' in k or 'calls' in k or 'latency' in k},
                          'findings': [f['classification'] for f in assessments]}, indent=2))
    except Exception as failure:
        # All raised messages above contain stable codes/paths, never request bodies or credentials.
        result['safeFailure'] = str(failure)
        raise
    finally:
        output.write_text(json.dumps(result, indent=2) + '\n')
        subprocess.run(COMPOSE + ['stop', 'backend'], cwd=ROOT, capture_output=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as failure:
        print(str(failure), file=sys.stderr)
        sys.exit(1)
