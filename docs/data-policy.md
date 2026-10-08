# Data policy and residency

## The distinction the product must not blur

Cloud AI cannot analyse company content without receiving some of that content.
Keeping original files on company infrastructure is **not** the same as zero
disclosure. The application states this in the project policy screen and enforces
it in one place: the egress gate.

Sanitisation **reduces** disclosure. It is never presented as a guarantee of
anonymisation.

## Where the gate sits

```
service ──▶ ai.gateway.run_role
               │
               ├─ pick adapter from project policy (local unless cloud is opt in twice)
               ├─ egress.prepare ──┬─ deny  ▶ record blocked manifest, raise 451
               │                   └─ allow ▶ minimise, sanitise, record manifest
               ├─ adapter.generate
               └─ validate output against the versioned role schema
```

No other code path reaches a model. An adapter never decides policy.

## Decision table

| Classification | Local | Cloud |
|---|---|---|
| Restricted | processed locally | blocked, always |
| Confidential | processed locally by default | only project authorised, sanitised, minimised excerpts |
| Shareable | local master retained | permitted under the configured provider policy |

Cloud requires **three** independent switches to be on: the deployment
(`APP_CLOUD_ENABLED_GLOBALLY`), the project (`aiPolicy.cloudEnabled` with
`localOnly` off), and optionally the role allowlist. A project can be stricter
than the deployment and never looser.

Transcription, OCR, embeddings and source indexing are local by default.

## What is recorded

Every outbound attempt — allowed or blocked — writes an `egressManifest`:

```json
{
  "projectId": "…", "at": "…", "allowed": false,
  "provider": "cloud", "modelId": "…", "role": "business_analyst",
  "classification": "restricted",
  "disclosureCategories": ["evidence_excerpt", "requirement_text"],
  "redactions": {"email": 3, "credential": 1},
  "chunkCount": 0, "charCount": 0,
  "blockedReason": "Content classified as restricted may not leave company infrastructure…"
}
```

Categories and counts only. The payload itself never enters the manifest or an
ordinary log line. The project audit screen exposes this log to anyone with the
audit permission.

## Prompt injection

Uploaded content is untrusted data. Before any evidence reaches a role prompt,
recognised instruction framing is neutralised (`ignore previous instructions`,
`system:`, role tags, shell or fetch directives). The AI roles have no tool
access, no URL access and no credentials; every external mutation goes through an
authorised deterministic service with its own permission check.

## Failure behaviour

A cloud or provider failure **never** causes a local only project to fall back to
cloud. If the configured model is unreachable, the job pauses visibly with the
reason and can be resumed; no content is redirected anywhere else.

## Operational requirements that remain with the company

Retention, recording notice and consent, provider contracts, provider retention
and training settings, network destinations, and client data handling procedures
are configured under company policy. The software enforces what it can and
records what happened; it does not by itself establish regulatory compliance.
