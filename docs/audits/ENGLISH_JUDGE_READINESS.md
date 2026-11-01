# English-language and judge-readiness audit

Audit date: October 30, 2026. Scope: accessible local backend and frontend repositories.

**Assessment:** the audited source is already English-first. No French prose was found
in judge-visible UI, API examples or synthetic scenario inputs. The substantial French
document is the historical V8 qualification report, preserved unchanged and now served
by an English companion. Documentation is clearer after this pass; final competition
readiness remains conditional on a rehearsed judge account, a working completed-result
link and the submission assets supplied by the owner. This is not live production
certification or a prediction of placement.

## Coverage and method

Both repositories were accessible:

- Backend: `aI-policy-investigator-backend` in the shared workspace.
- Frontend: sibling `ai-policy-investigator-frontend`; no frontend access gap.

Before edits, the source inventory included **155 backend and 73 frontend text files**.
The review combined accented-character and French-vocabulary searches, manual review
of candidate lines, the UI entry points/error mapping/navigation, API documentation,
seed/evaluation text, operator scripts, repository READMEs and technical guides.
Five existing frontend desktop/mobile/PDF screenshots were inspected visually. Their
text is English, including the visible synthetic PDF content. No presentation deck,
video or submission-specific file was found in the audited source directories before
this pass. New submission copy is explicitly a draft.

The inventory covers `src/`, `docs/`, `scripts/`, `deploy/`, `evaluation/`, frontend
`e2e/` and `public/`, `.github/`, Maven wrapper configuration and root project text.
Migrations were read and hashed, never edited. Generated dependency locks, dependency
trees, build/cache directories, ignored local/e2e data, secret/environment files,
credential material and repository metadata were excluded from language scanning.
An additional vocabulary pass covered French written without accents, which identified
two inherited comments in the provenance-pinned `TextCleaningService` source.
Private uploads, database contents, deployed UI/model outputs and the actual submission
portal were not inspected. Static searches cannot establish the language of future
user-supplied documents or generated model explanations. This report does not claim that.

No Git command, VPS/production access, deployment or real Meta call was performed.
The only external lookup was public official event information. No credentials were
read or printed. Source, API contracts, assertions, seeds, prompt behavior, migrations,
qualified binaries and historical evidence are unchanged.

## Language findings by priority

Priority definitions: **P0** judge-visible or live-demo impact; **P1** public documentation
and submission; **P2** internal developer/operator documentation; **P3** internal comments
and other non-user-facing text.

| ID | Priority | Verified finding | Action / disposition |
| --- | --- | --- | --- |
| L01 | P0 | No French prose found in frontend labels, buttons, navigation, dialogs, notices, error messages, metadata or inspected captures. `src/index.html` declares `lang="en"`. | No UI translation or behavior change needed. This does not attest the deployed version. |
| L02 | P0 | Golden policy/procedure text, demo departments, titles and visible model explanations in existing captures are English. | Keep their bytes and identifiers intact. No seed, PDF, finding, review or investigation was rewritten. |
| L03 | P1 | Backend/frontend READMEs, API examples, demo instructions, provenance and public technical guides are English. The operator-focused judge guide is long, and no submission-specific draft was present. | Add a two-minute judge quickstart and English submission/demo draft. Link both from the backend entry points; keep detailed setup intact. |
| L04 | P2 | [V8_PREPRODUCTION.md](../V8_PREPRODUCTION.md), lines 1–229, is French. It combines qualification evidence, the option A reassessment and an operator runbook. | Preserve it as a historical record. Add [V8_PREPRODUCTION.en.md](../V8_PREPRODUCTION.en.md) with equivalent results, conditions and commands; direct current readers to the English companion. No historical JSON or hash reference changed. |
| L05 | P3 | `scripts/tests/test_initial_admin.py:31` and `scripts/tests/test_setup_demo.py:30` contain an accented character used repeatedly in password-validation fixtures. It is test data, not French prose. | Preserve the assertions and UTF-8 boundary cases. Translating the character would change what the tests exercise. |
| L06 | P3 | `src/main/java/com/tewendelabs/investigator/ingestion/TextCleaningService.java:5,14` contains two French comments written without accents. The file is an imported adaptation pinned by `docs/provenance/allowlist.json` to SHA-256 `95862bdbf9ef29d4dcb80a093ef22f0a2bace64d479e7caf99d117c937eb7f1e`. | Preserve source bytes and historical provenance. English equivalents: “Light normalization of extracted text before chunking; text hygiene only, no business logic.” and “Remove control characters other than newline and tab; they do not contribute document text.” A future comment-only adaptation should have a new provenance entry without overwriting the historical import hash. No other French comments or fixed operator/log messages were found in this scope. |
| L07 | P0, unverified runtime risk | User-uploaded text and future model-generated text have no source-audit guarantee of English. No production database or runtime was inspected. | Use the existing English scenario and recorded outputs for judging. If a French fixture is later discovered, create a separately versioned English scenario in isolation, regenerate its PDFs/hashes/extractions/investigations, verify it and provision new links. Never translate stored evidence in place. Prompt changes require separate approval and evaluation. |

