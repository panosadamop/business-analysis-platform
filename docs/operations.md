# Operations

## Installation

1. `cp .env.example .env` and set at least `APP_JWT_SECRET` and
   `APP_S3_SECRET_KEY` to long random values.
2. `docker compose up -d --build`.
3. `docker compose run --rm seed` to create the reference project, or create the
   first administrator yourself through `POST /api/v1/admin/users` from an
   existing administrator account.
4. Put the company reverse proxy or TLS terminator in front of the `web` service.
   Nothing else is published: database, object store and inference ports bind to
   localhost.

A single host installation is not high availability.

## Upgrade

```bash
git pull
docker compose build
docker compose up -d
docker compose logs -f api worker
```

Indexes are created idempotently on API start. MongoDB schema validation is
`moderate`, so an older document is never rejected on read; new writes must
satisfy the validator.

## Rollback

Images are rebuilt from a tagged source tree, so rollback is redeploying the
previous tag. Approved artifact versions are immutable and additive, so a
rollback of application code never rewrites approval history.

## Backup and restore

Back up three things together, from the same point in time:

| What | How |
|---|---|
| MongoDB | `docker compose exec mongo mongodump --archive=/data/db/backup.gz --gzip` |
| Object storage | mirror the MinIO `data` volume or the bucket |
| Secrets | `APP_JWT_SECRET` (connector credentials are encrypted with a key derived from it) |

Restore drill expectations (AT-18): source, version and approval links and the
external mappings stay coherent, and the retrieval index is rebuildable from the
authoritative sources — it is derived data and is never the system of record.

Proposed initial objectives are RPO ≤ 24 hours and RTO ≤ 8 hours; both are proven
by restore drills, not by backup job success.

## Scaling

* `docker compose up -d --scale worker=3` for more background throughput.
* Analysis jobs are the memory hungry ones; the worker has a 4 GB limit by default.
* With a local inference service, benchmark model specific RAM and VRAM and
  throughput before buying hardware. CPU only mode works at reduced throughput.

## Observability

* `GET /health` is a liveness probe, `GET /ready` checks the database.
* Every response carries `X-Correlation-Id`; logs include it and deliberately
  exclude raw recordings, document text, secrets and prompts.
* `GET /api/v1/admin/jobs` lists queue state; stale running jobs are requeued
  automatically after 30 minutes.
* `GET /api/v1/projects/{id}/audit` and `/egress` expose the per project audit
  and outbound policy logs.

## Routine jobs

| Job | Cadence | Purpose |
|---|---|---|
| `outbox_scan` | every minute | promote due connector publications |
| `sync` | on demand or scheduled | poll a connector for remote changes |
| `snapshot` | daily at 01:00 | store the daily metric snapshot used by historical charts |
| calibration candidate | manual | offline estimate calibration with holdout evaluation |

## Security posture

* Containers run as a non root user; no model weights, credentials or client data
  are baked into images.
* Connector credentials are encrypted at rest with a key derived from
  `APP_JWT_SECRET` and are referenced by id everywhere else.
* Webhook receivers verify provider signatures and reject anything unverified;
  for company hosted deployments polling is the default so no inbound port is
  required.
* Public anonymous sharing is disabled; client access is authenticated, expiring
  and revocable.

## Known operational limits

* Legacy `.doc` conversion and local OCR need worker images that are not bundled;
  until they are configured, those files are stored and reported as unsupported
  rather than treated as analysed.
* Multi destination connector routing is single primary by default; enabling more
  than one destination requires explicit field ownership to avoid feedback loops.
