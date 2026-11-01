# Reuse and Investigator contributions

This project builds on selected infrastructure and design experience from
[AI Compliance Copilot](https://github.com/ThierryTe/spring-ai-rag). It does not claim
that pre-existing login, PDF ingestion, vector search or Angular infrastructure were
invented during this event. The owner authorized selective reuse and confirmed event
eligibility; that confirmation is not an independent interpretation of hackathon rules.

## Exact imports and design references

The [allowlist](allowlist.json) records four imported files with repository URL,
source commit/path/hash, destination/hash and adaptation:

- Maven wrapper scripts and wrapper properties: unchanged.
- TextCleaningService: package adapted; used for embedding input, never canonical evidence.

[adaptations.json](adaptations.json) records reference-informed security, upload,
SQL retrieval, embedding and bounded-worker designs where source bytes were not copied.
[PRE_EXISTING.md](PRE_EXISTING.md) describes the prior project's capabilities.
No source repository was modified. Git histories, credentials, private documents,
OpenAI reasoning clients/prompts, old schema/data and seed accounts were not imported.

The deployment build/push → SSH/Compose sequence is informed by the Copilot backend
and frontend workflows. Investigator adds its own immutable multi-image selection,
runner-side archive transfer, validation and database-preserving release handling.
The frontend remains a separate repository with its own source history and notices.

## Investigator-specific development

- Policy/procedure domain with immutable versions and original page-aware PDF evidence.
- Current identity, department/grant scope and forced RLS across SQL, JPA and workers.
- Explicit external-processing consent and rechecks before model requests/persistence.
- Independent PolicyReasoningProvider and real Meta structured reasoning integration.
- Structured requirement extraction, version-change alignment and bounded procedure comparison.
- Server-owned JSON schemas, source-ID/quote verification and model/prompt/schema provenance.
- Durable investigation jobs, checkpoints, deadlines, bounded retries and safe failure states.
- Persisted authorized impact graph and append-only human review preserving AI evidence.
- Synthetic golden datasets, real-provider evaluation, error accounting and citation checks.
- Separate Angular investigation workflow, production image delivery and reproducible model cache.

These are project contributions, not claims that every underlying architectural idea
is novel. The [evaluation guide](../TESTING.md#recorded-evaluation) separates real inference evidence
from deterministic/mocked tests and reports unsuccessful outcomes as well as successes.

## Dependencies and limits

Local embeddings use a pinned public model with its own
[provenance/license record](embedding-model.json); weights are not distributed here.
Preserve [third-party notices](../../THIRD_PARTY_NOTICES.md) and upstream license headers.
This record documents attribution; it does not claim a completed production deployment
or general AI accuracy.