The retained French prose consists of the original historical qualification report
and these two provenance-pinned internal comments. All documentation created or edited
by this pass is English. Neither case is judge-visible UI or synthetic scenario content.
Words shared by English and French, such as “procedure,” and CSS `sans-serif` were
reviewed as false positives rather than translated.

## Judge experience: verified facts and recommendations

| Question | Verified evidence | Assessment / recommendation |
| --- | --- | --- |
| Value understood within 30 seconds? | README already explains policy-change comparison. Login says “Understand what a policy change sets in motion.” The dashboard shows findings, evidence and actions. No timed first-time user study was run. | Likely understandable when led with the concrete training/access conflict. README now links a result-first quickstart. Rehearse with an unfamiliar person; do not claim a measured comprehension time. |
| Problem → AI explanation → evidence → action? | `dashboard.html` and `finding-panel.ts` expose classifications, AI explanation, suggested action, exact references, PDF viewer and review history. Existing captures show CONTRADICTION and NO_CONFLICT. | Strong demonstrated path. Start with the finding and original PDF; explain the graph afterward. Existing captures show a human Dismissed badge: explain the difference from the original AI classification rather than altering history. |
| Genuine and visible Muse Spark? | Backend transport uses `https://api.meta.ai/v1/chat/completions`; provider defaults to `muse-spark-1.3`, requests structured output, verifies model identity and records usage. Historical preflight/investigation/browser records report real inference. | Genuine integration is supported by source plus historical records; no fresh inference was attempted. The main finding view exposes model calls/tokens but does not prominently identify Muse Spark/model provenance. The guide/draft now explains it; a visible model/provenance panel is a recommended product enhancement, not implemented here. |
| Navigation without permission surprises? | `Directory` requires a saved UUID/link; recent investigations are session-only. `Auth.canUpload` checks account memberships. `Policies.canWriteSelected` uses that broad capability, so a private ADMIN may see version-write controls on a shared READ-only policy. Backend tests deny those writes. | Security remains enforced, but permission errors can damage the demo. Use the supplied result link and read controls. A resource-specific capability UI would need separate design/API approval; do not infer write rights from a private role. |
| Clear differentiation? | Scoped version alignment, exact quotations, original PDFs, durable jobs and append-only human review are implemented. Provenance separates reused infrastructure from project contributions. | Explain the investigation workflow, verifiable sources and accountable decisions. Avoid unsupported market-superiority, autonomous-remediation or general-compliance claims. |
| Safe fallback? | Completed authorized reads do not invoke the provider. Historical captures/evidence exist. Progress exposes PARTIAL/FAILED; incomplete work is not treated as no conflict. No automatic replay/fallback mode was found. | Use an earlier completed result, clearly labeled, then local historical captures if the site is down. Guide/script now document this. Actual target-account access and the offline asset handoff still need rehearsal. |

Source references for the frontend findings are in its accessible checkout:
`src/app/core/auth.ts`, `src/app/core/errors.ts`, `src/app/core/workspace.ts`,
`src/app/features/investigations/{directory,start,dashboard,recent-investigations}.ts`,
`dashboard.html`, `finding-panel.ts`, `src/app/features/policies/policies.ts`,
`src/app/features/settings/evaluations.ts`, and `docs/REAL_DEMO.md`.
The stale start-form message describes WRITE as universally required; V8's judge
analysis exception does not require shared-source WRITE. Provisioned judges have a
private ADMIN membership and therefore pass the current account-level gate. This is
a wording/capability-design issue, not evidence that the tested V8 backend exception
is blocked. No application wording was changed in this translation-only pass.

Additional friction: `errors.ts` returns a generic “wait a moment” message for every
429 before examining specific error codes. Demo lifetime/collective quotas do not
necessarily reset with time. Evaluations currently presents “No evaluation feed is
available,” not live scores. Keep judging on the prepared investigation and link to
the recorded evaluation documentation. Do not invent remaining-quota data or a feed.

## Security, integration and credibility retained

The V8 option A qualification remains **GO for the qualified local artifact**. Its
[existing report](../verification/v8-qualification.json) records 172 successful Java
tests and 173 successful Python tests from the prior qualification. Shared document
WRITE denial, isolation between judges/departments, ordinary READ/WRITE distinctions,
DEFINER/INVOKER ownership, FORCE RLS, NOBYPASSRLS, quota races, retries, expiry and
in-flight revocation are represented in the retained cases. No new security guarantee
or production claim is inferred from copy changes.

Historical Meta evidence:

- [API preflight](../verification/meta-api-preflight.json): authenticated synthetic
  inference recorded with `muse-spark-1.3`.
- [Investigation evidence](../verification/phase3-demo.json): real extraction/comparison,
  contradiction/control, reported usage and verified quotations.
- Frontend `docs/focused-demo-verification.json`: recorded browser workflow, five calls,
  eight verified published citation instances and 40,605 ms summed metered provider
  latency. It is not a current latency or availability promise.
