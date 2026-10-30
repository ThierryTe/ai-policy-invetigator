# Project documentation

Start with the [project overview](../README.md), then choose a guide:

| Guide | Contents |
|---|---|
| [Judge quickstart](JUDGE_QUICKSTART.md) | Two-minute evidence walkthrough, access expectations and fallback |
| [Submission draft and demo script](HACKATHON_SUBMISSION.md) | English product story, Meta integration, differentiation and presentation sequence |
| [Architecture](ARCHITECTURE.md) | Components, data model, AI pipeline, authorization and reliability |
| [Local installation and configuration](SETUP.md) | Prerequisites, environment variables, Docker and host development |
| [Synthetic demonstration](DEMO.md) | Private demo login, PDF fixtures and the complete browser workflow |
| [Interactive judge access](JUDGE_DEMO.md) | Individual test departments, targeted scenario sharing, persistent quotas, expiration and local provisioning |
| [API: documents and authentication](api/phase2.md) | Login, upload, immutable versions, ingestion and evidence |
| [API: investigations](api/phase3.md) | Consent, asynchronous jobs, structured requirements and findings |
| [API: dashboard and human review](api/phase4.md) | Status, graph, verified citations and append-only review actions |
| [Evaluation and reproducibility](EVALUATION.md) | Golden datasets, recorded real inference, errors and limitations |
| [Production CI/CD](PRODUCTION_PIPELINE.md) | Main-branch publication, SSH image delivery, GitHub configuration and rollback |
| [Production operations](DEPLOYMENT.md) | Network topology, initial account, backup and restore |
| [Reuse and contributions](provenance/HACKATHON_CONTRIBUTIONS.md) | Pre-existing work, exact imports and Investigator-specific development |
| [V8 preproduction qualification — English companion](V8_PREPRODUCTION.en.md) | Option A GO, recorded test results, deployment conditions and realistic rollback |
| [English-language and judge-readiness audit](audits/ENGLISH_JUDGE_READINESS.md) | Cross-repository findings, protected historical content and five highest-impact improvements |

The API filenames retain their original names to preserve existing links; they are
current contracts, not development plans. Selected machine-readable evidence remains
under `verification/`. See [evaluation](EVALUATION.md) for its purpose and limitations.
