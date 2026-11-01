# Testing

Use this guide for the judge walkthrough and a dedicated local reproduction. Historical
evidence is linked below; these instructions are not a report of a new execution.
**Remote Work remains unvalidated until a complete investigation succeeds.**

## Judge walkthrough

Use the completed-investigation URL supplied privately with your individual account.
There is no default password or public registration. Reading an existing result does
not start new Meta reasoning. The configured site is
[ai-policy.tewendelabs.com](https://ai-policy.tewendelabs.com); current availability
and the actual judge account must be checked separately.

1. Sign in and open the supplied investigation link. The recorded training/access
   scenario changes training from within 30 days after access to **before access**.
2. Select the contradiction. Read the explanation and suggested action; compare the
   policy and procedure quotations in Evidence, then open the original PDF pages.
3. Inspect the compatible procedure, which blocks access until training is complete.
   Use Focus finding, Expand, Fit to view or 100% to explore the persisted graph.
4. Inspect existing History. Shared-source judge access is read-only: Confirm, Dismiss,
   Add note, source edits and consent changes require the appropriate owning-department
   permission. A presenter can demonstrate reviews in an authorized private scenario.

An active judge can upload in their private department and, under V8 permissions and
quotas, analyze authorized shared sources. Analysis does not grant source WRITE access.
Some upload/version buttons may still be visible for shared documents; the server rejects
unauthorized writes. Operator setup remains in [Judge access](JUDGE_DEMO.md).

If live inference is slow, return to a separate completed result and identify it as an
earlier run. If the site is unavailable, use the historical screenshots linked from the
[README](../README.md#demo-and-video). A video is not yet available. Evidence coverage
means source coverage, not AI accuracy. Preserve the investigation URL: the recent list
contains only known session IDs, not server history. Reload can restore an unexpired
tab session after identity verification; 401 requires sign-in, while 403/404 requires
checking account/source permissions rather than bypassing them.

## Local setup

Use a dedicated local database with synthetic documents. Real investigations send
consented source excerpts to Meta and consume account quota. Do not run fixture or
evaluation tools against a shared production database.

Prerequisites: Docker/Compose with Linux/amd64 support, Python 3.11+, and separate
backend/frontend checkouts. Frontend development uses Node 22/npm 11.8.0; host backend
builds need Java 21 and the Maven wrapper (3.9.16). Docker is the verified native embedding
runtime; host inference with the inspected Intel Mac dependency combination is unsupported.

From a fresh backend checkout only:

```sh
cp .env.example .env
chmod 600 .env
```

Preserve any existing `.env` and database credentials. In your editor, fill the three
database passwords, a private JWT secret of at least 32 UTF-8 bytes and `MODEL_API_KEY`.
The exact settings are in [.env.example](../.env.example). Keep the verified
`META_MODEL_ID=muse-spark-1.3` and existing provider budgets unless deliberately reviewed.
The generation default is 4096 tokens; application bounds do not establish Meta support
for a larger value. No Meta key or database credential belongs in the frontend.

```sh
docker compose --env-file .env --profile app up --build -d --wait
```

The API is `http://127.0.0.1:18080`; PostgreSQL is bound to `127.0.0.1:5546` locally.
The first start downloads and verifies pinned ONNX/tokenizer artifacts into persistent
volumes; later starts reuse them. The backend mounts the model files read-only. A cold
start needs network access. Startup does not create a demo user.

From the separate frontend checkout:

```sh
npm ci
npm start
```

Open `http://127.0.0.1:4200`; the existing development proxy targets the backend.
Alternatively, frontend `docker compose up --build -d --wait` serves
`http://127.0.0.1:18081` through its existing same-origin API proxy.

For optional local Swagger, use the existing overlay from the backend checkout:

```sh
docker compose --env-file .env -f compose.yaml -f compose.local.yaml --profile app up -d --wait
```

The UI is `http://127.0.0.1:18080/swagger-ui.html`; the specification is `/v3/api-docs`.
API permissions still apply. Loading the specification does not call Meta; running an
investigation does. Production independently denies these documentation routes.

## Local account and existing fixtures

Create a private, ignored `.local/demo.env` in the backend containing `DEMO_PASSWORD`
with a private value of 16–72 UTF-8 bytes, without control characters. Restrict its file
permissions to the owner. Load it and explicitly provision the local account:

```sh
set -a
. .local/demo.env
set +a
DEMO_USER_ENABLED=true APP_ENVIRONMENT=local python3 scripts/setup_demo.py
unset DEMO_PASSWORD
```

The script requires both flags in its process environment, uses the existing root
`.env` database configuration and creates `demo@policy-investigator.local` with ADMIN
memberships in its isolated Security and HR departments. It exports four synthetic
PDFs to `.local/demo/pdfs`; it does not upload, consent or invoke Meta. No password is
printed. Repeating the seed preserves its managed identities; changing the private
password rotates it, and reseeding reactivates the managed account/memberships.

| Exported PDF | Effective date | Content |
|---|---|---|
| `01-security-baseline.pdf` | 2026-10-26 | Training within 30 days after access |
| `02-security-replacement.pdf` | 2026-10-27 | Training before sensitive-system access |
| `03-hr-conflicting.pdf` | 2026-10-26 | Day-one access; training within 30 days |
| `04-hr-compatible.pdf` | 2026-10-26 | Access blocked until training completes |

Sign in with this account and its private password. Upload the baseline as a Security
`POLICY`, then add the replacement using **New version** on that same policy. Upload
the two HR documents as separate `PROCEDURE` documents. Wait until every version is
`INDEXED`, and explicitly allow external processing on all three documents.

Run an investigation with policy versions 1/2, both procedure versions and analysis
date **2026-10-27 or later**. Expect to inspect a potential contradiction and a compatible
control, as found in the historical runs; fresh model output can differ. Check actual
state, explanations, quotes and pages. Confirm, annotate and dismiss a finding using
the authorized analyst account; verify History retains all actions and the original AI
payload is unchanged. Check desktop/mobile graph controls, PDF viewing and sign-out.

Use distinct document titles when deliberately repeating uploads. Original versions
and results remain persisted. Unsetting the seed flag does not disable a created user;
to disable only this local account, an authorized local operator can use:

```sql
UPDATE app_users SET active=false
WHERE id='d3000000-0000-4000-8000-000000000004'
  AND email='demo@policy-investigator.local';
```

This retains documents and review history. Production accounts use the separate
[initial login](FIRST_LOGIN.md) and [judge provisioning](JUDGE_DEMO.md) procedures.

## Remote Work scenario

**Status: not validated.** Neither the three input PDFs nor evidence of a successful
complete Remote Work investigation was found in the inspected repositories. The fixture
exporter and existing browser workflow use the training/access scenario above; renaming
their files would not test Remote Work. No expected classifications or metrics are asserted.

Once the exact synthetic inputs are supplied, follow this manual procedure:

1. Record filenames, effective dates and SHA-256 hashes for **Remote Work Policy V1**,
   **Remote Work Policy V2** and **Remote Work Management Procedure**. Verify each PDF
   contains extractable text. Record the changed clauses and procedure passages for
   human comparison before inference; do not infer their contents from the titles.
2. In an authorized private department, upload V1 as `POLICY`. Add V2 as the immediate
   next version of that same policy. Upload the management document as `PROCEDURE`.
   Record actual policy/version IDs and confirm all three versions are `INDEXED`.
3. Explicitly allow external processing for both documents, using an ADMIN in each
   owning department. Select V1 as baseline, V2 as replacement and the management
   procedure version; choose an analysis date on or after all effective dates.
4. Start one investigation. Save its actual URL/UUID, state, safe error if any, model
   metadata and reported usage. Poll to a terminal state. `PARTIAL`, `FAILED`, timeout,
   missing assessment or incomplete coverage leave this scenario **unvalidated**.
5. Require state `COMPLETED` and `payload.complete=true`, then inspect extracted
   requirements, aligned changes and the actual procedure assessments. Resolve every
   published citation to the stored excerpt, document version and original PDF page.
   Check graph consistency and review history using the authorized private account.
6. Retain a sanitized report from that real run with input hashes, version IDs,
   investigation ID, timestamp, actual classifications, usage and checks performed.
   Only then update the scenario status. A completed run establishes this workflow's
   completion; correct interpretation still needs human assessment.

Do not replace historical training/access reports with Remote Work output. Keep each
attempt identifiable, including unsuccessful attempts. Never use a fixed KPI count or
present a previous investigation as the result of the current request.

## Regression and browser checks

These commands are instructions for a future local test run, not checks executed by
this documentation pass. Backend deterministic tests do not call real Meta:

```sh
python3 -B -m unittest discover -s scripts/tests -v
./mvnw -B -Pdatabase-tests verify
```

Database tests require Docker and isolated synthetic PostgreSQL fixtures. To build a
runnable backend with native embedding dependencies, use
`./mvnw -B -Pneural-embeddings,database-tests verify`. Maven can replace files under
`target/`; preserve any qualified JAR/reports before rebuilding. Optional host model
setup uses `scripts/fetch_embeddings.py` and `scripts/run_local.py`. Dotenv is opt-in for
direct Java/Maven (`SPRINGDOTENV_ENABLED=true`); the local launcher enables it unless
explicitly disabled. Production disables dotenv.

From the frontend checkout, run `npm test` and `npm run build`. The isolated authentication
browser regression uses mocked API responses and no Meta request; its commands and manual
follow-up remain in the [authentication guide](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/AUTHENTICATION.md).

For the optional **real** training/access browser workflow, the backend fixture helper
requires ignored `.local/runtime.env` with values matching the existing local database
and root `.env`. On a fresh installation, `scripts/init_local.py` can generate those
values before database creation; copy them privately into root `.env`. Do not regenerate
credentials for an existing volume. With the local frontend/backend running:

```sh
python3 scripts/prepare_browser_fixture.py --backend /absolute/path/to/backend
npx playwright install chromium
E2E_DATA_DIR="$PWD/.e2e-data" E2E_BASE_URL=http://127.0.0.1:4200 \
  E2E_REPORT_PATH="$PWD/.e2e-results/training-access.json" \
  npx playwright test e2e/workflow.spec.ts
```

Replace the backend path. This creates isolated synthetic accounts and performs real
uploads, consent, inference and reviews. It is not a Remote Work test. Do not reuse the
historical report's UUID with fresh fixture accounts: they belong to another organization.
The full test also writes committed screenshot paths; preserve/review those artifacts
before deliberate execution. `e2e/visual.spec.ts` reads `docs/browser-verification.json`
and writes historical report/screenshot paths, so it must not be chained to this separate
report without matching fixture ownership. Fixture `--cleanup` disables synthetic browser
accounts while preserving their immutable evidence.

## Recorded evaluation

All records below are historical synthetic runs, not production health checks or
Remote Work results. The small datasets do not estimate general accuracy.

The [Meta preflight](verification/meta-api-preflight.json) records authenticated model
discovery and structured inference with `muse-spark-1.3`; entitlement is account-specific.
The [training/access investigation](verification/phase3-demo.json) identified the
contradiction and compatible control described above, with checked source IDs/quotes,
permission revocation and cross-department denial. That run used five calls, 6,368 prompt
and 8,200 completion tokens; reported provider latency was 47,469 ms and elapsed time
48,732 ms. Two matching cases do not establish accuracy.

Golden inputs remain in [phase3-golden.json](../evaluation/phase3-golden.json) and
[phase4-golden.json](../evaluation/phase4-golden.json). The latter covers ten cases:
contradictions, compatible access gates, exceptions, scope differences, ambiguity,
missing requirements and insufficient evidence.

| Recorded run | [Initial full evaluation](verification/phase4-evaluation.json) | [Separate exception retry](verification/phase4-explicit-exception-evaluation.json) |
|---|---:|---:|
| Cases | 10 | 4 |
| Expected outcomes matched | 6 | 3 |
| Processing errors | 4 | 0 |
| Contradiction TP / FP / FN | 2 / 0 / 1 | 1 / 1 / 0 |
| Reported contradiction precision | 1.00 | 0.50 |
| Reported contradiction recall | 0.667 | 1.00 |
| Verified citation instances | 65 / 65 | 54 / 54 |
| Calls | 21 | 10 |
| Prompt / completion tokens | 25,577 / 45,136 | 12,782 / 23,005 |
| Sum of reported provider latency | 199,143 ms | 97,429 ms |

The initial report retains four `INCOMPLETE_PROVIDER_OUTPUT` errors. The retry includes
a false positive on the stricter-than-exception case; it neither replaces those errors
nor shares the initial denominator. The insufficient-evidence case safely abstained.
Read processing errors and abstentions alongside the runner's precision/recall scoring;
do not combine the two runs into an improved score.

Across these two evaluation runs: 31 calls, 38,359 prompt tokens, 68,141 completion
tokens, 296,572 ms summed metered provider latency and 119/119 verified citation instances.
Citation matches establish source correspondence, not correct interpretation. Provider
latency is not end-to-end duration; timed-out dispatches may consume unreported tokens.
The reports also retain graph/review API and permission-revocation checks.

The frontend's [focused browser report](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/focused-demo-verification.json)
retains a separate successful workflow run. Older session/deployment reports and source
manifests are dated snapshots, including references to filenames removed by later cleanup;
their contents and hashes are preserved. The current lifecycle is in [Architecture](ARCHITECTURE.md).

### Reproduce safely

Use the dedicated [local setup](#local-setup), never a shared production database.
The tools create synthetic SQL identities/records; uploads, consent, investigations
and reviews use authenticated APIs. They make real Meta requests and can incur usage.

The SQL fixture helper requires ignored `.local/runtime.env` with database values
matching root `.env`; the smoke script additionally needs `.local/embeddings.env`.
On a fresh dedicated installation, `scripts/init_local.py` and `scripts/fetch_embeddings.py`
create those files. Do not regenerate credentials for an existing volume. The manual
browser demonstration can instead use root `.env` and `scripts/setup_demo.py` as above.

From the backend checkout, only for an intentional new evaluation:

```sh
python3 scripts/smoke_investigation.py
python3 scripts/evaluate_phase4.py --start-backend
# Optional separate retry; leaves the full-run result intact:
python3 scripts/evaluate_phase4.py --start-backend --group explicit-exception --max-procedures 2
```

The smoke script starts/stops its backend. The evaluator does so with `--start-backend`;
without that flag, it uses an already running instance. Its default is two procedure
versions per comparison to bound output. These tools leave synthetic evidence in the
local database and archive/replace report files under `docs/verification/`. Preserve
existing reports before a deliberate rerun, retain failed attempts and review newly
generated artifacts before publication. Provider errors are not successful demonstrations.
Do not execute these commands as documentation checks; fresh outputs can differ.

Keep all raw verification, qualification, provenance and recovery records intact.
In particular, [phase2-results.json](verification/phase2-results.json) is read and hashed
by the Meta preflight tool; removing or rewriting it would invalidate that dependency.
Deterministic regression commands are in [Regression and browser checks](#regression-and-browser-checks).

## Recording an existing investigation

**No video has been created.** The retained frontend
[recording status](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/demo-artifacts/recording-status.json)
records a blocked attempt because its production investigation URL and authorized
credentials/session were missing. That attempt stopped at the configuration guard;
it does not establish production access, recording duration or a successful video.

The optional frontend [recording script](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/e2e/demo-recording.spec.ts)
uses an existing completed investigation. It does not create an account, start inference,
upload documents, change consent or append reviews. API mutations are blocked except
login. Use an authorized synthetic scenario; this is not a Remote Work validation.

From the frontend checkout, with its existing Playwright/Chromium and a usable FFmpeg:

```sh
DEMO_DISCOVER_ONLY=1 \
DEMO_INVESTIGATION_URL='https://YOUR-PRODUCTION-HOST/investigations/EXISTING-INVESTIGATION-UUID' \
DEMO_CREDENTIALS_FILE='/absolute/path/to/existing/private/credentials.json' \
node_modules/.bin/playwright test e2e/demo-recording.spec.ts --workers=1
```

Replace the placeholders. The private JSON has `email` and `password`; existing fixture
files with `viewer`/`actor` and `password` are also accepted. `DEMO_ACCOUNT=actor` selects
the authorized actor. Keep credentials outside public artifacts. Alternatively supply
`DEMO_BASE_URL` and `DEMO_INVESTIGATION_ID`, or use private `DEMO_STORAGE_STATE` and, when
needed, `DEMO_SESSION_FILE` containing the existing token/expiry session. The app verifies
restored identity; older frontends without restoration require credentials. Set
`DEMO_FFMPEG` to an existing encoder path if automatic discovery cannot find it.

Discovery inspects the actual accessible findings, graph, sources and policy history,
then writes `demo-artifacts/feature-discovery.json` and a privacy-masked `preflight.png`.
For recording, replace `DEMO_DISCOVER_ONLY=1` with `DEMO_RECORD=1`. The current script
requires an existing investigation displaying **8 / 5 / 2 / 100%** before recording;
these are a script admission condition, not verified results or universal product metrics.
Discovery does not require those values. Source coverage never means AI accuracy.

Only a successful run generates `ai-policy-investigator-demo.webm`,
`recording-metadata.json`, `demo-timeline.md` and `demo-voiceover.md` under `demo-artifacts/`,
and updates `recording-status.json`. The timeline/narration are generated outputs, not
required inputs; the removed provisional drafts are not evidence of a recording.
The target is one continuous 180-second 1920×1080 silent video, with separate English
narration. Actual duration and dimensions must be confirmed from successful metadata.

The recorder hides account details, omits reviewer History/settings, uses populated
features and records omissions. It trims only setup footage at the ends, without internal
cuts or speed changes. Authentication footage stays in private temporary storage and is
removed when the run finishes. A localhost capture is labeled local preview and cannot
prove deployment. No recording command was executed during this documentation cleanup.
