# Pre-existing work

Reuse was authorized by the project owner on October 26, 2026, with event eligibility
confirmed by the owner. This records that confirmation; it is not an independent
legal assessment of the event rules.

Backend source: https://github.com/ThierryTe/spring-ai-rag
Commit: c22f3b1e0f690aa195e85e0ea37c98d8ffe43cb1

Frontend inspected: https://github.com/ThierryTe/spring-ai-rag-frontend
Commit: 282991b0df41f156aeef61c79e8738509c56eab8
No frontend code has been imported in Phase 2. Its pre-existing modified README was
not copied or changed.

Pre-existing capabilities include Java/Spring build infrastructure, BCrypt/JWT
login, role-based SQL filtering, JDBC/pgvector search, basic PDF ingestion,
Spring AI embeddings, bounded in-memory ingestion, monitoring, and an authenticated
Angular portal with upload/polling/UI primitives. None is claimed as an invention
of this event.

Only the four files in allowlist.json were physically imported. TextCleaningService
has a package rename and is used only for embedding input. All other implementation
files were authored here; adaptations.json records source-informed designs and the
security changes even where no source bytes were imported.

Excluded: Git histories, environment files, credentials, seed accounts, private data,
generated reports, OpenAI clients/configuration, RAG prompts, demo session logic,
old migrations and deployment secrets. No old database has been accessed.
