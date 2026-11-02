# AI Policy Investigator

Built for the **Meta Global AI Developer Hackathon 2026**.

**A policy changes. Which procedures need attention, and what is the evidence?**

AI Policy Investigator helps compliance analysts compare an existing policy with its replacement, identify potential conflicts in related procedures, inspect supporting evidence from original PDF documents, and record human review decisions.

**Live application:** https://ai-policy.tewendelabs.com

| Start here | Purpose |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Components, AI pipeline, security, and infrastructure |
| [Testing](docs/TESTING.md) | Judge walkthrough, local setup, test scenarios, and recorded evaluation |
| [Frontend source](https://github.com/ThierryTe/ai-policy-invetigator-frontend) | Angular frontend; this repository contains the backend |

## Problem and Solution

When an organization updates a policy, existing procedures may become outdated without their wording changing.

For example, a new remote-work policy may reduce the number of permitted remote days or change who approves exceptions, while an existing management procedure continues to describe the previous rules.

Traditional document comparison alone does not necessarily reveal these operational consequences.

AI Policy Investigator addresses this problem by comparing:

- An immutable baseline policy version.
- Its direct replacement.
- One to four explicitly selected procedure versions.

The application connects changed requirements, potential conflicts, original source quotations, and suggested actions in a single investigation.

Human reviewers remain responsible for confirming, dismissing, or annotating findings.

## Key Features

- **Policy change analysis:** Compare structured requirements across policy versions.
- **Procedure impact assessment:** Identify potential contradictions, missing requirements, and ambiguities.
- **Evidence-based findings:** Inspect exact quotations and original PDF documents.
- **Investigation graph:** Visualize relationships between policy changes and affected procedures.
- **Human-in-the-loop review:** Record decisions without overwriting original AI findings.
- **Asynchronous processing:** Track investigation progress through background workers and persisted checkpoints.
- **Document versioning:** Preserve original PDF bytes and immutable document versions.
- **Controlled external processing:** Require explicit authorization before sending selected document content to Meta.

Supported finding classifications are:

- `CONTRADICTION`
- `MISSING_REQUIREMENT`
- `AMBIGUITY`
- `NO_CONFLICT`

Processing failures are reported explicitly and are never treated as successful no-conflict assessments.

Suggested actions require human review and do not automatically modify policies or procedures.

## Implemented Workflow

1. Upload policy and procedure PDF documents.
2. Preserve their original bytes and immutable versions.
3. Index page-aware document text using local ONNX embeddings and PostgreSQL with pgvector.
4. Explicitly authorize external processing for the selected documents.
5. Select a baseline policy, its replacement, and up to four procedure versions.
6. Start an asynchronous investigation and monitor its progress.
7. Review extracted requirements, findings, source evidence, original PDFs, and the impact graph.
8. Confirm, dismiss, or annotate findings while preserving the original AI output.

## How Meta Muse Spark Is Used

AI Policy Investigator integrates **Meta Muse Spark 1.3** through the Meta Model API using `muse-spark-1.3`.

Muse Spark provides the semantic reasoning needed to:

1. Extract structured requirements from policy documents.
2. Align requirements between baseline and replacement policy versions.
3. Identify meaningful changes in obligations, responsibilities, deadlines, exceptions, and effective dates.
4. Assess the potential impact of those changes on selected operational procedures.

The backend validates model responses before publishing findings, including response schemas, model identity, source IDs, exact quotations, and structured extraction requirements.

The current extraction contract is **`requirements-v4` / `policy-investigator-2026-11-02-v4`**.

It requires `unknownFields` to contain exactly the names of fields whose final JSON values are `null`. A non-null `effectiveDate` must be a valid ISO calendar date and must not appear in `unknownFields`.

Inconsistent model responses are rejected rather than silently repaired or presented as verified findings.

The [v4 verification note](docs/UNKNOWN_FIELDS_V4.md) documents **206 passing offline tests**. These tests validate backend behavior but do not establish production model reliability or guarantee successful inference.

Local `all-MiniLM-L6-v2` embeddings support document retrieval independently of Meta's reasoning capabilities.

Source access and external-processing consent are checked before each provider attempt.

Historical [real inference evidence](docs/verification/phase3-demo.json) and [Meta API preflight results](docs/verification/meta-api-preflight.json) document prior Meta integration. They do not guarantee current API entitlement or availability.

## Technical Architecture

| Component | Technology |
|---|---|
| Frontend | Angular 21 |
| Backend | Java Spring Boot |
| AI integration | Spring AI 2.0.1 for local embeddings |
| AI reasoning | Meta Muse Spark 1.3 via Meta Model API |
| Embeddings | Spring AI Transformers / local ONNX / all-MiniLM-L6-v2 |
| Database | PostgreSQL with pgvector |
| Investigation processing | Asynchronous background workers |
| Deployment | Docker Compose |
| CI/CD | GitHub Actions and GitHub Container Registry |

See [Architecture](docs/ARCHITECTURE.md) for the detailed system design, security model, and AI pipeline.

## Live Demo and Judge Access

**Application:** https://ai-policy.tewendelabs.com

**Demo video:** English walkthrough, 2 minutes 54 seconds.

**Video URL:** https://youtu.be/5Wn6jKOish8

The application requires authentication. Demo account details and investigation access instructions are provided in the hackathon submission's Project Description.

### Recommended Investigation: Remote Work Policy

**Investigation ID:** `d706af38-a477-4177-bbb8-07001b0041bb`

This scenario uses three fictional PDF documents:

1. **Remote Work Policy 2025:** Allows three remote-work days per week, with manager-approved exceptions.
2. **Remote Work Policy 2026:** Reduces remote work to two days per week, requires office attendance on Tuesdays and Thursdays, and transfers exception approvals to Human Resources.
3. **Remote Work Management Procedure:** Contains rules based on the earlier policy.

The recorded demo shows a previously completed investigation of these documents.

Reviewers can explore policy changes, procedure impact findings, supporting PDF quotations, and the investigation graph.

### Additional Investigation: Employee Contract

**Investigation ID:** `44b5b0bc-920d-4e3f-8588-848c5b78e9e2`

An additional investigation is available to demonstrate the application's document review workflow.

### Recommended Judge Walkthrough

1. Open the live application.
2. Sign in using the dedicated demo credentials supplied with the hackathon submission.
3. Open the Remote Work investigation using the provided investigation link or supported navigation.
4. Review the detected policy changes and procedure impact findings.
5. Inspect supporting quotations and original PDF documents.
6. Explore the investigation graph.
7. Optionally review the Employee Contract investigation.

Previously completed investigations can be reviewed without triggering new Meta inference calls.

Starting a new investigation is optional and subject to API usage limits.

The video and investigation IDs are provided by the project owner. The exact PDF contents, result correctness, current application health, and judge access have not been independently verified as part of this documentation update.

For the detailed walkthrough and validation steps, see [Testing](docs/TESTING.md#judge-walkthrough) and the [Remote Work scenario](docs/TESTING.md#remote-work-scenario).

### Visual References

Historical application screenshots are available:

- [Desktop investigation](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/desktop-fitted-investigation.png)
- [Mobile investigation](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/mobile-fitted-investigation.png)
- [PDF viewer](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/pdf-real-source.png)

## Evidence, Evaluation, and Limitations

Historical synthetic evaluations remain available for transparency and reproducibility.

An initial ten-case evaluation matched **6 out of 10** expected outcomes, with four processing errors.

A separate four-case retry matched **3 out of 4** expected outcomes, including one false positive. This retry does not replace or erase the initial failures.

See the [recorded evaluation](docs/TESTING.md#recorded-evaluation) for supporting evidence.

These historical results are not a current accuracy benchmark for the v4 extraction contract.

Verified citations establish correspondence with source documents, but do not guarantee correct interpretation or general AI accuracy.

The current MVP does not provide:

- Automatic enterprise-wide procedure discovery.
- Autonomous policy or procedure remediation.
- Report export.
- A server-side investigation-history list.
- Notifications.
- A live accuracy score.

AI-generated findings require human review. No compliance certification is claimed.

## Operations and Documentation

- [Testing and local setup](docs/TESTING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Production pipeline](docs/PRODUCTION_PIPELINE.md)
- [Deployment and recovery](docs/DEPLOYMENT.md)
- [Judge provisioning](docs/JUDGE_DEMO.md)

Operational documentation does not independently establish current production health.

## Provenance and Attribution

Selected infrastructure derives from the earlier [AI Compliance Copilot](https://github.com/ThierryTe/spring-ai-rag) project.

The following records distinguish pre-existing capabilities, hackathon contributions, and third-party dependencies:

- [Pre-existing capabilities](docs/provenance/PRE_EXISTING.md)
- [Hackathon contributions](docs/provenance/HACKATHON_CONTRIBUTIONS.md)
- [Exact reuse records](docs/provenance/allowlist.json)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

Credentials, private documents, model weights, and database backups remain outside public repository artifacts.

## Project Goal

**AI Policy Investigator helps organizations understand not only what changed in a policy, but which operational procedures may need attention and what evidence supports that conclusion.**

By combining Meta Muse Spark's semantic reasoning with strict backend validation, document traceability, and human review, the project demonstrates a practical approach to evidence-based policy governance.