- [Evaluation](../TESTING.md#recorded-evaluation): initial 6/10 expected outcomes with four processing
  errors; separate retry 3/4 with one false positive. 119/119 verified quote instances
  across those evaluation runs are not 100% reasoning accuracy.

The [official event overview](https://dev.meta.ai/events/global-hackathon) describes
creativity, technical ambition and working software for indie entrants, and technical
execution/production robustness for startups. This supports prioritizing a clear working
demonstration and truthful evidence. The owner's selected track, accepted Official Rules,
actual submission fields and final eligibility were not independently verified here;
no judging weights or prize outcome are assumed.

## Five highest-impact improvements, in priority order

| Rank | Priority | Verified starting point | Improvement and acceptance check | Status / owner |
| --- | --- | --- | --- | --- |
| **1** | **P0** | A new session has no pinned scenario; opening existing work requires a UUID/link. | Give each judge one completed-result deep link plus private individual access and a short walkthrough. Fresh-session acceptance: sign in → contradiction → original PDF within two minutes, with all contributing sources visible. | **Docs delivered:** README entry and quickstart. **Owner remaining:** actual private handoff, expiry check and fresh-session rehearsal. An in-app pinned entry is a separate enhancement. |
| **2** | **P0** | Shared-source write controls can appear; quota errors are generic; shared scenario review is intentionally denied. | Make available actions match per-resource rights and show actionable distinctions between expired access, persistent quota and unavailable service. Acceptance: shared scenario produces no tempting write/review path; private WRITE still works; source denial remains enforced. | **Guide mitigation delivered. Product change recommended only:** requires explicit approval, capability-contract review and focused UI/security checks. |
| **3** | **P0** | Historical live run needed tens of seconds of summed provider time; no automatic inference fallback exists. | Rehearse a completed-result tab and local screenshot/evidence fallback. Acceptance: if live inference is slow, switch smoothly and label the earlier real run; if the site is down, show local captures without implying live success. | **Fallback script delivered. Owner remaining:** verify target-account access, stage local assets, decide whether a live extension is worth the budget. |
| **4** | **P1** | Meta integration is real in source/evidence, but model identity is not prominent on the main finding screen. | Explain “Muse Spark extracts, aligns and compares; local embeddings retrieve; server validates.” Show actual provenance/usage and one verified PDF citation. Acceptance: an unfamiliar reviewer can identify Meta's essential reasoning role and distinguish evidence coverage from accuracy. | **Narration/submission draft delivered. Recommended UI provenance display remains unimplemented** and needs separate approval. |
| **5** | **P1** | Strong technical docs and captures exist; no submission-specific draft, deck or video was present before this pass. | Package one concise value proposition, result-first three-minute video, contradiction/control, actionable result, limitations and reuse attribution. Acceptance: final links work for the intended audience, credentials remain private, claims match preserved evidence and the actual submission form is complete. | **English submission draft and timed script delivered. Owner remaining:** final track/form fields, demo/video links and final recording. No deck/video created or submission sent. |

This is a readiness checklist, not a claim that these changes guarantee first place.
The current product's source-language readiness is positive; the remaining P0 work is
judge handoff/rehearsal and recommended permission-aware UX, not a French translation gap.

## Safely corrected files

All changes are in backend documentation. The frontend was audited read-only.

| File | Change |
| --- | --- |
| [README.md](../../README.md) | Add concrete result-first judge entry and links to submission/audit materials. |
| [docs/README.md](../../README.md) | Index the quickstart, submission draft, English qualification companion and audit. |
| [docs/JUDGE_DEMO.md](../JUDGE_DEMO.md) | Separate judge walkthrough from operator instructions with an opening link. |
| [docs/JUDGE_QUICKSTART.md](../TESTING.md#judge-walkthrough) | New English two-minute walkthrough, permission boundaries, optional live path and labeled fallback. |
| [docs/HACKATHON_SUBMISSION.md](../../README.md) | New English draft, 30-second pitch, timed demonstration and honest claims checklist. |
| [docs/V8_PREPRODUCTION.en.md](../V8_PREPRODUCTION.en.md) | English companion translating the historical French report without modifying it. |
| This report | Findings, audit scope, remaining gaps and five prioritized improvements. |
| [Check summary](ENGLISH_JUDGE_READINESS_CHECKS.json) | Machine-readable local results, preservation checks and scope limits. |

## Local checks and remaining blockers

The accompanying [machine-readable check summary](ENGLISH_JUDGE_READINESS_CHECKS.json)
records the executed checks and integrity comparisons. Documentation link checks cover
local targets only; hosted links and production routes were not contacted. No Java or
frontend application test run is needed for these documentation-only edits. Real-provider
evaluation and browser workflow scripts were deliberately not run because they can
make real Meta calls. The existing qualified JAR was not rebuilt.

Before final submission, the owner still needs to verify the real judge entry URL,
individual account expiry/all-source sharing, completed-result access and no-call
fallback; fill in the chosen track and actual submission/video fields; and rehearse
with the real permission profile. These runtime/portal assets are audit gaps, not
asserted failures. The frontend repository itself was fully accessible for this source
audit. Any later product behavior change or replacement fixture needs separate approval
and its own focused checks. V8's existing deployment/backup/preflight conditions remain
in force; this audit does not authorize or perform deployment.
