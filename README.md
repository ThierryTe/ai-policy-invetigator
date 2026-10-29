# AI Policy Investigator

Built for the Meta Global AI Developer Hackathon 2026.

AI Policy Investigator helps compliance analysts assess a policy change against
related enterprise procedures. It extracts requirements, compares the old and new
policy, detects potential conflicts and presents exact source evidence for human
review. It is an investigation workflow rather than a generic RAG chatbot.

The Angular application lives in the separate
[ai-policy-invetigator-frontend repository](https://github.com/ThierryTe/ai-policy-invetigator-frontend).
The backend repository is [ThierryTe/ai-policy-invetigator](https://github.com/ThierryTe/ai-policy-invetigator).
Use the published repository/package names as shown; local checkout directories may differ.

## What the application does

1. Upload a baseline policy, an immutable replacement version and procedure PDFs.
2. Index page-aware source text using local ONNX embeddings and PostgreSQL/pgvector.
3. Explicitly authorize external processing for the selected documents.
4. Run a durable asynchronous investigation and poll its persisted progress.
5. Inspect changed requirements, potential conflicts, source quotations and an impact graph.
6. Confirm, dismiss or annotate a finding while preserving its original AI result.

Findings are CONTRADICTION, MISSING_REQUIREMENT, AMBIGUITY or NO_CONFLICT. The system
preserves unknown fields and distinguishes incomplete processing from a non-conflict.
Actionable findings require human review; suggested actions do not modify policies
or grant access automatically.

The MVP compares one to four explicitly selected procedure versions. It does not
claim automatic discovery of every affected procedure across an enterprise. Original
PDFs, versions, page provenance, jobs, findings and review history remain persisted.

## Real demonstration

The recorded synthetic scenario contrasts **training before sensitive-system access**
with **day-one access and training within 30 days**, plus a compatible access-gated
procedure. It used real Meta `muse-spark-1.3` inference and persisted, verified citations.
Human review is separate from the AI result: Confirm, Dismiss and Add Note preserve
original classification/evidence and append reviewer decisions rather than replacing them.

View the existing frontend captures:
[desktop investigation](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/desktop-fitted-investigation.png),
[mobile investigation](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/mobile-fitted-investigation.png),
and [source PDF viewer](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/pdf-real-source.png).
These show synthetic documents and actual model/review data; they do not establish
public-site availability or general model accuracy. See [the reproducible demo](docs/DEMO.md).

## Architecture

| Component | Implementation |
|---|---|
| Backend | Java 21, Spring Boot 4.1.1, Spring AI 2.0.1, Maven wrapper 3.9.16 |
| Storage | PostgreSQL 16, pgvector 0.8.0, parameterized JDBC and Spring Data JPA |
| Security | Spring Security/JWT, current memberships/grants, forced SQL row-level security |
| PDF ingestion | PDFBox, immutable bytes/versions, page-aware chunks and durable workers |
| Embeddings | Local all-MiniLM-L6-v2 ONNX, pinned artifacts, 384 dimensions |
| Reasoning | Meta Muse (`muse-spark-1.3`) behind PolicyReasoningProvider; independent of embeddings |
| Frontend | Angular 21 standalone components, signals, OnPush and HttpClient |
| Deployment | Docker/Compose, Nginx frontend, existing Nginx Proxy Manager, GitHub Actions |

Access is checked at database retrieval and before every provider request, including
retries. Findings and evidence require current access to every contributing source.
Only explicitly consented documents can be sent to Meta. Schema and citation validation
are enforced by the server; citation correctness is not proof that AI reasoning is
correct. JWTs stay in frontend memory rather than localStorage.

Read the [technical architecture](docs/ARCHITECTURE.md) for the data model, authorization,
provider boundary, durability and processing limits.

## Run the local demonstration

Use Docker/Compose with Linux/amd64 images for the verified native embedding runtime.
Python 3.11+ supports operator tools; Java 21 is needed for host builds and Node 22/npm 11.8.0
for frontend development.

For a fresh backend checkout:

```sh
cp .env.example .env
chmod 600 .env
# Populate private values in your editor; preserve any existing .env instead.
docker compose --env-file .env --profile app up --build -d --wait
```

The local backend is http://127.0.0.1:18080. The first start downloads the exact pinned
ONNX model/tokenizer into a persistent volume and verifies their sizes/hashes; Spring
Boot mounts them read-only. Subsequent starts reuse the verified cache. No host model
installation is required. See [installation and configuration](docs/SETUP.md).

There is no default password or public registration. The [demo guide](docs/DEMO.md)
provisions the explicitly enabled local account demo@policy-investigator.local using
a private DEMO_PASSWORD, exports synthetic PDFs, and walks through login, upload,
investigation, graph, source PDFs and human review. It never bypasses JWT or authorization.
From the separate frontend checkout, npm ci/npm start serves http://127.0.0.1:4200;
its Docker option serves http://127.0.0.1:18081.

The principal scenario contrasts **training before sensitive-system access** with
**day-one access and training within 30 days**. A compatible access-gated procedure is
included as a negative control. The demo uses real Meta inference and persisted citations;
account access and a valid private MODEL_API_KEY are required.

## API and local OpenAPI

The main API flow is login → authorized upload/version history → ingestion polling →
external-processing consent → investigation polling → requirements/findings/evidence →
graph and append-only reviews. Exact fields, status transitions and errors are documented:

- [Authentication, documents, versions and evidence](docs/api/phase2.md).
- [Consent and investigations](docs/api/phase3.md).
- [Dashboard graph and human review](docs/api/phase4.md).

Those filenames remain stable for existing links; the contents describe current APIs.

OpenAPI/Swagger is disabled by default and denied in production. For an explicit local
opt-in, add compose.local.yaml as described in [setup](docs/SETUP.md), then open
http://127.0.0.1:18080/swagger-ui.html. Documentation uses Springdoc 3.2.0 and JWT bearer
metadata; API calls still enforce authentication and current permissions. Loading the
specification does not call Meta. API DTOs use Java records; targeted Lombok 1.18.46
constructor injection does not change domain/security behavior or add @Data to entities.

## Evaluation and limitations

A recorded real Muse investigation identified the training/access contradiction and
the compatible control with verified citations. The ten-case synthetic evaluation
matched 6/10 expected outcomes with four processing errors. A separate four-case exception
retry matched 3/4 and included one false positive; it does not replace the initial errors.
Across those two runs: 31 calls, 38,359 prompt / 68,141 completion tokens, 296,572 ms
summed metered provider latency and 119/119 verified source/quote instances. Citation
matching does not establish semantic correctness. These small runs do not establish
general accuracy, and errors must not be presented as NO_CONFLICT.

[Evaluation and reproducibility](docs/EVALUATION.md) documents datasets, exact metrics,
provider usage/latency, separate retries and retained sanitized evidence. It includes
both unsuccessful outcomes and successful findings. Golden datasets are under evaluation/.

Deterministic regression checks:

```sh
python3 -B -m unittest discover -s scripts/tests -v
./mvnw -B -Pdatabase-tests verify
# Include native embedding dependencies for a runnable JAR:
./mvnw -B -Pneural-embeddings,database-tests verify
```

Database tests require Docker and exercise isolated synthetic PostgreSQL fixtures.
Normal CI does not call real Meta or download ONNX weights. Real evaluation scripts
create local fixture data and can incur provider costs; do not run them on a shared
production database.

## Production deployment and CI/CD

On main, the configured workflow chains successful CI, immutable image publication
and SSH/Compose deployment.
Develop and PR runs validate only. Shared backend workflows serve both repositories,
using GitHub Environment **prod** in the caller. Images are downloaded/verified on the
runner and transferred through the configured SSH account, avoiding a GHCR pull
dependency on the VPS. Local images deploy with no build/pull and preserve PostgreSQL/ONNX volumes.

The workflow keeps the existing VPS_HOST, VPS_USERNAME, VPS_SSH_KEY, VPS_PORT and
VPS_DEPLOY_PATH secrets. Set the public prod variable VPS_HOST_KEY in both repositories
to the independently verified Ed25519 public host key of the VPS. The runner builds an
isolated known_hosts file and enforces StrictHostKeyChecking=yes for SSH/SCP; no additional
SSH secret or unverified key scan is needed. Missing or malformed pins fail before connecting.
See [SSH host identity setup](docs/PRODUCTION_PIPELINE.md#current-ssh-configuration).
The local startup commands above are separate from this production pipeline; no
successful hosted run or public-site deployment is established here.

- [Production pipeline and one-time GitHub configuration](docs/PRODUCTION_PIPELINE.md).
- [Network topology, initial administrator, backup and restore](docs/DEPLOYMENT.md).

Only the Angular/Nginx container joins the existing shared proxy network. Backend and
PostgreSQL remain private, with no production host ports. Swagger and dotenv remain
disabled in production. Live token/package access, VPS capacity, NPM/TLS routing and
health must be verified during actual deployment; local checks do not certify them.

## Reuse and contributions

Selected infrastructure derives from
[AI Compliance Copilot](https://github.com/ThierryTe/spring-ai-rag). The four exact
imports, source commits/hashes and adaptations remain in the
[reuse allowlist](docs/provenance/allowlist.json) and
[design adaptations](docs/provenance/adaptations.json).
[Pre-existing capabilities](docs/provenance/PRE_EXISTING.md) and
[Investigator contributions](docs/provenance/HACKATHON_CONTRIBUTIONS.md) distinguish
prior work from this project's policy domain, secure processing, investigations,
evidence verification, review, evaluation and deployment additions. See also
[third-party notices](THIRD_PARTY_NOTICES.md) and
[model provenance](docs/provenance/embedding-model.json).

Keep .env/.local files, credentials, SSH keys, model weights, database dumps and runtime
logs outside commits/build contexts. Public examples use variable names and placeholders,
not credentials. The [documentation index](docs/README.md) links the maintained guides;
development plans and intermediate audit trails are not part of the public manual.
