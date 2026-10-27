#!/usr/bin/env python3
"""Real local ONNX + packaged HTTP + PostgreSQL workflow. Synthetic inputs only.

Requires the dedicated Compose database, migrations from application startup, and
scripts/fetch_embeddings.py. Credentials stay in process memory/environment and
are never printed. Creates isolated synthetic users/data and stops its app process.
"""
import io
import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import textwrap
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:18080'


def pdf(*pages):
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'']
    page_ids = []
    for text in pages:
        page_id = len(objects) + 1
        content_id, font_id = page_id + 1, page_id + 2
        page_ids.append(page_id)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>'.encode())
        lines = textwrap.wrap(text, width=78)
        escaped = [line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') for line in lines]
        stream = ('BT /F1 12 Tf 16 TL 50 700 Td ' + ' T* '.join(f'({line}) Tj' for line in escaped) + ' ET').encode('ascii')
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream')
        objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(f"{i} 0 R" for i in page_ids)}] /Count {len(pages)} >>'.encode()
    out = io.BytesIO(); out.write(b'%PDF-1.4\n')
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(out.tell()); out.write(f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = out.tell()
    out.write(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        out.write(f'{offset:010d} 00000 n \n'.encode())
    out.write(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return out.getvalue()


def request(method, route, token=None, payload=None, headers=None):
    all_headers = dict(headers or {})
    if token:
        all_headers['Authorization'] = 'Bearer ' + token
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode(); all_headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + route, data=payload, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            raw = response.read()
            return response.status, json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw
    except urllib.error.HTTPError as error:
        return error.code, None  # do not log bodies, tokens, passwords or excerpts


def sql(statement, password=None):
    env = os.environ.copy()
    for line in (ROOT / '.local/runtime.env').read_text().splitlines():
        key, value = line.split('=', 1); env[key] = value
    args = ['docker', 'compose', '--env-file', '.local/runtime.env', 'exec', '-T']
    if password:
        env['SMOKE_USER_PASSWORD'] = password; args += ['-e', 'SMOKE_USER_PASSWORD']
    args += ['postgres', 'psql', '-U', 'postgres', '-d', 'investigator', '-v', 'ON_ERROR_STOP=1']
    result = subprocess.run(args, input=statement, text=True, capture_output=True, cwd=ROOT, env=env)
    if result.returncode:
        raise RuntimeError('Synthetic database fixture operation failed')


def upload(token, content, fields, route='/api/policies'):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
    body += content + f'\r\n--{boundary}--\r\n'.encode()
    status, value = request('POST', route, token, bytes(body), {'Content-Type': 'multipart/form-data; boundary=' + boundary, 'Idempotency-Key': str(uuid.uuid4())})
    if status != 202:
        raise RuntimeError(f'Synthetic upload returned HTTP {status}')
    return value


def completed(token, job):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status, value = request('GET', '/api/jobs/' + job, token)
        if status != 200:
            raise RuntimeError(f'Job polling returned HTTP {status}')
        if value['status'] == 'FAILED':
            raise RuntimeError('Ingestion failed with safe code: ' + value['error_code'])
        if value['status'] == 'COMPLETED':
            return
        time.sleep(0.5)
    raise RuntimeError('Ingestion did not finish within the smoke-test deadline')


def main():
    os.chdir(ROOT)
    env = os.environ.copy(); env['SERVER_PORT'] = '18080'
    log = (ROOT / '.local/smoke-app.log').open('w')
    if '--container' in sys.argv:
        class ContainerApp:
            args = ['docker', 'compose', '--env-file', '.local/runtime.env', '--env-file', '.local/embeddings.env', '--profile', 'app']
            def __init__(self):
                result = subprocess.run(self.args + ['up', '-d', 'backend'], capture_output=True, cwd=ROOT)
                if result.returncode:
                    raise RuntimeError('Backend container did not start')
            def poll(self):
                result = subprocess.run(self.args + ['ps', '--status', 'running', '--services', 'backend'], capture_output=True, text=True, cwd=ROOT)
                return None if 'backend' in result.stdout else 1
            def terminate(self):
                subprocess.run(self.args + ['stop', 'backend'], capture_output=True, cwd=ROOT)
            def wait(self, timeout=None):
                return 0
            def kill(self):
                self.terminate()
        app = ContainerApp()
    else:
        app = subprocess.Popen([sys.executable, 'scripts/run_local.py'], env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if app.poll() is not None:
                raise RuntimeError('Packaged application did not start; inspect .local/smoke-app.log')
            try:
                if request('GET', '/actuator/health')[0] == 200:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.RemoteDisconnected):
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError('Application startup timed out')
        org, dept, other_dept, user, other = [str(uuid.uuid4()) for _ in range(5)]
        password = secrets.token_urlsafe(24)
        sql(fr'''\getenv password SMOKE_USER_PASSWORD
BEGIN;
INSERT INTO organizations VALUES ('{org}','Synthetic smoke organization');
INSERT INTO departments VALUES ('{dept}','{org}','Compliance'),('{other_dept}','{org}','Other department');
INSERT INTO app_users(id,organization_id,email,password_hash) VALUES
 ('{user}','{org}','{user}@test.invalid',crypt(:'password',gen_salt('bf',10))),
 ('{other}','{org}','{other}@test.invalid',crypt(:'password',gen_salt('bf',10)));
INSERT INTO memberships VALUES ('{user}','{dept}','ANALYST'),('{other}','{other_dept}','ANALYST');
COMMIT;
''', password)
        status, auth = request('POST', '/api/auth/login', payload={'email': user + '@test.invalid', 'password': password})
        if status != 200:
            raise RuntimeError(f'Login returned HTTP {status}')
        token = auth['token']
        content = pdf('Report security incidents within 24 hours.', 'Meals during business travel are reimbursed up to thirty dollars.')
        baseline = upload(token, content, {'title': 'Synthetic incident policy', 'kind': 'POLICY', 'departmentId': dept, 'effectiveDate': '2026-10-26'})
        completed(token, baseline['jobId'])
        status, hits = request('POST', '/api/versions/' + baseline['versionId'] + '/search', token, {'query': 'How soon must a cybersecurity event be reported?'})
        if status != 200 or not hits or hits[0]['page_number'] != 1:
            raise RuntimeError('Local semantic retrieval did not rank the incident requirement first')
        source = hits[0]['id']
        status, evidence = request('GET', '/api/evidence/' + source, token)
        if status != 200 or '24 hours' not in evidence['excerpt']:
            raise RuntimeError('Evidence location/text did not match the source')
        status, original = request('GET', f"/api/policies/{baseline['policyId']}/versions/{baseline['versionId']}/content", token)
        if status != 200 or original != content:
            raise RuntimeError('Original PDF did not round-trip')
        replacement = upload(token, pdf('Report security incidents within 12 hours.'), {'previousVersionId': baseline['versionId'], 'effectiveDate': '2026-10-27'}, '/api/policies/' + baseline['policyId'] + '/versions')
        completed(token, replacement['jobId'])
        procedure = upload(token, pdf('The response team records and escalates security incidents.'), {'title': 'Synthetic response procedure', 'kind': 'PROCEDURE', 'departmentId': dept, 'effectiveDate': '2026-10-26'})
        completed(token, procedure['jobId'])
        status, versions = request('GET', '/api/policies/' + baseline['policyId'] + '/versions', token)
        if status != 200 or len(versions) != 2:
            raise RuntimeError('Policy version history is incomplete')
        status, auth = request('POST', '/api/auth/login', payload={'email': other + '@test.invalid', 'password': password})
        if status != 200:
            raise RuntimeError('Second synthetic user could not authenticate')
        if request('GET', '/api/evidence/' + source, auth['token'])[0] != 404:
            raise RuntimeError('Cross-department evidence isolation failed')
        sql(f"DELETE FROM memberships WHERE user_id='{user}';")
        if request('GET', '/api/evidence/' + source, token)[0] != 404:
            raise RuntimeError('Current membership revocation was not enforced')
        print(json.dumps({'result': 'PASS', 'model': 'all-MiniLM-L6-v2', 'model_revision': '1110a243fdf4706b3f48f1d95db1a4f5529b4d41', 'checks': ['packaged startup', 'JWT login', 'baseline upload', 'durable worker', 'real local embeddings', 'semantic ranking smoke', 'page evidence', 'original PDF round-trip', 'replacement version', 'procedure upload', 'cross-department denial', 'current membership revocation']}, indent=2))
    finally:
        app.terminate()
        try:
            app.wait(timeout=15)
        except subprocess.TimeoutExpired:
            app.kill(); app.wait()
        log.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as failure:
        print(str(failure), file=sys.stderr)
        sys.exit(1)
