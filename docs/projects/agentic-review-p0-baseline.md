# Skills SDK review pilot: P0 baseline

P0 is complete as a read-only baseline and candidate selection. P1 has not
started. Observed 16 October 2026; final selected-head readback at 17:52 UTC.
This is not a review approval, CI pass, or merge-readiness receipt.

## First PR selected

[PR 63: Prototype: machine-readable CLI route capabilities](https://github.com/jscraik/skills-sdk/pull/63)
is the first pilot candidate. It remains a draft; no review request or state
change was sent.

| Binding | Observed value |
| --- | --- |
| Repository | `jscraik/skills-sdk` |
| Base and trusted repository-policy revision | `d1cd2958122bbc67fbbfd96b3294700f2dc97560` |
| Selected head | `91ab3cfd39024d34d9ab8cf64fd3d25f27ca497d` |
| Existing formal CodeRabbit review revision | `0f197d329adb7cc515fcb8a78f94145b31b861cf` |
| Scope | Nine files; 254 additions and 31 deletions |
| Intended behavior | Classify CLI route capabilities; reserved discovery routes return exit 3 with a diagnostic; strengthen dependency-direction checks. |

This is smaller than open PR 62, which had 24 changed files, 3,864 additions
and 93 deletions at capture. PR 62 is an active normalization implementation
with changing evidence; it is not adopted as additional pilot implementation
scope. PR 63 supplies bounded CLI and architecture questions, two reference
findings, a failed metadata check, and a useful stale-review comparison.

Selected files:

- `docs/cli.md`
- `scripts/check_repository_standards.py`
- `src/skills_sdk/cli/__init__.py`
- `src/skills_sdk/cli/main.py`
- `src/skills_sdk/cli/routes.py`
- `tests/test_cli_help.py`
- `tests/test_cli_route_capabilities.py`
- `tests/test_skill_package_cli.py`
- `tests/test_skill_validation_architecture.py`

## Existing integrations: observed activity and limits

| Integration | Directly observed | Pilot disposition |
| --- | --- | --- |
| CodeRabbit | Authenticated bot reviews, inline findings and conversation summaries. PR 63 has a green status, one earlier-revision formal review and a later delta summary for three files. | Primary incumbent review source. Reuse its existing output before adding a service. A green status or three-file delta summary is not full current-candidate clearance. Effective organization settings and future allowance remain unverified. |
| Codex connector | Authenticated historical SDK review submissions, inline findings, completion summaries and a usage-limit response on PR 55. No Codex review was observed on PR 63 in the captured review/comment inventory. | Existing secondary comparison source. Not invoked in this pilot. Historical quota failure is an example, not a claim about current available quota. |
| GitHub Actions | PR 63 current-head `validate` check failed. The failed log identifies the PR-template stage, before the repository validation phases. | Existing mechanical baseline. Do not report source tests failed or passed from this early metadata failure. |
| Semgrep | Current-head `semgrep-cloud-platform/scan` check concluded success; check app slug identifies the existing integration. | Retain its own scanner lane. Check success does not prove exhaustive security coverage. Scanner policy and scan contents were not audited. |
| Socket | Current-head Project Report and Pull Request Alerts checks concluded success. | Retain dependency/security observations separately from review approval. |
| Tessl reviewer | No Tessl review/check appeared in the captured seven-PR sample. No repository-root Tessl review configuration was listed on main. | Not selected. This is absence of observed evidence, not proof the account has no Tessl installation. No installation or paid run is needed for P0. |
| Workstation readiness controls | Local projected readiness and review-request helpers, plus Git/release instructions, were inspected and hashed. They require current-head evidence and the applicable independent-review quorum. | Preserve these controls. They are separate from hosted GitHub enforcement and are not portable SDK-core behavior. No passing readiness receipt was produced. |

The primary evidence for PR 63 is its
[CodeRabbit review](https://github.com/jscraik/skills-sdk/pull/63#pullrequestreview-5551171864),
[later conversation summary](https://github.com/jscraik/skills-sdk/pull/63#issuecomment-6220702340)
and [failed validate job](https://github.com/jscraik/skills-sdk/actions/runs/38938071775/job/117098470610).
The summary explicitly describes reviewing the delta from the earlier revision
to the selected head; it does not replace an adjudication of existing findings.

## Starting findings and failure cases

The two findings below are reference claims from the existing reviewer, not
new independently reproduced defects. GitHub reports both threads unresolved
and not outdated. Their original review revision is the earlier commit above;
GitHub's current comment commit location must not be mistaken for a fresh review.

| Reference | Claim to adjudicate against the selected head | P1 evidence needed |
| --- | --- | --- |
| [Architecture prefix gap](https://github.com/jscraik/skills-sdk/pull/63#discussion_r4297279466) | Dependency rules may reject `skills_sdk.host` but permit `skills_sdk.host_adapters` in portable/distribution layers. | Inspect actual prefix matching and execute an isolated rejected/allowed import pair. |
| [Incomplete CLI invocation](https://github.com/jscraik/skills-sdk/pull/63#discussion_r4297279474) | Missing top-level or Tessl subcommands may return exit 3 without a diagnostic instead of a usage error. | Execute the selected CLI for missing commands and named discovery routes; capture exact output and exit codes. |

The hosted template failure reports six classes: missing concrete reasons for
Provider impact, Runtime impact, Distribution impact, Update readiness and
Codex, plus an unchecked body-refresh checklist item without Pending/N/A.
The PR body also claims required validation passed while reporting its aggregate
command blocked; that inconsistency is a pilot triage input, not an instruction
to alter the body during P0. Metadata repair, code repair, and reviewer requests
retain their existing separate governed routes.

## Hosted rules versus operator policy

The classic branch-protection endpoint returns HTTP 404. That does not mean
main is unprotected: the effective branch-rules endpoint and active
[protect ruleset](https://github.com/jscraik/skills-sdk/rules/21647755) were read
successfully. They include PR use, deletion/force-push restrictions, linear
history, code-quality and code-coverage rules. Stale-review dismissal is on.

The captured effective rules do not include a named required-status-check rule.
Required approving-review count is zero, code-owner review is off, and required
thread resolution is off. No bypass actors were listed. Consequently, the
workstation's stronger CI/review/thread requirements must not be represented
as hosted branch enforcement. The baseline records this difference; it changes
no rules and makes no claim that a merge would be permitted.

## Five historical comparisons

These merged PRs provide different comparison cases. Each raw packet records
full base/head identifiers, reviews, inline comments, conversation, changed
files, head checks and statuses. Reference findings still need adjudication
before they become a scoring answer key. A merged state is not proof a finding
was fixed or a review was valid.

| PR | Captured final head | Baseline role and reference |
| --- | --- | --- |
| [61: Authoring contract](https://github.com/jscraik/skills-sdk/pull/61) | `c22e52799cc2e22fba3233d197b53ecfde49c331` | Documentation/governance; [gate-to-command links](https://github.com/jscraik/skills-sdk/pull/61#discussion_r4252526786), originally reviewed at `2ebabf2d8976c9ee4dd3c55eaeb803ceeeb9b7c6`. |
| [60: Presentation approvals](https://github.com/jscraik/skills-sdk/pull/60) | `ff4d6162a18768ef38d9fbb14861f9777de6547b` | Contract boundary; [minimum SVG viewBox claim](https://github.com/jscraik/skills-sdk/pull/60#discussion_r4246888341), originally reviewed at that final head. |
| [58: Validation performance](https://github.com/jscraik/skills-sdk/pull/58) | `07071a946bd01832edb953a5234a0b0a13053083` | Validation coverage; [docs-only tests gap](https://github.com/jscraik/skills-sdk/pull/58#discussion_r4242543450), originally reviewed at `360baeefd64cc7a4d806d3230edf26a9745c9093`. |
| [55: Calibration lifetime](https://github.com/jscraik/skills-sdk/pull/55) | `4d2983a709520925e1e26472e5189a0f15f434dc` | Completion-summary/no-inline-review layout and [quota-response handling](https://github.com/jscraik/skills-sdk/pull/55#issuecomment-6100449550). No formal reviews or inline comments in the captured lists; this is not automatically a clean-review control. Code and security summaries describe different revisions. |
| [47: Offline content review](https://github.com/jscraik/skills-sdk/pull/47) | `fc8f4c046303c873c9c666e947a48db607c4e0db` | Longer review/repair sequence; [CLI inventory drift](https://github.com/jscraik/skills-sdk/pull/47#discussion_r4211281212), originally reviewed at `90bea1376c8e8cc03a7b3bcfc113492e11c9f79f`. |

## Trusted inputs and execution packet

Use the base revision above for the pilot's standards: AGENTS, CODESTYLE,
CONTRIBUTING, ARCHITECTURE, PR template, trusted template validator and validation
workflow. The ignored local baseline records their SHA-256 hashes and hashes
of the inspected projected operator controls. Candidate edits to the standards
checker are review data; they cannot silently redefine approval policy.

The first P1 pass should apply the three perspectives from the
[pilot plan](agentic-review-pilot.md#p1-run-focused-review-in-shadow-mode):
contract correctness, security/evidence integrity, and architecture/operational
failure. Judge the nine-file scope at the selected head. Preserve existing
review findings and test missing-command, discovery-route and forbidden-import
behavior. A changed PR head requires a fresh snapshot and explicit coverage
reconciliation before claiming current coverage.

Primary means the first evidence source, not a reduced approval quorum. If the
existing risk classifier requires both CodeRabbit and Codex, preserve that
requirement; a shadow-mode result does not replace it.

Start in shadow mode, with one selected-head review and one post-repair rerun;
stop after two repair rounds for human triage. P0 spent no model-review runs
and requested no external messages. No paid execution is selected; provider
cost and quota must be established before a new run that can consume them.
Any GitHub review request requires explicit authority and the normal inspection
receipt/helper route. Do not mark the draft ready merely to trigger a service.

Raw generated packets, provider text, logs and machine baseline are retained
under the Git-ignored `.tmp/agentic-review-p0-20261016/`. They are local evidence,
not public SDK contracts or committed fixtures. The sanitized references and
decision in this document remain suitable for source control. Exact API
commands, timestamps, failures and response hashes are in the capture records.

## P0 acceptance and handoff

- Existing reviewer, scanner and CI activity: inspected through live GitHub reads.
- First bounded PR: selected, pinned, and head read back unchanged.
- Five historical comparisons: selected with exact base/head and reference inventory.
- Trusted policy input: pinned and hashed; no new runtime lens or policy installed.
- Current CI, thread and review boundaries: recorded, including metadata failure,
  two unresolved threads and the absence of claimed full-head clearance.
- External changes: none. No push, PR edit, review request, comment, rule change,
  installation, model run or merge was performed.

P1 remains unstarted. Its first action is selected-head code inspection and
adjudication of the two reference findings in an isolated checkout, followed by
the selected authorized independent-review path. Full CI and review clearance
are not prerequisites for recording P0, and P0 does not waive them for delivery.
