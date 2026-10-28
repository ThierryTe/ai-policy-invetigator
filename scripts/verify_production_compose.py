#!/usr/bin/env python3
"""Validate resolved production topology without contacting Docker Engine or deploying.

Uses synthetic interpolation values and /dev/null, never the private production env file.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROXY = 'nginx-proxy-manager_default'
APPLICATION = 'ai-policy-investigator_application'
ALIAS = 'ai-policy-investigator-web'


def require(condition, code):
    if not condition:
        raise ValueError(code)


def validate(backend, frontend):
    back = backend['services']
    front = frontend['services']['frontend']
    require(set(back) == {'backend', 'postgres', 'model-init'}, 'UNEXPECTED_BACKEND_SERVICES')
    require(set(frontend['services']) == {'frontend'}, 'UNEXPECTED_FRONTEND_SERVICES')
    require(all(not s.get('ports') for s in [*back.values(), front]), 'PUBLISHED_PORT')
    require(set(back['backend']['networks']) == {'application', 'database', 'default'}, 'BACKEND_NETWORKS')
    require(set(back['postgres']['networks']) == {'database'}, 'DATABASE_NETWORKS')
    require(set(back['model-init']['networks']) == {'default'}, 'INITIALIZER_NETWORKS')
    require(set(front['networks']) == {'application', 'proxy'}, 'FRONTEND_NETWORKS')
    networks = backend['networks']
    require(networks['application'].get('internal') is True, 'APPLICATION_NOT_INTERNAL')
    require(networks['database'].get('internal') is True, 'DATABASE_NOT_INTERNAL')
    require(not networks['default'].get('internal'), 'MISSING_PROVIDER_DOWNLOAD_EGRESS')
    require(networks['application']['name'] == APPLICATION, 'APPLICATION_NETWORK_NAME')
    require(all(n['name'] != PROXY for n in networks.values()), 'BACKEND_ON_PROXY_NETWORK')
    for name, expected in [('application', APPLICATION), ('proxy', PROXY)]:
        n = frontend['networks'][name]
        require(n.get('external') is True and n['name'] == expected, 'FRONTEND_EXTERNAL_NETWORK')
    require(ALIAS in front['networks']['proxy'].get('aliases', []), 'MISSING_UNIQUE_NPM_ALIAS')
    require(front['environment'] == {'BACKEND_UPSTREAM': 'http://backend.' + APPLICATION + ':8080'}, 'FRONTEND_ENVIRONMENT')
    env = back['backend']['environment']
    require(env['APP_ENVIRONMENT'] == 'production' and env['SPRINGDOTENV_ENABLED'] == 'false', 'PRODUCTION_MODE')
    require(env['LOCAL_OPENAPI_ENABLED'] == env['LOCAL_SWAGGER_UI_ENABLED'] == 'false', 'PUBLIC_DOCUMENTATION')
    require(env['DB_URL'] == 'jdbc:postgresql://postgres:5432/investigator', 'DATABASE_SERVICE_NAME')
    require(env['EMBEDDING_MODEL_URI'] == 'file:/models/model.onnx'
            and env['EMBEDDING_TOKENIZER_URI'] == 'file:/models/tokenizer.json', 'MODEL_PATHS')
    model_mount = next(v for v in back['backend']['volumes'] if v['target'] == '/models')
    require(model_mount.get('read_only') is True, 'WRITABLE_BACKEND_MODEL')
    require(backend['volumes']['investigator_data']['name'] == 'ai-policy-investigator_investigator_data', 'DATABASE_VOLUME_CHANGED')
    require(back['backend']['depends_on']['model-init']['condition'] == 'service_completed_successfully', 'MODEL_INIT_GATE')
    return {'result': 'PASS', 'publishedPorts': [], 'npmHostname': ALIAS, 'npmPort': 8080,
            'backendServiceHostname': 'backend.' + APPLICATION,
            'sharedProxyNetwork': PROXY, 'internalApplicationNetwork': APPLICATION,
            'databaseNetwork': networks['database']['name'], 'onlyFrontendOnProxyNetwork': True,
            'backendAndDatabaseHaveNoPublishedPorts': True, 'dockerEngineContacted': False,
            'networksCreated': False, 'containersDeployed': False}


def resolved(project, directory, files):
    env = os.environ.copy()
    # No real credentials are needed to resolve Compose. Never print resolved environments.
    env.update({k: 'synthetic-configuration-validation-only' for k in
                ['POSTGRES_ADMIN_PASSWORD', 'APP_DB_PASSWORD', 'OWNER_DB_PASSWORD', 'JWT_SECRET', 'MODEL_API_KEY']})
    args = ['docker', 'compose', '--project-directory', str(directory), '--env-file', '/dev/null', '-p', project]
    for file in files:
        args += ['-f', str(file)]
    result = subprocess.run(args + ['--profile', 'app', 'config', '--format', 'json'],
                            capture_output=True, text=True, env=env, timeout=30)
    require(result.returncode == 0, 'COMPOSE_CONFIGURATION_FAILED')
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend-directory', type=Path, required=True)
    options = parser.parse_args()
    try:
        front = options.frontend_directory.resolve()
        result = validate(
            resolved('ai-policy-investigator', ROOT, [ROOT / 'compose.yaml', ROOT / 'compose.production.yaml']),
            resolved('ai-policy-investigator-ui', front,
                     [front / 'compose.yaml', ROOT / 'deploy/frontend/compose.production.yaml']))
    except (ValueError, KeyError, OSError, StopIteration, subprocess.TimeoutExpired):
        print('Production Compose verification failed; check files and resolved topology privately.', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
