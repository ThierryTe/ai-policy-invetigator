# AI Policy Investigator

Built for the **Meta Global AI Developer Hackathon 2026**.

**A policy changes. Which procedures need attention, and what is the evidence?**
AI Policy Investigator helps compliance analysts compare a policy with its replacement
and selected procedures, inspect potential conflicts against original PDF evidence,
and record a human decision.

| Start here | Purpose |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Components, AI pipeline, security and infrastructure |
| [Testing](docs/TESTING.md) | Judge walkthrough, local setup, scenarios and recorded evaluation |
| [Frontend source](https://github.com/ThierryTe/ai-policy-invetigator-frontend) | Angular application; backend source is this repository |

## Problem and solution

A new policy can make an existing procedure incompatible without changing that
procedure's wording. Reviewing the policy alone misses the operational consequence.

The application compares an immutable baseline, its direct replacement and **one to
four explicitly selected procedure versions**. It connects changed requirements,
potential issues, source quotations and suggested actions in one investigation.
An analyst can confirm, dismiss or annotate a finding while preserving the AI output.

## Implemented workflow

1. Upload policy and procedure PDFs; retain original bytes and immutable versions.
2. Index page-aware text with local ONNX embeddings and PostgreSQL/pgvector.
3. Explicitly authorize external processing for the selected documents.
4. Start an asynchronous investigation and follow its persisted progress.
5. Inspect requirements, findings, exact quotations, original PDFs and the impact graph.
6. Record human review decisions separately from the original classification and evidence.

Classifications are `CONTRADICTION`, `MISSING_REQUIREMENT`, `AMBIGUITY` and `NO_CONFLICT`.
Incomplete processing and provider failures remain explicit; they are never successful
no-conflict assessments. Suggested actions require review and do not modify policies.

## What Meta Muse Spark does

The backend calls the Meta Model API with **`muse-spark-1.3`** to extract structured
requirements, align baseline/replacement requirements and assess selected procedures.
Muse supplies the interpretation behind the findings. The server validates response
schemas, model identity, source IDs and exact quotations before publishing results.

Local `all-MiniLM-L6-v2` embeddings support retrieval independently of Meta reasoning.
Source access and external-processing consent are checked before each provider attempt.
Historical [real inference](docs/verification/phase3-demo.json) and the
[API preflight](docs/verification/meta-api-preflight.json) establish prior use of Meta;
they do not guarantee current account entitlement or production availability.

## Demo and video

- **Configured demo address:** [ai-policy.tewendelabs.com](https://ai-policy.tewendelabs.com).
  Availability and judge access have not been reverified in this documentation pass.
  Individual credentials and a completed-investigation link must be supplied privately.
- **Two-minute walkthrough:** [open an existing result](docs/TESTING.md#judge-walkthrough).
  Reading its findings, graph and evidence makes no new reasoning request.
- **Video:** no published video URL is available. The frontend's
  [recording status](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/demo-artifacts/recording-status.json)
  records that no video was created. See the [recording instructions](docs/TESTING.md#recording-an-existing-investigation).
- **Visual fallback:** historical local captures of the
  [desktop investigation](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/desktop-fitted-investigation.png),
  [mobile investigation](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/mobile-fitted-investigation.png)
  and [PDF viewer](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/pdf-real-source.png).

The recorded synthetic scenario contrasts training **before sensitive-system access**
with day-one access and training within 30 days, plus a compatible control procedure.
**Remote Work is not validated:** its three input documents were not found in the
inspected repositories, and no completed Remote Work investigation is established.
The [test procedure](docs/TESTING.md#remote-work-scenario) defines what remains to verify.

## Evidence and limits

The initial ten-case synthetic evaluation matched **6/10** expected outcomes, with
four processing errors. A separate four-case retry matched **3/4**, including one
false positive. Its results do not replace the initial failures. See
[recorded evaluation](docs/TESTING.md#recorded-evaluation) for evidence and reproduction.

Verified citations establish source correspondence, not correct interpretation or
general AI accuracy. The MVP does not provide automatic enterprise-wide procedure
discovery, autonomous remediation, report export, a server investigation-history list,
notifications or a live accuracy score. No compliance certification is claimed.

## Operations and attribution

Local installation and test commands are in [Testing](docs/TESTING.md). Operators retain
the separate [production pipeline](docs/PRODUCTION_PIPELINE.md),
[deployment and recovery guide](docs/DEPLOYMENT.md) and
[judge provisioning guide](docs/JUDGE_DEMO.md). These guides do not establish live health.

Selected infrastructure derives from [AI Compliance Copilot](https://github.com/ThierryTe/spring-ai-rag).
The [pre-existing capabilities](docs/provenance/PRE_EXISTING.md),
[project contributions](docs/provenance/HACKATHON_CONTRIBUTIONS.md),
[exact reuse records](docs/provenance/allowlist.json) and
[third-party notices](THIRD_PARTY_NOTICES.md) preserve attribution.
Credentials, private documents, model weights and database backups stay outside public artifacts.
