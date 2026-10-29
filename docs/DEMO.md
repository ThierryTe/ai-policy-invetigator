# Local demo login and complete workflow

The suggested login is **demo@policy-investigator.local**. Its password is the value
of **DEMO_PASSWORD** in your private local environment. There is no default password.
Keep its value in an ignored private file or process environment; never commit or share it.

## Authentication and scope

The demo uses the existing POST /api/auth/login BCrypt check and short-lived JWT,
followed by /api/auth/me. Angular stores the token in memory and handles session expiry.
No authentication bypass or automatic startup seed is involved.

`scripts/setup_demo.py` reuses the existing operator psql/pgcrypto provisioning
approach from `scripts/provision_user.sql`. This is an explicit operator command,
not application startup seeding. It creates one managed demo identity and isolated
Security/HR departments. ADMIN membership in both is needed for uploads,
external-processing consent, investigation write permission, current source access
and human reviews. It grants no access to another organization or department.

## Environment variables

| Variable | Requirement |
|---|---|
| `DEMO_USER_ENABLED` | Must be exactly `true`; absent/false refuses before accessing Docker/database |
| `APP_ENVIRONMENT` | Must be exactly `local` in the provisioning process; production/default refuses |
| `DEMO_PASSWORD` | Required process variable; 16–72 UTF-8 bytes, no control characters or template placeholder |

The provisioning command reads these from its **process environment**. Merely adding
them to root `.env` does not execute a seed or enable an application feature.
Compose still reads its existing root `.env` for database/JWT/Meta configuration.
No demo credential is forwarded to the frontend container or model provider.

## Exact local startup

From the backend checkout, keep your existing private root `.env` unchanged:

```sh
docker compose --env-file .env --profile app up --build -d --wait
```

This starts the existing PostgreSQL 16/pgvector, pinned-model bootstrap and Spring
Boot application, applying the existing migrations. It does not create a demo user.

For a fresh local checkout only, create the private demo password file if absent:

```sh
python3 - <<'PY'
import os, secrets
from pathlib import Path
path = Path('.local/demo.env')
path.parent.mkdir(mode=0o700, exist_ok=True)
if not path.exists():
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write('DEMO_PASSWORD=' + secrets.token_urlsafe(32) + '\n')
    print('Private demo password file created; value withheld.')
else:
    print('Existing private demo password file preserved.')
PY
```

Load that password and explicitly provision the account:

```sh
set -a
. .local/demo.env
set +a
DEMO_USER_ENABLED=true APP_ENVIRONMENT=local python3 scripts/setup_demo.py
unset DEMO_PASSWORD
```

No password is printed. Repeating the command preserves the same user and department
IDs, does not duplicate memberships, and preserves the hash when the password is
unchanged. Explicitly changing DEMO_PASSWORD and reseeding rotates this managed
account's password. Reseeding also reactivates the demo account and restores its two
demo ADMIN memberships. A colliding unrelated user or fixed identity causes rollback.

The command exports the existing synthetic golden PDFs to `.local/demo/pdfs`:

| File | Purpose / effective date |
|---|---|
| `01-security-baseline.pdf` | Training within 30 days after access; 2026-10-26 |
| `02-security-replacement.pdf` | Training mandatory before sensitive access; 2026-10-27 |
| `03-hr-conflicting.pdf` | Sensitive access on day one, training within 30 days; 2026-10-26 |
| `04-hr-compatible.pdf` | Sensitive access blocked until training; 2026-10-26 |

Provisioning/export does not upload documents, grant processing consent or call Meta.
The seed transports the secret as COPY data rather than SQL literals/command-line
arguments, hashes it using the existing BCrypt-compatible pgcrypto mechanism and
drops the temporary input table at commit. Raw database output/errors are not printed.

## Frontend startup and login URL

The frontend is a **separate repository**. No source change is needed there.

For the existing Docker deployment, from the frontend checkout:

```sh
docker compose up --build -d --wait
```

Login URL: **http://127.0.0.1:18081**. The frontend uses the existing backend Docker
network and same-origin `/api` proxy. Keep the VPS reverse proxy/HTTPS configuration
unchanged; no public VPS deployment is performed by this local demo setup.

Alternatively, run the frontend development server:

```sh
npm ci
npm start
```

Development login URL: **http://127.0.0.1:4200**; its existing development proxy targets
the backend at port 18080. Use the username above and your private DEMO_PASSWORD.
A browser reload intentionally requires login again because tokens stay in memory.

## Verify authentication and the complete UI workflow

1. Sign in. A normal login returns a 15-minute JWT and Angular fetches `/api/auth/me`.
   Settings should show **Security: ADMIN** and **HR: ADMIN**. Invalid passwords
   remain rejected; no JWT exception or demo-login bypass exists.
2. In **Policies**, upload `01-security-baseline.pdf` as a POLICY owned by Security,
   effective 2026-10-26. Wait for indexing. Select its row and explicitly click
   **Allow external processing**.
3. Click **New version** on that policy; upload `02-security-replacement.pdf`, effective
   2026-10-27. Confirm versions 1 and 2 both remain in history and can open their PDFs.
4. Upload `03-hr-conflicting.pdf` and `04-hr-compatible.pdf` as two separate PROCEDURE
   documents owned by HR, effective 2026-10-26. Wait for indexing and explicitly allow
   external processing for both.
5. Open **Investigations → Run investigation**. Select the Security policy, baseline
   version 1, replacement version 2, both HR procedure versions and analysis date
   **2026-10-27** (or later). Start and watch persisted stages.
6. Expect a potential **CONTRADICTION** for day-one sensitive access before training
   and a **NO_CONFLICT** control for access gated by training. Inspect actual output;
   errors/incomplete processing must not be treated as NO_CONFLICT. Meta access and
   a real `MODEL_API_KEY` are required; normal provider budgets and errors still apply.
7. Select graph nodes, inspect source quotes and page numbers, and open the original
   PDF. Confirm a finding, add a note and dismiss it to exercise the review workflow.
   History should retain all actions, reviewer identity and timestamps while the
   original AI classification/evidence remain unchanged.
8. Sign out; protected content clears. A reload requires login. The server continues
   to enforce current memberships and complete document scope on every API request.

Use new document titles if deliberately repeating the whole upload demonstration;
immutable versions/results remain as evidence. Seeding is idempotent; uploading
another set of documents is an explicit new workflow, not automatic seed behavior.

## Production boundary and cleanup

Production startup never invokes this script and gains no demo endpoint/default
credential. The development flag gates provisioning, not subsequent authentication:
the account is a normal persisted user. Do not run the operator seed against a shared
production database. Unsetting the flag does not delete an account already created.
To disable local demo access, use existing operator SQL:

```sql
UPDATE app_users SET active=false
WHERE id='d3000000-0000-4000-8000-000000000004'
  AND email='demo@policy-investigator.local';
```

Active-identity checks then reject login and existing JWTs. Reseeding with explicit
local flags reactivates the account. No policy versions, findings or review history
are deleted. `.local/demo.env` and all exported local PDFs remain ignored by Git and
excluded from application/Docker artifacts by the existing rules.
