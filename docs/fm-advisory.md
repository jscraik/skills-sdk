# Optional Apple FM advisory

`skills-sdk advise-fm` is an explicit, optional check using Apple's on-device
Foundation Model through `/usr/bin/fm`. It is a local delivery candidate, not
an accepted release or a calibrated SDK acceptance judge.

The check returns a separate `fm-advisory/v1` result. It never feeds validation,
build, quality, calibration, publication or installation decisions. A finding
does not deny acceptance, and no finding does not grant it. Those routes do not
call FM automatically. The source candidate and snapshot binding are supplied
by the caller; this check does not authenticate their relationship or claim
that a response was produced by an executed provider.

## Run an advisory

Create a request from the exact candidate and source snapshots you intend to
review. Include every required policy, exception list or reference in
`required_context`; the SDK cannot infer undeclared dependencies.

```json
{
  "schema_version": "fm-advisory-request/v1",
  "candidate": {
    "package_id": "example",
    "source_revision": "1111111111111111111111111111111111111111",
    "content_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "kind": "contradiction",
  "assertion": "The description and instructions must be mutually consistent.",
  "required_context": ["description", "instructions", "policy"],
  "documents": [
    {"document_id": "description", "role": "specification", "text": "Read files without changing them."},
    {"document_id": "instructions", "role": "response", "text": "Overwrite the original file."},
    {"document_id": "policy", "role": "specification", "text": "This check permits no writes."}
  ]
}
```

The example identity is synthetic; replace it with the actual checked identity.
For `kind: semantic`, supply one assertion, reference facts as specification
documents and the actual response snapshot as a response document.

```bash
skills-sdk advise-fm --request advisory-request.json --json
```

Omitting a required document returns `status: skipped` and
`reason: missing_required_context` before any FM or availability call. Missing
specification or response roles also skip. An empty, duplicate or malformed
document is invalid input, rather than a completed review. Whitespace in valid
source snapshots is preserved. The check never discovers files, fetches missing
references or changes the package.

Requests are limited to 16 KiB of canonical JSON, 12,000 UTF-8 source bytes,
128 source lines and 32 documents. The request file itself is limited to
16 KiB and read through the CLI's existing regular-file, no-symlink boundary.
The executable adapter requires macOS and `/usr/bin/fm`. It checks that the
default custom provider is absent before sending source text. It explicitly
selects `system`, never PCC or another provider, and never changes FM settings.
The preflight is not an atomic lock against concurrent host configuration
changes; callers must keep their trusted FM configuration stable during a run.

## Results and exit codes

`status: completed` carries `judgement: finding`, `no_finding` or
`insufficient_evidence`. Other statuses are `skipped`, `unavailable` and `error`;
they have a typed reason and no judgement. Every result sets
`advisory_only: true`, `acceptance_authorized: false` and
`source_binding: caller_supplied`. It binds the request digest and supplied
candidate identity. Evidence names a supplied document, line and line digest;
the result does not copy the source quotation. Explanations can still contain
sensitive source facts; keep advisory results private when reviewing private
material. Credential-shaped and machine-specific explanations are rejected.

| Exit | Meaning |
| --- | --- |
| `0` | Advisory completed or required context skipped; finding and no finding both use `0`. |
| `2` | Invalid request, execution failure, timeout or invalid model output. |
| `3` | Unsupported host, missing FM executable or configured custom provider. |

These exits describe this optional operation, not SDK acceptance. Run it as a
separate diagnostic step and retain its output separately from gate receipts.
Capture JSON output using the caller's private logging destination. The SDK
does not retain raw prompts, raw model output or stderr as persistent logs.
Transient schema files are outside the package and removed after the call.

`--timeout-seconds` accepts a value greater than zero and at most 30. The
deadline covers provider preflight and generation. The existing SDK supervised
transport terminates the owned process group and allows up to five seconds
for cleanup. Cancellation propagates after bounded cleanup. No automatic retry
runs, and partial or malformed output never becomes a judgement.

## Python and schema boundaries

```python
from skills_sdk.models import FMAdvisoryRequest
from skills_sdk.providers.fm_advisory import advise_with_fm

request = FMAdvisoryRequest.model_validate(payload)
result = await advise_with_fm(request, timeout_seconds=30)
```

`SchemaRegistry` provides `fm-advisory-request.v1` and `fm-advisory.v1`.
Structural JSON schemas bound field shapes; registered model validation also
checks UTF-8 workload limits, duplicate document IDs, state relationships and
public-safe explanations. Source-reference meaning is verified only against
the supplied request during execution, not by a standalone result schema.
Unknown or duplicate evidence IDs are rejected rather than silently repaired.

The pilot found plausible contradictions, but also false alarms and incorrect
missing-context decisions. A valid source reference does not prove that the
model's interpretation is correct. Greedy sampling is not recorded as a numeric
temperature, and a system-model label is not an authenticated weights digest.
Human calibration and all existing acceptance requirements remain separate.
