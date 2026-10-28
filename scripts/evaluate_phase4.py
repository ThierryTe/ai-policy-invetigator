#!/usr/bin/env python3
"""Small real Muse evaluation through authorized upload/investigation/review APIs.

Synthetic fixtures only. Needs the dedicated local Compose database and operator
access used by smoke_workflow.sql. Never records tokens, passwords or provider keys.
--start-backend builds/starts the existing deployment and stops that backend on exit.
Without the flag, uses an already running backend without changing its lifecycle.
"""
import argparse
import datetime
import hashlib
import json
import secrets
import subprocess
import time
import uuid

from smoke_workflow import ROOT, completed, pdf, request, sql, upload
from smoke_investigation import api

COMPOSE = ['docker', 'compose', '--env-file', '.env', '--profile', 'app']


def case_result(case, progress, findings):
    """Keep infrastructure/validation failures separate from semantic predictions."""
    if progress['state'] != 'COMPLETED':
        safe_abstention = progress['state'] == 'PARTIAL' and progress.get('error_code') in (
            'INCOMPLETE_EXTRACTION', 'INCOMPLETE_ASSESSMENT')
        return {'observed': 'ABSTAIN' if safe_abstention else 'ERROR',
                'matched': case['expected'] == 'ABSTAIN' and safe_abstention,
                'errorCode': progress.get('error_code')}
    labels = sorted({f['classification'] for f in findings})
    observed = next((v for v in ('CONTRADICTION', 'AMBIGUITY', 'MISSING_REQUIREMENT', 'NO_CONFLICT') if v in labels), 'ERROR')
    matched = observed == case['expected'] or case['expected'] == 'ABSTAIN' and observed == 'AMBIGUITY'
    return {'observed': observed, 'classifications': labels, 'matched': matched, 'errorCode': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-backend', action='store_true')
    parser.add_argument('--max-procedures', type=int, choices=(1, 2, 3, 4), default=2,
                        help='Bound comparison output per investigation (default: 2).')
    dataset_path = ROOT / 'evaluation/phase4-golden.json'
    dataset = json.loads(dataset_path.read_text())
    parser.add_argument('--group', choices=[g['id'] for g in dataset['groups']], help='Run a targeted group, preserving the full-run report.')
    args = parser.parse_args()
    groups = []
    for group in dataset['groups']:
        if args.group and group['id'] != args.group:
            continue
        for offset in range(0, len(group['cases']), args.max_procedures):
            groups.append({**group, 'id': group['id'] + '-' + str(offset // args.max_procedures + 1),
                           'cases': group['cases'][offset:offset + args.max_procedures]})
    report = {'recordedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'model': 'muse-spark-1.3', 'provider': 'Meta Model API', 'syntheticOnly': True,
              'datasetVersion': dataset['version'], 'selectedGroup': args.group, 'maxProceduresPerInvestigation': args.max_procedures, 'datasetSha256': hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
              'limitation': dataset['limitation'], 'groups': [], 'cases': [], 'result': 'NOT_COMPLETED'}
    filename = 'phase4-' + args.group + '-evaluation.json' if args.group else 'phase4-evaluation.json'
    output = ROOT / 'docs/verification' / filename
    if output.exists():
        archive = output.parent / 'phase4-attempts'
        archive.mkdir(exist_ok=True)
        (archive / (str(time.time_ns()) + '.json')).write_bytes(output.read_bytes())
    actor = None
    try:
        if args.start_backend:
            started = subprocess.run(COMPOSE + ['up', '--build', '-d', '--wait', 'backend'], cwd=ROOT, capture_output=True)
            if started.returncode:
                raise RuntimeError('EVALUATION_BACKEND_START_FAILED')
        if request('GET', '/actuator/health')[0] != 200:
            raise RuntimeError('EVALUATION_BACKEND_NOT_READY')
        organization, security, hr, actor, outsider = [str(uuid.uuid4()) for _ in range(5)]
        password = secrets.token_urlsafe(24)
        sql(fr'''\getenv password SMOKE_USER_PASSWORD
BEGIN;
INSERT INTO organizations VALUES ('{organization}','Synthetic Phase 4 evaluation');
INSERT INTO departments VALUES ('{security}','{organization}','Security'),('{hr}','{organization}','HR');
INSERT INTO app_users(id,organization_id,email,password_hash) VALUES
 ('{actor}','{organization}','{actor}@test.invalid',crypt(:'password',gen_salt('bf',10))),
 ('{outsider}','{organization}','{outsider}@test.invalid',crypt(:'password',gen_salt('bf',10)));
INSERT INTO memberships VALUES ('{actor}','{security}','ADMIN'),('{actor}','{hr}','ADMIN'),('{outsider}','{hr}','REVIEWER');
COMMIT;
''', password)
        token = api('POST', '/api/auth/login', None, {'email': actor + '@test.invalid', 'password': password})['token']
        other = api('POST', '/api/auth/login', None, {'email': outsider + '@test.invalid', 'password': password})['token']
        checked_review = False
        for group in groups:
            baseline = upload(token, pdf(group['baseline']), {'title': 'Synthetic ' + group['id'], 'kind': 'POLICY',
                              'departmentId': security, 'effectiveDate': '2026-10-26'})
            completed(token, baseline['jobId'])
            replacement = upload(token, pdf(group['replacement']), {'previousVersionId': baseline['versionId'],
                                 'effectiveDate': dataset['analysisDate']}, '/api/policies/' + baseline['policyId'] + '/versions')
            completed(token, replacement['jobId'])
            api('POST', '/api/policies/' + baseline['policyId'] + '/external-processing', token, {'allowed': True}, expected=204)
            procedures = []
            for case in group['cases']:
                procedure = upload(token, pdf(case['procedure']), {'title': 'Synthetic ' + case['id'], 'kind': 'PROCEDURE',
                                   'departmentId': hr, 'effectiveDate': '2026-10-26'})
                completed(token, procedure['jobId'])
                api('POST', '/api/policies/' + procedure['policyId'] + '/external-processing', token, {'allowed': True}, expected=204)
                procedures.append(procedure)
            began = time.monotonic()
            inv = api('POST', '/api/investigations', token, {'baselineVersionId': baseline['versionId'],
                      'replacementVersionId': replacement['versionId'], 'procedureVersionIds': [p['versionId'] for p in procedures],
                      'analysisDate': dataset['analysisDate']}, expected=202, headers={'Idempotency-Key': str(uuid.uuid4())})
            route = '/api/investigations/' + inv['id']
            deadline = time.monotonic() + 270
            while time.monotonic() < deadline:
                progress = api('GET', route, token)
                if progress['state'] in ('COMPLETED', 'PARTIAL', 'FAILED'):
                    break
                time.sleep(1)
            else:
                raise RuntimeError('EVALUATION_POLLING_DEADLINE')
            findings = api('GET', route + '/findings', token)
            extractions = api('GET', route + '/requirements', token)
            graph = api('GET', route + '/graph', token)
            node_ids = {n['id'] for n in graph['nodes']}
            if any(e['source'] not in node_ids or e['target'] not in node_ids for e in graph['edges']):
                raise RuntimeError('GRAPH_DANGLING_EDGE')
            refs = []
            for ext in extractions:
                for req in ext['payload']['requirements']:
                    refs.extend(req['sourceReferences'])
            payload = findings.get('payload', {})
            for item in payload.get('changes', []) + payload.get('assessments', []):
                refs.extend(item['sourceReferences'])
            verified = []
            for ref in refs:
                evidence = api('GET', '/api/evidence/' + ref['sourceId'], token)
                valid = ref['quote'] in evidence['excerpt']
                verified.append({'sourceId': ref['sourceId'], 'page': evidence['page_number'], 'quoteMatches': valid})
                if not valid:
                    raise RuntimeError('EVALUATION_CITATION_MISMATCH')
            for endpoint in (route, route + '/findings', route + '/graph', route + '/requirements'):
                api('GET', endpoint, other, expected=404)
            if payload.get('assessments') and not checked_review:
                original = payload
                finding = payload['assessments'][0]['id']
                review_route = route + '/findings/' + finding + '/reviews'
                api('POST', review_route, other, {'action': 'CONFIRM'}, expected=404)
                api('POST', review_route, token, {'action': 'CONFIRM', 'note': 'Synthetic reviewer checked both sources.'})
                note = api('POST', review_route, token, {'action': 'ADD_NOTE', 'note': 'Synthetic test note.'})
                if note['status'] != 'CONFIRMED':
                    raise RuntimeError('NOTE_CHANGED_REVIEW_DECISION')
                reviewed = api('POST', review_route, token, {'action': 'DISMISS', 'note': 'Synthetic alternative decision for workflow verification.'})
                if reviewed['status'] != 'DISMISSED' or len(reviewed['history']) != 3 or original != api('GET', route + '/findings', token)['payload']:
                    raise RuntimeError('REVIEW_IMMUTABILITY_FAILED')
                checked_review = True
            for case, proc in zip(group['cases'], procedures):
                selected = [f for f in payload.get('assessments', []) if f['procedureVersionId'] == proc['versionId']]
                report['cases'].append({'id': case['id'], 'category': case['category'], 'expected': case['expected'],
                                        'procedureVersionId': proc['versionId'], **case_result(case, progress, selected)})
            report['groups'].append({'id': group['id'], 'investigationId': inv['id'], 'elapsedMs': round((time.monotonic() - began) * 1000),
                                     'progress': progress, 'findings': findings, 'extractions': extractions, 'graph': graph,
                                     'verifiedCitations': verified, 'authorizationDenialsVerified': True})
            output.write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({'group': group['id'], 'state': progress['state'], 'error': progress.get('error_code'),
                              'cases': [{k: c[k] for k in ('id', 'expected', 'observed', 'matched')} for c in report['cases'][-len(group['cases']):]]}), flush=True)
        # A valid token immediately loses graph and review access after department revocation.
        last_route = '/api/investigations/' + report['groups'][0]['investigationId']
        sql(f"DELETE FROM memberships WHERE user_id='{actor}' AND department_id='{security}';")
        api('GET', last_route + '/graph', token, expected=404)
        api('GET', last_route + '/findings', token, expected=404)
        first = report['groups'][0]['findings'].get('payload', {}).get('assessments', [])
        if first:
            api('POST', last_route + '/findings/' + first[0]['id'] + '/reviews', token, {'action': 'CONFIRM'}, expected=404)
        cases = report['cases']
        tp = sum(c['expected'] == 'CONTRADICTION' and c['observed'] == 'CONTRADICTION' for c in cases)
        fp = sum(c['expected'] != 'CONTRADICTION' and c['observed'] == 'CONTRADICTION' for c in cases)
        fn = sum(c['expected'] == 'CONTRADICTION' and c['observed'] != 'CONTRADICTION' for c in cases)
        citations = [v for g in report['groups'] for v in g['verifiedCitations']]
        report['metrics'] = {'cases': len(cases), 'matched': sum(c['matched'] for c in cases),
                             'errors': sum(c['observed'] == 'ERROR' for c in cases),
                             'contradictionTruePositives': tp, 'contradictionFalsePositives': fp, 'contradictionFalseNegatives': fn,
                             'contradictionPrecision': tp / (tp + fp) if tp + fp else None,
                             'contradictionRecall': tp / (tp + fn) if tp + fn else None,
                             'citationInstances': len(citations), 'verifiedCitationInstances': sum(v['quoteMatches'] for v in citations),
                             'citationCorrectness': sum(v['quoteMatches'] for v in citations) / len(citations) if citations else None,
                             **{k: sum(g['progress'][k] for g in report['groups']) for k in ('calls', 'metered_calls', 'prompt_tokens', 'completion_tokens', 'latency_ms')}}
        report.update({'result': 'COMPLETED', 'reviewWorkflowVerified': checked_review, 'revocationVerified': True})
        print(json.dumps(report['metrics'], indent=2), flush=True)
    except Exception:
        report['result'] = 'RUN_FAILED'
        report['safeFailure'] = 'EVALUATION_RUN_FAILED_SEE_COMPLETED_GROUPS'
        raise RuntimeError(report['safeFailure']) from None
    finally:
        output.write_text(json.dumps(report, indent=2) + '\n')
        if actor:
            sql(f"UPDATE app_users SET active=false WHERE id IN ('{actor}','{outsider}');")
        if args.start_backend:
            subprocess.run(COMPOSE + ['stop', 'backend'], cwd=ROOT, capture_output=True)


if __name__ == '__main__':
    main()
