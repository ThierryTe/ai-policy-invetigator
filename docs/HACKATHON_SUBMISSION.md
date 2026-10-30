# Hackathon submission draft and demo script

Status: English editorial draft for owner review. This is not a submitted entry.
The owner must provide the final demo URL, private judge handoff, video URL, selected
track and the organizer's required submission fields. No working public deployment
or newly recorded video is asserted here.

## Thirty-second product story

“A new security policy requires training before sensitive-system access. An HR
procedure still grants access on day one and allows training later. AI Policy
Investigator uses Meta Muse Spark to compare the policy versions and selected
procedures, surface the potential conflict, and show the exact PDF evidence. An
analyst reviews a proposed action, with the original AI finding and review history
preserved. It turns a policy update into an evidence-backed investigation.”

## Submission description

AI Policy Investigator helps compliance analysts assess the operational impact of
a policy change. Instead of asking a chatbot to summarize documents, analysts select
an immutable baseline, its replacement and one to four procedure versions. Meta Muse
Spark extracts explicit requirements, aligns the changes and assesses potential
contradictions, missing requirements, ambiguities and compatible procedures.

The product presents source-backed explanations, proposed actions and a persisted
impact graph. Every published reference must resolve to authorized source text and
an exact quotation. Analysts can inspect the original PDF page, then confirm, dismiss
or annotate a finding without overwriting the AI output.

The workflow combines current department permissions, forced PostgreSQL row-level
security, explicit external-processing consent, durable asynchronous jobs, bounded
model attempts and human review. Missing access, incomplete processing and provider
errors do not become successful no-conflict results. These controls support a
credible enterprise workflow; they do not establish general AI accuracy or certify
legal compliance.

## Why Meta is essential

Meta `muse-spark-1.3` performs structured requirement extraction, policy-change
alignment and scoped procedure comparison through the backend's Meta Model API
transport. It is responsible for the interpretation displayed in the findings.
The application validates schemas, citations and model identity and records
model/prompt/schema provenance and reported usage. Local all-MiniLM-L6-v2 ONNX
embeddings support retrieval and do not replace Meta reasoning.

The repository retains sanitized [real API preflight evidence](verification/meta-api-preflight.json),
a [real investigation](verification/phase3-demo.json) and
[evaluation evidence](EVALUATION.md). These are historical runs, not newly executed
claims about service availability. Deterministic regression tests use mocked Meta.

## Differentiation to demonstrate

| Capability | What a judge can inspect |
| --- | --- |
| Policy-change investigation | Baseline → replacement → selected procedures, rather than a free-form summary |
| Scope-sensitive reasoning | A contradiction and a compatible control in the same synthetic scenario |
| Verifiable evidence | Exact source quotations, page references and original PDF bytes |
| Human accountability | Original AI output retained beside append-only review decisions |
| Access-aware processing | Shared synthetic sources stay READ-only; each judge has an isolated private workspace |
| Honest failure handling | Durable progress, bounded retries, PARTIAL/FAILED states and explicit limitations |

These are demonstrated product characteristics, not claims of exclusive market
novelty. Reused infrastructure is disclosed in
[contribution provenance](provenance/HACKATHON_CONTRIBUTIONS.md).

## Suggested three-minute demonstration

| Time | Action | Narration / evidence |
| --- | --- | --- |
| 0:00–0:25 | Open the prepared completed investigation | State the training-before-access change and the day-one-access problem. Identify this as an earlier real Meta run. |
| 0:25–0:55 | Select the contradiction | Read AI explanation and Suggested action; describe the proposed operational correction. |
| 0:55–1:30 | Open Evidence and View PDF | Show policy and HR quotes with page references. A matching quote verifies provenance, not interpretation. |
| 1:30–1:55 | Select the compatible control and focus the graph | Explain why access gated by training is compatible within the selected scope. |
| 1:55–2:20 | Open History | Show retained analyst decisions. Shared judge accounts cannot review the source department's findings; use existing history or an authorized presenter-owned scenario. |
| 2:20–2:45 | Explain the Meta pipeline and usage | Muse Spark extracts, aligns and compares; local embeddings retrieve; server validates; calls/tokens are reported separately from source coverage. |
| 2:45–3:00 | Close with scope and limitations | One to four selected procedures, human review, honest incomplete states and disclosed small-sample evaluation. |

Optional interactive extension: run a fresh investigation only after the operator
verifies account expiry, source consent and budgets. Keep the completed-result tab
available. If the fresh request is slow, return to the earlier result and label it
accurately. If the site is unavailable, use local copies of the historical screenshots
and sanitized evidence. No replay should be presented as a current live result.

## Evidence and claims to preserve

- The recorded browser run reported five calls and 40,605 ms **summed metered provider
  latency**. It is one historical observation, not an end-to-end latency guarantee.
- The initial ten-case evaluation matched **6/10**, including four processing errors.
  A separate four-case retry matched **3/4** and included one false positive.
- **119/119** verified citation instances across those evaluation runs establish
  source/quote matches, not 100% reasoning accuracy.
- The V7 → V8 qualification is GO under the owner's option A: private WRITE allowed,
  shared sources READ-only. Local qualification is not proof of a deployed release.
- Do not claim autonomous remediation, enterprise-wide procedure discovery,
  legal/compliance certification or an unmeasured time-saving percentage.

## Owner's final submission checklist

- [ ] Confirm the accepted track, eligibility/reuse requirements and actual form
  requirements against the current [official event information](https://dev.meta.ai/events/global-hackathon)
  and the accepted Official Rules. The public overview is not the full rulebook.
- [ ] Provide the tested demo URL and individual judge access through the designated
  private channel, including a completed-investigation link and access expiry.
- [ ] Provide the final video URL and repository URLs; check the links in a fresh,
  authorized browser session. Avoid password, token and private-document captures.
- [ ] Rehearse the two-minute judge path with the actual judge permission profile,
  including the PDF viewer, shared-source WRITE denial and source consent.
- [ ] Prepare the honestly labeled completed-result fallback and local screenshots.
- [ ] Keep evaluation limitations and reuse attribution visible. Recheck that the
  final images correspond to the qualified sources and migrations before any release.
