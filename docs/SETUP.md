# Local installation and configuration

## Prerequisites

The recommended complete runtime is Docker with Compose and Linux/amd64 images.
The verified ONNX/native stack runs in that environment; host-native inference on
the Intel Mac dependency combination is not supported. Java 21 is needed for host
builds, Python 3.11+ for operator tools, and Node 22/npm 11.8.0 for frontend development.
The Maven wrapper pins Maven 3.9.16.

The backend and frontend are separate checkouts. A local directory can be named
`ai-policy-investigator-frontend`; its GitHub repository and GHCR package actually
use **ai-policy-invetigator-frontend**. Do not infer a remote name from a local path.

## Private environment

For a new backend checkout:

```sh
cp .env.example .env
chmod 600 .env
```

Use your editor to replace placeholders with private local database passwords, a
JWT secret of at least 32 UTF-8 bytes, and your Meta API key. Do not publish this file
or paste its values into logs. Existing `.env` files should be preserved.

Optionally, `python3 scripts/init_local.py` generates fresh database/JWT values in
ignored `.local/runtime.env` and refuses overwrite. If using Compose with root `.env`,
copy those generated values privately into the corresponding entries there; the
helper does not populate root `.env` or create Meta credentials.

| Variable | Purpose |
|---|---|
| MODEL_API_KEY | Meta bearer credential; real inference requires account access |
| JWT_SECRET | Private JWT signing key, at least 32 UTF-8 bytes |
| POSTGRES_ADMIN_PASSWORD | Dedicated PostgreSQL administrator password |
| OWNER_DB_PASSWORD | Migration-owner password |
| APP_DB_PASSWORD | Runtime-role password |
| META_MODEL_ID | Verified default muse-spark-1.3; verify availability before changing |
| META_TIMEOUT_SECONDS / META_MAX_RETRIES / META_CONCURRENCY | Bounded provider timeout, retry and concurrency controls |
| META_INVESTIGATION_BUDGET_SECONDS | Persisted total investigation deadline |
| DB_URL / APP_DB_USERNAME / OWNER_DB_USERNAME | JDBC connection and separate roles for host execution |
| EMBEDDING_MODEL_URI / EMBEDDING_TOKENIZER_URI / EMBEDDING_REVISION | Host artifact paths and exact fingerprint; Compose supplies container paths |

The application has one configuration file, `src/main/resources/application.properties`.
Other worker, upload, pool, issuer/audience and local documentation switches are listed
in `.env.example` and that file. Production security invariants are not tuning knobs.

The existing `me.paulschwarz:springboot4-dotenv:5.1.0` integration is opt-in.
`SPRINGDOTENV_ENABLED=true` must be set in the process to enable direct Java/Maven
local loading; a switch inside a disabled `.env` cannot enable its own loading.
Real process variables take precedence, including intentionally empty values.
`scripts/run_local.py` enables dotenv by default unless the process explicitly disables
it, and treats ignored legacy local files as fallbacks. Production disables dotenv
and injects runtime environment values.

## Docker startup

From the backend root:

```sh
docker compose --env-file .env --profile app up --build -d --wait
```

This starts dedicated PostgreSQL 16/pgvector, the short-lived pinned model initializer
and Spring Boot. The API is at http://127.0.0.1:18080; the local PostgreSQL port is
127.0.0.1:5546. Original PDFs and investigation records live in the project database.
Do not reuse another project's database or credentials.

The initializer downloads the exact model/tokenizer revision, checks sizes and SHA256,
and caches the artifacts in the persistent embedding_models volume. Spring Boot mounts
it read-only at /models. A separate native_cache volume stores runtime dependencies.
Cold initialization needs network access; subsequent starts reuse verified caches.
The model revision and 384 dimensions are fixed in [model provenance](provenance/embedding-model.json).

For the local Swagger UI, explicitly add the existing local overlay:

```sh
docker compose --env-file .env -f compose.yaml -f compose.local.yaml --profile app up -d --wait
```

Open http://127.0.0.1:18080/swagger-ui.html; JSON is /v3/api-docs. API calls still
require JWT/current permissions. Swagger does not persist authorization. Viewing the
specification does not trigger Meta; executing an investigation can incur usage.
Production denies documentation routes independently of the enable flags.

## Frontend and login

From the separate frontend checkout:

```sh
npm ci
npm start
```

Open http://127.0.0.1:4200. Its development proxy targets the local backend. Alternatively,
`docker compose up --build -d --wait` in that checkout serves the existing frontend
at http://127.0.0.1:18081 using its same-origin /api proxy.

There is no public registration or default password. Follow [the demo guide](DEMO.md)
to provision a local-only normal account, export synthetic PDFs and exercise the complete
workflow. Production uses the separate explicit [initial account procedure](DEPLOYMENT.md).

## Host builds and verification

```sh
./mvnw -B -Pdatabase-tests verify
python3 -B -m unittest discover -s scripts/tests -v
# Include the real local embedding runtime for a runnable JAR:
./mvnw -B -Pneural-embeddings,database-tests verify
python3 scripts/fetch_embeddings.py
python3 scripts/run_local.py
```

Database tests require Docker and use isolated synthetic fixtures. Ordinary tests do
not call Meta or establish real-model accuracy. Host inference still requires a supported
native platform; use Docker for the verified end-to-end demo.

An intentional real synthetic API preflight is available through the Spring wrapper:

```sh
SPRINGDOTENV_ENABLED=true java -jar target/ai-policy-investigator-0.1.0-SNAPSHOT.jar --verify-meta-access
```

It requires a populated private environment and real account entitlement. It performs
model discovery and structured inference, records sanitized evidence and never substitutes
another provider. The wrapper needs host Python/repository scripts; the production
JRE image does not contain that operator tooling. See [evaluation](EVALUATION.md).
