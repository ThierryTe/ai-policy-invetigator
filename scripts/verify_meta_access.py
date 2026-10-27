#!/usr/bin/env python3
"""Verify the official Meta API with fixed synthetic input only.

Reads MODEL_API_KEY and optional META_MODEL_ID from the environment or this project's
ignored .local/meta.env. Never reads enterprise documents, other repositories or
credential stores. No SDK/provider fallback. Prints only a stable status code.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://api.meta.ai/v1'
DOCUMENTED_CANDIDATE = 'muse-spark-1.3'  # Not a claim of account entitlement.
EXPECTED = {'check': 'meta-access-ok'}
SCHEMA = {'type': 'object', 'properties': {'check': {'type': 'string', 'enum': ['meta-access-ok']}},
          'required': ['check'], 'additionalProperties': False}
SOURCES = ['https://dev.meta.ai/docs/overview',
           'https://dev.meta.ai/docs/api-reference/models/list-models',
           'https://dev.meta.ai/docs/structured-output',
           'https://dev.meta.ai/docs/api-reference/chat-completions/schemas']


class ProbeBlocked(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeBlocked('UNEXPECTED_REDIRECT')


def configuration():
    values = {}
    path = ROOT / '.local/meta.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key.strip() in ('MODEL_API_KEY', 'META_MODEL_ID'):
                values[key.strip()] = value.strip().strip('\"\'')
    for key in ('MODEL_API_KEY', 'META_MODEL_ID'):
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def validate_completion(response):
    try:
        choice = response['choices'][0]
        if choice['finish_reason'] != 'stop' or choice['message'].get('refusal'):
            raise ProbeBlocked('INCOMPLETE_OR_REFUSED_OUTPUT')
        if json.loads(choice['message']['content']) != EXPECTED:
            raise ProbeBlocked('STRUCTURED_OUTPUT_INVALID')
        usage = response['usage']
        names = ('prompt_tokens', 'completion_tokens', 'total_tokens')
        if any(type(usage.get(k)) is not int or usage[k] < 0 for k in names):
            raise ProbeBlocked('USAGE_REPORTING_INVALID')
        if usage['prompt_tokens'] == 0 or usage['completion_tokens'] == 0 or usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']:
            raise ProbeBlocked('USAGE_REPORTING_INVALID')
        if not isinstance(response['model'], str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,120}', response['model']):
            raise ProbeBlocked('RESPONSE_MODEL_INVALID')
        return {k: usage[k] for k in names}
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProbeBlocked('RESPONSE_CONTRACT_INVALID') from None


def exchange(opener, key, method, path, body, evidence, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProbeBlocked('TOTAL_DEADLINE_EXCEEDED')
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=payload, method=method,
                                     headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    attempt = {'method': method, 'endpoint': BASE + path}
    evidence['requests'].append(attempt)
    started = time.monotonic()
    try:
        with opener.open(request, timeout=min(20, remaining)) as response:
            attempt['http_status'] = response.status
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ProbeBlocked('RESPONSE_TOO_LARGE')
            if time.monotonic() > deadline:
                raise ProbeBlocked('TOTAL_DEADLINE_EXCEEDED')
            return json.loads(raw)
    except urllib.error.HTTPError as failure:
        attempt['http_status'] = failure.code
        # Do not read/store provider errors, headers or exception strings.
        raise ProbeBlocked('META_HTTP_' + str(failure.code)) from None
    except (TimeoutError, urllib.error.URLError):
        raise ProbeBlocked('META_NETWORK_OR_TIMEOUT') from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProbeBlocked('RESPONSE_NOT_JSON') from None
    finally:
        attempt['latency_ms'] = round((time.monotonic() - started) * 1000)


def verify(values):
    phase2 = ROOT / 'docs/verification/phase2-results.json'
    evidence = {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'status': 'BLOCKED', 'authenticated_inference_verified': False,
                'documented_base_url': BASE, 'documentation_sources': SOURCES,
                'documented_candidate_model': DOCUMENTED_CANDIDATE,
                'account_model': None, 'response_model': None,
                'phase2_evidence_sha256': hashlib.sha256(phase2.read_bytes()).hexdigest(),
                'requests': [], 'synthetic_input_only': True, 'credentials_recorded': False}
    key = values.get('MODEL_API_KEY', '').strip()
    try:
        if not key:
            raise ProbeBlocked('MISSING_MODEL_API_KEY')
        if any(c.isspace() for c in key):
            raise ProbeBlocked('INVALID_CREDENTIAL_CONFIGURATION')
        opener = urllib.request.build_opener(NoRedirect())
        deadline = time.monotonic() + 45
        catalog = exchange(opener, key, 'GET', '/models', None, evidence, deadline)
        ids = {item['id'] for item in catalog['data'] if isinstance(item, dict) and isinstance(item.get('id'), str)}
        evidence['available_model_ids'] = sorted(model for model in ids if re.fullmatch(r'[a-zA-Z0-9_.:-]{1,120}', model))
        selected = values.get('META_MODEL_ID', DOCUMENTED_CANDIDATE)
        if selected not in ids or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,120}', selected):
            raise ProbeBlocked('MODEL_NOT_AVAILABLE_OR_SELECTION_REQUIRED')
        evidence['account_model'] = selected
        payload = {'model': selected, 'messages': [
            {'role': 'system', 'content': 'Return the requested synthetic API connectivity check as JSON.'},
            {'role': 'user', 'content': 'Set check to meta-access-ok.'}],
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'MetaAccessCheck', 'strict': True, 'schema': SCHEMA}}}
        evidence['request_contract'] = payload
        response = exchange(opener, key, 'POST', '/chat/completions', payload, evidence, deadline)
        evidence['usage'] = validate_completion(response)
        evidence['response_model'] = response['model']
        evidence['validated_synthetic_output'] = EXPECTED
        evidence['authenticated_inference_verified'] = True
        evidence['status'] = 'PASS'
    except ProbeBlocked as failure:
        evidence['blocker'] = failure.code
    except Exception:
        # Fail closed: never stringify a credential-bearing request or unknown provider response.
        evidence['blocker'] = 'UNEXPECTED_PREFLIGHT_FAILURE'
    return evidence


def main():
    values = configuration()
    evidence = verify(values)
    text = json.dumps(evidence, indent=2) + '\n'
    key = values.get('MODEL_API_KEY')
    if key:
        text = text.replace(key, '[REDACTED]')
    directory = ROOT / 'docs/verification'
    directory.mkdir(parents=True, exist_ok=True)
    evidence_path = directory / 'meta-api-preflight.json'
    if evidence_path.exists():
        previous = evidence_path.read_bytes()
        history = directory / 'meta-api-attempts'
        history.mkdir(exist_ok=True)
        # Content-addressed history preserves prior results without credential-bearing filenames.
        (history / (hashlib.sha256(previous).hexdigest() + '.json')).write_bytes(previous)
    evidence_path.write_text(text)
    print('Meta preflight: ' + evidence['status'] + (' (' + evidence['blocker'] + ')' if 'blocker' in evidence else ''))
    return 0 if evidence['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
