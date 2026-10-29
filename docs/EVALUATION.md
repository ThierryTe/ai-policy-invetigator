# Evaluation and reproducibility

All published examples and reports use synthetic policy text. The small dataset is a
demonstration of behavior and failure handling, not an estimate of general accuracy.
No new Meta request was made while preparing this documentation.

## Recorded real inference

The [Meta preflight](verification/meta-api-preflight.json) records authenticated model
discovery and structured inference with muse-spark-1.3. It contains the synthetic
request contract, latency and usage, with no credential value. Access is account-specific;
a successful historical check does not guarantee entitlement for another account.

The [training/access demonstration](verification/phase3-demo.json) compares:

- A replacement security policy requiring training before sensitive-system access.
- An HR procedure granting day-one access with training within 30 days.
- A compatible control procedure withholding sensitive access until training.

The recorded result identified the contradiction and returned NO_CONFLICT for the
control. All cited source IDs/quotes were checked, along with permission revocation
and cross-department denial. Five calls used 6,368 prompt and 8,200 completion tokens;
reported provider latency was 47,469 ms and end-to-end elapsed time 48,732 ms. Two
selected cases do not establish accuracy, even though both expected labels matched.

## Golden datasets and actual outcomes

The repository includes `evaluation/phase3-golden.json` and the ten-case
`evaluation/phase4-golden.json`. They cover contradictions, compatible access gates,
exceptions, scope differences, ambiguity, missing requirements and insufficient evidence.

| Recorded run | Full ten-case run | Separate explicit-exception retry |
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

The [full report](verification/phase4-evaluation.json) retains four
INCOMPLETE_PROVIDER_OUTPUT errors, rather than relabeling them as successful
NO_CONFLICT outcomes. The [targeted retry](verification/phase4-explicit-exception-evaluation.json)
is a separate run, not a replacement for the original results. It includes a false
positive on the stricter-than-exception case. The insufficient-evidence case safely
abstained. Metrics follow the runner's recorded scoring conventions; processing errors
and abstentions must be read alongside precision/recall. The four-case retry does not
share the full run's denominator and must not be merged into an improved score.

Citation correctness checks source correspondence, not whether the model interpreted
an exception or obligation correctly. Human review remains necessary. The reports also
record graph/review API checks and authorization revocation.

## Reproduce safely

Use the dedicated local environment and [demo setup](DEMO.md), never a shared production
database. These scripts create synthetic SQL identities/records; document ingestion,
consent, investigations and reviews go through authenticated APIs.

The automated tools also use ignored .local/runtime.env through their SQL fixture
helper, and the smoke script needs .local/embeddings.env. For a fresh dedicated local
setup, init_local.py and fetch_embeddings.py create those files; keep their database
values consistent with root .env. Do not regenerate credentials for an existing volume.
The browser demo can instead use root .env with setup_demo.py as documented.

```sh
python3 scripts/smoke_investigation.py
python3 scripts/evaluate_phase4.py --start-backend
# Optional separate retry; leaves the full-run result intact:
python3 scripts/evaluate_phase4.py --start-backend --group explicit-exception --max-procedures 2
```

The smoke script manages its local backend lifecycle; the evaluator starts/stops the
backend when --start-backend is supplied and otherwise uses an already running instance.
Both use real Meta inference and can incur usage. They leave synthetic evidence in the
local database. Inspect the reported errors and usage; a provider failure is not a
successful demonstration. See script docstrings before execution.

The evaluator defaults to two procedure versions per comparison to stay within the
existing provider output budget. It writes sanitized results under docs/verification
and archives previous outputs there. Such newly generated attempt histories are local
run artifacts; review and select evidence deliberately before publication.

## Evidence retained in this repository

| File | Reason |
|---|---|
| verification/meta-api-preflight.json | Actual synthetic Meta contract, account model, usage and latency |
| verification/phase3-demo.json | Real end-to-end conflict/control result and verifiable evidence |
| verification/phase4-evaluation.json | Full ten-case results, including errors |
| verification/phase4-explicit-exception-evaluation.json | Separate retry, including a false positive |
| verification/phase2-results.json | Baseline verification file read and hashed by the existing Meta preflight script |

The baseline file is intentionally unchanged: removing or rewriting it would break
that script or invalidate the hash in the recorded preflight. API/evidence filenames
retain their stable paths for tools and existing consumers. Development-phase reports,
local machine logs and obsolete per-attempt histories are not required for reproduction.

For deterministic regression checks without provider calls:

```sh
python3 -B -m unittest discover -s scripts/tests -v
./mvnw -B -Pdatabase-tests verify
```

The database suite exercises authorization across JDBC/JPA/workers, immutable provenance,
revocation, review history and provider error handling. Synthetic/mocked test success is
separate from real inference results. External-provider outputs may vary between runs.
