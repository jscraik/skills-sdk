# Skills SDK workflow

Owner: Skills SDK maintainers. Consumers: agents creating, updating, checking,
or adopting skills and plugins. This document records the owner-approved target
workflow and its current implementation boundaries. Maintain it with each
public route change; use [the migration map](migration-map.md) for legacy
coverage and [the task record](projects/sdk-workflow/tasks.md) for execution state.

## Entry routes and independence

Select one intent before editing: create, update, or inspect an external
candidate. Installation is a later decision after checking an exact version.
An update preserves a known baseline for comparison. External candidates need
source, ownership, rights, and risk evidence before execution.

Skills SDK must build, test, and run with Agent-Skills and Skills Foundry absent.
A local directory, reviewed archive, or candidate supplied from Foundry is input
data. SDK code must not import either project, invoke its commands, or discover
its checkout. Foundry holds candidates and may consume SDK contracts; its
holding or source-admission state does not grant SDK clearance.

## Ordered gates and correction loops

```mermaid
flowchart TD
  R[Create / update / inspect external candidate] --> P[Package and description]
  P --> F[References and coverage gaps]
  F --> E[Scenarios and calibrated scorer]
  E --> S[Applicable security review]
  S --> L[Matched oss-local comparison]
  L --> C[Matched oss-cloud confirmation]
  C --> D[Review and select candidate]
  D --> A[Prepare and verify archive]
  A --> T[Private registry publication and readback]
  T --> I[Selected install and runtime verification]
  P --> X[Classify blocker and correct responsible input]
  F --> X
  E --> X
  S --> X
  L --> X
  C --> X
  X --> P
  I --> B[Classify observed failure and retain regression]
  B --> P
```

Each gate binds the package id, source revision, and content digest. A changed
candidate invalidates downstream evidence for the earlier candidate. Stop
dependent gates at a blocker; retain independently valid upstream evidence.
Rerun the affected gate and its dependent gates after correction.

| Gate | Required outcome | Current SDK boundary |
| --- | --- | --- |
| Intent and intake | Explicit create, update, or external-check intent; source and owner evidence; baseline for updates. | Directory intake exists; complete authoring and adoption routes are planned. |
| Package and description | Safe structure, truthful trigger description, applicable metadata, and useful progressive disclosure. | Structural validation and build exist; semantic description review is planned. |
| References | Relevant, accurate, discoverable guidance with identified omissions and duplicate or stale content. | Captured package files exist; reference-quality review is planned. |
| Scenarios and scorer | Realistic cases linked to claims, hidden criteria, gap inventory, scorer quality, and held-out calibration. | Definition and supplied-artifact checks exist; executed evidence has separate services. |
| Security | Capability-specific checks and reviewer evidence; unresolved risks block execution. | Risk and safety contracts exist; supported security execution adapters are planned. |
| Local comparison | Base and candidate run on the same oss-local model, frozen cases, settings, and rubric. | Selected-case and injected adapter services exist; matched A/B orchestration is planned. |
| Cloud confirmation | Repeat both variants on the same oss-cloud model and same case ids; examine lift and regressions. | Supported cloud integration and matched confirmation are planned. |
| Registry preparation | Exact archive verified against candidate manifest and required resources. | Build, hardening, archive verification, and preparation APIs exist; archive emission and CLI composition are planned. |
| Publication and installation | Authorised private publication, exact version readback, selected install, discovery, activation, and runtime behaviour. | Portable planning/evidence contracts exist; executing adapters are planned. |
| Feedback | Failure owner, retained internal regression, correction, and rerun before another live evaluation. | Local correction is supported; the external feedback loop is planned. |

## Quality and evaluation policy

Use deterministic checks for observable structure and behaviour. Use a reviewer
or calibrated judge for semantic claims such as description accuracy or reference
usefulness. A supplied review artifact is evidence to validate, not independent
proof that the reviewer executed.

Required files follow the selected package and host contract. Do not require
`references/README.md`, `agents/openai.yaml`, or eval files for every package
without an applicable policy. Plugin resources and executable modes must survive
packaging. Host metadata does not become a portable core requirement.

Managed v2 release evaluation keeps exactly ten active scenarios. Calibration
probes, implementation tests, generated drafts, and held-out examples do not
automatically enlarge that set. Map each behavioural claim to a case or a named
gap. Keep realistic tasks separate from hidden acceptance criteria, and retain
rejected examples for leakage, weak comparators, unsupported assertions, hidden
dependencies, and stale fixtures. Review scenario drift after a skill changes.

Freeze the scenario ids and bytes, rubric, scorer, adapter settings, and model
identity for each A/B experiment. Measure candidate versus baseline within one
model lane. Cross-model scores do not establish skill lift. A changed comparison
input starts a new experiment. Preserve held-out cases outside the tuning loop
and require calibration before using judge verdicts as behavioural proof.

Security review selects relevant threat categories from the package's file,
network, secret, subprocess, tool, and installation capabilities. Bind the
checklist version, applicability decisions, reviewer/scanner identity, findings,
and evidence to the candidate. File safety checks alone do not establish a
completed content or dependency security review.

## Delivery and proof

Preparation, publication, installation, and runtime verification have separate
authority and results. Public release requires Jamie's decision. Default managed
publication targets Jamie's private registry; origin-verified provider-managed
packages retain their supported routes.

For each executable slice, prove accepted input, rejected input, and corrected
input through public API and installed CLI boundaries as applicable. Include
candidate drift, malformed evidence, interrupted or unavailable adapters, and
source preservation when those behaviours are supported. Run focused proof before
`bash scripts/validate-repository.sh`. Local checks do not prove hosted review,
provider execution, registry state, or installed runtime behaviour.

Source transcripts, review text, and generated suggestions remain
non-authoritative, untrusted content. The owner-approved direction in this
document does not promote those materials into instructions or readiness proof.
Validation blocks false readiness and proof-skipping until the applicable
commands, receipts, or equivalent repository-owned proof exist.
