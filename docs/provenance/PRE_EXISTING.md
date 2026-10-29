# Pre-existing capabilities

The source backend is [ThierryTe/spring-ai-rag](https://github.com/ThierryTe/spring-ai-rag),
inspected at commit c22f3b1e0f690aa195e85e0ea37c98d8ffe43cb1. The reference frontend is
[ThierryTe/spring-ai-rag-frontend](https://github.com/ThierryTe/spring-ai-rag-frontend),
inspected at commit 282991b0df41f156aeef61c79e8738509c56eab8.

Before Investigator, that project already provided Java/Spring build infrastructure,
BCrypt/JWT login, role-based SQL filtering, parameterized JDBC/pgvector search, PDF
ingestion, Spring AI embeddings, bounded in-memory ingestion, monitoring and an
Angular authenticated portal with upload/polling primitives. These are pre-existing
capabilities, not new hackathon inventions.

Only the four files in [allowlist.json](allowlist.json) were physically imported into
this backend. [adaptations.json](adaptations.json) documents design-informed work
without copied source bytes. The backend allowlist contains no frontend source files;
frontend attribution belongs to its separate repository.

The owner authorized selective reuse on October 26, 2026 and confirmed event eligibility.
No independent legal assessment is implied. Source environment files, credentials,
private data, generated artifacts, OpenAI clients/prompts, old migrations and database
contents were excluded. See [Investigator contributions](HACKATHON_CONTRIBUTIONS.md).
