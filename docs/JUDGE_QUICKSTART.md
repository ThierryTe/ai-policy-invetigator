# Judge quickstart

**A policy changes. Which procedures now need attention, and what is the evidence?**
AI Policy Investigator compares a baseline policy, its replacement and selected
procedures. Meta Muse Spark extracts requirements and assesses potential conflicts;
the application verifies citations and keeps the final decision with a human reviewer.

## Start with the result — about two minutes

Use the **completed investigation link supplied with your individual judge account**.
Sign in when prompted. The link has the form `/investigations/<investigation-id>`.
Credentials and the actual link are supplied privately by the project owner; there
is no public default password. If you have not received both, request them before
starting. Opening an existing result does not start a new Meta request.

1. **Understand the change.** The synthetic baseline allows security training within
   30 days after access. The replacement requires training **before sensitive-system
   access**. The selected HR procedures show two contrasting approaches.
2. **Inspect the potential contradiction.** In **Findings**, select **Contradiction**.
   Read **AI explanation**: one HR procedure grants sensitive access on day one while
   allowing later training. Read **Suggested action** for the proposed correction.
   This is a finding for human review, not an automatic policy edit.
3. **Check the evidence.** Open the finding's **Evidence** tab or the **Evidence excerpts**
   section. Compare the quoted policy and HR passages, then choose **View PDF** to
   inspect the original page. The graph connects the persisted documents,
   requirements and findings. Use **Focus finding**, **Expand** or **100%** if needed.
4. **Inspect the control.** Select **No conflict**. The compatible HR procedure withholds
   sensitive access until training is complete. This illustrates scope-sensitive
   comparison rather than flagging every textual difference.
5. **See the human decision.** Open **History** to inspect any recorded review actions.
   A badge such as **Dismissed** describes a human decision, while **Contradiction**
   remains the original AI classification. The two records are intentionally separate.

The recorded demonstration found both outcomes. Inspect the actual selected run;
fresh model output is not guaranteed to match it. **Evidence coverage** measures source
coverage, not AI accuracy. A verified quotation does not prove the interpretation.

## Your account's permissions

- **Shared synthetic scenario:** you may read the authorized documents, PDFs,
  findings, evidence and graph. You cannot edit these documents, append versions,
  change processing consent or review the source department's findings.
- **Your private department:** you may upload and version your own synthetic PDFs,
  explicitly allow external processing, and investigate them within your limits.
  Your documents are isolated from other judges' private departments.
- **New analysis of shared sources:** V8 permits an active judge to start an
  investigation of already authorized, indexed and consented shared versions.
  Analysis does not grant document WRITE access. It consumes investigation and
  model-attempt allowances, including retries.

The current interface may display **New version** or **Upload new version** on shared
documents because its button visibility uses your account-level upload capability.
The server still rejects the write. For the result walkthrough, stay on the supplied
investigation and use its read controls. **Confirm**, **Dismiss** and **Add note**
require review permission in the policy's owning department; these are not part of
the shared-scenario judge walkthrough. To demonstrate writing or review, the presenter
must use an authorized private scenario or a previously recorded analyst review.

## Optional live analysis

Use **Investigations → Run investigation** only when the presenter has confirmed
model availability and your remaining allowance. Select the prepared policy's
baseline and direct replacement, the two indexed procedures, and an analysis date
on or after **2026-10-27**, matching every selected version's effective date. Select
only sources for which external processing is already allowed.

The result page reports persisted stages, calls and reported tokens. Keep the URL.
**PARTIAL**, **FAILED**, or an incomplete-processing notice is not a successful
no-conflict assessment. Avoid repeatedly starting jobs after an error: a new request
can consume quota, and a previous timeout may already have consumed a model attempt.

## If the live request is slow or unavailable

After about **20 seconds**, switch the presentation to the separate, already completed
investigation. This is a suggested presentation cue, not an application timeout or
a promise about latency. Say: **“This earlier completed run used real Meta inference;
we can inspect its stored evidence while the new request finishes.”** Do not call it
the output of the current request. Existing authorized reads need no new inference.

If the application itself is unavailable, use the recorded
[desktop investigation](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/desktop-fitted-investigation.png),
[mobile investigation](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/mobile-fitted-investigation.png)
and [original PDF view](https://github.com/ThierryTe/ai-policy-invetigator-frontend/blob/main/docs/screenshots/pdf-real-source.png).
These are historical local captures, not evidence of current production availability.
The presenter should have local copies ready; hosted links were not checked in this audit.

Reloading the page requires sign-in again because authentication is stored only in
memory. Investigation URLs remain usable subject to current access. The recent list
contains work created in this session, so a missing recent entry does not mean the
stored investigation was deleted. For a 401, sign in again; for a 403/404 or expiration,
ask the presenter to verify your account and all-source sharing. Do not bypass access
controls. A generic 429 can indicate a persistent quota, not a short cooldown.

## How Meta is used

The backend sends authorized, explicitly consented source excerpts to the Meta Model
API using `muse-spark-1.3`. It requests structured requirements, aligns policy versions
and compares selected procedures. Local ONNX embeddings support retrieval; they are
separate from Meta reasoning. The server checks response schemas, model identity,
source IDs and exact quotations before publishing results.

[Recorded real-inference evidence](verification/phase3-demo.json) and
[evaluation results and limitations](EVALUATION.md) distinguish real model runs from
mocked regression tests. The ten-case evaluation matched 6/10 expected outcomes with
four processing errors. A separate exception retry matched 3/4, including one false
positive; it did not replace the original failures. No general accuracy or compliance
guarantee is claimed.

Operators: prepare individual accounts, exact source sharing, a completed-result link
and bounded access using [Interactive judge access](JUDGE_DEMO.md). This quickstart does
not provision accounts, deploy the application or make a model request.
