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
| META_MAX_COMPLETION_TOKENS | Per-call generation budget, including reasoning; default 4096, application bounds 4096–8192 |
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

## Meta generation budget and diagnostics

`META_MAX_COMPLETION_TOKENS` maps to `meta.max-completion-tokens` and the Meta
Chat Completions `max_completion_tokens` request field. The backend refuses startup
for non-integers, empty values, or values outside 4096–8192. These are conservative
application bounds, not a published Meta model output maximum. The default remains
4096; raising it is an explicit operator choice. Compose forwards the variable to
the backend through both the production and image-only release overlays. An unset
or empty Compose interpolation value uses 4096; a directly injected empty Spring
property is invalid.

The [official model catalog](https://dev.meta.ai/docs/models) lists a 1,048,576-token
context window for `muse-spark-1.3`. That is not a separately guaranteed output limit.
The [Chat Completions guide](https://dev.meta.ai/docs/protocols/chat-completions)
describes the generation limit as model-dependent, and the
[request schema](https://dev.meta.ai/docs/api-reference/chat-completions/schemas)
states that it includes visible output and reasoning tokens. The public references
checked on 2026-10-30 do not publish a numeric maximum for this model's
`max_completion_tokens`. Do not infer support for 8192 from its context window or
from a successful local fixture test. Confirm that value with Meta before using
`META_MAX_COMPLETION_TOKENS=8192` for a first controlled investigation.

After confirmation, set that single non-secret variable in the protected runtime
configuration used by the existing production release workflow. Release the updated
backend image and Compose configuration together through that workflow; a restart
alone does not inject changed environment values into an existing container. Verify
the selected value with `printenv META_MAX_COMPLETION_TOKENS` inside the backend,
then create a new investigation. A terminal failed investigation is not automatically
requeued; use a new investigation request/idempotency key. Keep the existing timeout,
retry, concurrency, and total investigation budgets for this first trial.

For HTTP 200 responses with valid usage counters, `meta_provider_event` logs contain
only the investigation UUID, per-call attempt number, normalized `finish_reason`,
refusal-presence boolean, prompt/completion/total token counters, configured generation
budget, and latency. The finish-reason vocabulary is `stop`, `length`, `content_filter`,
`tool_calls`, `function_call`, `missing`, or `other`; unrecognized provider text is never
copied into logs. The refusal text, response body, prompts, source text, credentials,
and lease tokens are never included. Logging occurs before content parsing and schema
validation, so `stop` does not mean that a response passed the later validations.
Malformed envelopes or invalid usage counters fail before this diagnostic event.

`reasoning_effort=low`, strict JSON Schema, citation/coverage validation, and
`FAILED`/`PARTIAL`/`COMPLETED` semantics remain unchanged. `INCOMPLETE_PROVIDER_OUTPUT`
is still terminal for the provider call and is not automatically retried. A larger
generation budget does not guarantee a complete response within the existing timeout.

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
