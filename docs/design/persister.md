# Persister and Postgres schema — design note

**Date:** 2026-05-13  
**Status:** draft  
**Implements:** [ADR-0003](../04_DECISION_LOG.md#adr-0003--modular-monolith-with-split-ready-seams), [ADR-0006](../04_DECISION_LOG.md#adr-0006--postgres-first-storage)  
**Related:** [Architecture §6–8](../01_ARCHITECTURE.md#6-stix-21-mechanics) · [Connector runtime](connector-runtime.md) · [Connector protocol](connector-protocol.md) · [`src/prow/connectors/kev/`](../../src/prow/connectors/kev/)

---

## Goals

- Persist STIX bundles produced by connectors to Postgres durably, in a single transaction per emit, with deterministic deduplication and explicit acknowledgement semantics back to the supervisor.
- Treat `raw jsonb` as the authoritative representation of every object; derived columns, generated fields, and indexes must be reproducible from `raw` (and the few immutable provenance columns) so future re-indexing passes remain possible without guessing ingest-time behavior.
- Expose storage through repository protocols under `prow.db.repositories`, with Postgres-specific SQLAlchemy 2.0 + asyncpg implementations isolated under `prow.db.postgres`, preserving the import-linter split-readiness contract from ADR-0003.
- Handle KEV-scale bundles (on the order of four to five thousand STIX objects in one `EmitPayload`) with predictable memory use, batched SQL writes, and connector-visible counts in `EmitAckPayload` that match what actually landed.
- Make every schema change a forward-only Alembic revision from day one; never hand-edit a shipped migration — roll forward with a new revision.
- Preserve provenance needed for later federation and multi-connector installs: immutable `source_connector_instance_id`, `ingested_at`, and the original marking references as stored in `raw`, with a practical denormalization for object-level markings only.

## Non-goals

- **Not a query language or HTTP API.** The persister writes; readers are repository methods consumed by the API layer later, not raw SQL from route handlers.
- **Not the connector framework.** Production wiring passes the persister as the supervisor’s `emit_handler` and backs state handlers with `connector_state`; the persister does not spawn connectors or interpret manifests.
- **Not the federation layer.** TAXII 2.1 client and server sit above this storage at v1.0; the persister only ensures ingested data is faithful and indexed enough for a future TAXII surface to enumerate.
- **Not the large-scale search tier.** OpenSearch remains the optional FTS backend per ADR-0006. v0.1 search posture is Postgres `tsvector` plus `pg_trgm` only.
- **Not a cross-feed entity-resolution or “same real-world CVE” policy engine.** Object-level deduplication follows STIX identity and versioning rules; merging two different STIX IDs that “mean” the same vulnerability is out of scope until a dedicated enrichment or resolution pass exists.

## Schema design

Postgres 16 is assumed, with extensions `pg_trgm` enabled for fuzzy name lookup and `tsvector` generated columns for full-text search. Numeric and textual column choices below are logical types; exact Alembic and SQLAlchemy declarations belong to Pass A.

### 1. `stix_objects` — canonical object store

One row per ingested STIX object (SDOs, SROs including `relationship`, and SCOs). Versioned STIX objects can legitimately share a STIX `id` with different `modified` timestamps; SCOs are not versioned and have no `modified` in the wire format the project targets for observables.

**SCOs vs SDOs / SROs — chosen shape:** keep a **single** `stix_objects` table with `modified timestamptz NULL` for SCO rows. Do **not** split SCOs into a parallel `stix_scos` table for v0.1. Rationale: one repository and one upsert code path matches how connectors already emit mixed bundles (KEV ships vulnerabilities, indicators, relationships, and observables together); the API’s “fetch object by id” story stays simple for the unversioned case; and ADR-0006’s “jsonb is truth” argument applies uniformly. The price is constraint gymnastics: a naive composite primary key on `(id, modified)` is wrong because Postgres treats `NULL` as distinct under uniqueness, which would allow multiple SCO rows for the same `id`.

**Resolution:** add a surrogate **`row_id bigserial PRIMARY KEY`** (internal-only, never exposed as STIX identity). Enforce business keys with **partial unique indexes**:

- Versioned objects: `UNIQUE (id, modified) WHERE modified IS NOT NULL`.
- SCOs: `UNIQUE (id) WHERE modified IS NULL`.

All foreign references from satellite tables to `stix_objects` should reference `row_id` where a hard FK is required, while still storing the STIX `id` as text for human queries and STIX-native joins. Soft references such as `created_by_ref` remain plain text without FK enforcement because ingest order is not guaranteed.

**Columns:**

| Column | Type | Notes |
|--------|------|--------|
| `row_id` | `bigserial` | Surrogate primary key. |
| `id` | `text` | STIX `id`. Not unique alone for versioned types. |
| `type` | `text` | STIX `type` (`indicator`, `vulnerability`, `ipv4-addr`, …). |
| `spec_version` | `text` | Always `'2.1'` for v0.1 rows. |
| `created` | `timestamptz` | From object; required. |
| `modified` | `timestamptz` | Required for SDOs and SROs; **NULL** for SCOs. |
| `created_by_ref` | `text` | Nullable soft reference. |
| `revoked` | `boolean` | `NOT NULL`, default `false`. |
| `confidence` | `smallint` | Nullable; 0–100 when present. |
| `source_connector_instance_id` | `text` | `NOT NULL`; provenance, immutable after insert. |
| `ingested_at` | `timestamptz` | `NOT NULL`, server default `now()` at insert time; immutable. |
| `raw` | `jsonb` | `NOT NULL`; full object exactly as validated for persistence. |
| `search_text` | `tsvector` | Stored generated column for FTS (expression below). |

**`search_text` generated column (stored):** build a document string by concatenating, with spaces, the `name` string, the `description` string, and all `labels` entries from `raw`. Concretely (conceptually, not final SQL): `coalesce(raw->>'name','') || ' ' || coalesce(raw->>'description','') || ' ' || coalesce(labels aggregated as text from raw->'labels', '')`, then wrap with `to_tsvector('simple', …)` so stemming language choice does not fight mixed CTI strings. The implementation pass should keep the expression immutable per Postgres rules.

**Indexes on `stix_objects`:**

- B-tree on `(type)` for type-filtered listing.
- B-tree on `(source_connector_instance_id)` for per-connector inventories.
- B-tree on `(ingested_at)` for time-windowed feeds and incident timelines.
- GIN on `(search_text)` for FTS.
- `pg_trgm` GIN on `lower(raw->>'name')` for fuzzy title lookup (matches architecture’s “name” orientation; CVE strings and malware names live here for many types).
- **Expression / JSONB path indexes (v0.1 hot paths):**
  - **Indicators:** btree or hash on `((raw->'pattern'))` is the wrong shape for STIX patterns; ship a btree on a **hash of the pattern string** *or* a functional btree on `raw->>'pattern'` capped to pattern-length limits — exact choice is implementation detail, but the design target is “lookup by exact pattern string” for dedup/debug, not full pattern language search.
  - **Vulnerabilities:** btree on `lower(raw->>'name')` (CVE token is the common case).
  - **Malware:** btree on `lower(raw->>'name')`.

Optional covering indexes for the API’s first list screens can wait until query shapes exist; do not add them speculatively in Pass A.

### 2. `stix_relationships` — denormalized edges

Fast graph traversal and triple-keyed deduplication without parsing `raw` on every hop.

| Column | Type | Notes |
|--------|------|--------|
| `id` | `text` | STIX relationship `id` — primary key here is acceptable because relationship objects are versioned SDOs/SROs with their own identity. |
| `source_ref` | `text` | `NOT NULL`, indexed. |
| `target_ref` | `text` | `NOT NULL`, indexed. |
| `relationship_type` | `text` | `NOT NULL`, indexed. |
| `created` | `timestamptz` | `NOT NULL`. |
| `modified` | `timestamptz` | `NOT NULL` (relationships are versioned like other SROs). |
| `revoked` | `boolean` | `NOT NULL`, default `false`. |
| `confidence` | `smallint` | Nullable. |
| `source_connector_instance_id` | `text` | `NOT NULL`. |
| `ingested_at` | `timestamptz` | `NOT NULL`. |

**Semantic uniqueness (“triple”) — chosen rule:** enforce **global** uniqueness on `(source_ref, relationship_type, target_ref)` **across all connectors**, regardless of `source_connector_instance_id`. If a second connector emits a different STIX `id` for the same triple, the persister classifies the incoming row as a **duplicate** for acknowledgement purposes and does not insert a conflicting edge. Rationale: STIX graph edges are statements about world objects; duplicating the same edge under different STIX IDs creates useless parallel universes in the small-tier graph store. If a future product decision needs per-connector parallel edges, that becomes an explicit schema and API change.

**Indexes:** composite btree on `(source_ref)`, `(target_ref)`, `(relationship_type)` as needed by query plans; at minimum btree on each column individually for naive filters.

Maintenance rule: whenever a `relationship` object is accepted into `stix_objects`, the persister upserts the denormalized row in the same transaction.

### 3. `stix_observables_index` — inverted IOC lookup

| Column | Type | Notes |
|--------|------|--------|
| `value` | `text` | Normalised observable value (`8.8.8.8`, hash hex, etc.). |
| `observable_type` | `text` | e.g. `ipv4-addr`, `file:md5` — a prow-normalised discriminator, not always identical to STIX `type` when multiple representations exist; Pass B defines the normaliser. |
| `object_id` | `text` | `NOT NULL` — the SCO’s STIX `id`. |

**Primary key:** `(value, observable_type, object_id)` — prevents duplicate index rows for the same attachment. Referential integrity to `stix_objects` is **not** a database-level foreign key in v0.1 (parent rows use partial uniques); the persister maintains consistency transactionally, and a later revision can add `object_row_id` + FK if hard enforcement becomes worth the schema churn.

**Indexes:** btree on `(value)` for “anything matching this IOC”; optional composite `(observable_type, value)` if telemetry shows type-first queries.

Maintained transactionally whenever an observable-bearing SCO is accepted.

### 4. `stix_markings` — object-level markings only

| Column | Type | Notes |
|--------|------|--------|
| `object_row_id` | `bigint` | `NOT NULL`, FK to `stix_objects.row_id`. |
| `object_id` | `text` | Denormalised STIX id for human queries. |
| `marking_id` | `text` | `NOT NULL` — STIX id of a `marking-definition`. |
| `applied_via` | `text` | `NOT NULL`; constrained to `'object'` for v0.1 rows (top-level `object_marking_refs`). |

**Primary key:** `(object_row_id, marking_id, applied_via)` — disambiguates markings when multiple `stix_objects` rows share one STIX `id` under the `(id, modified)` uniqueness model; the architecture sketch’s `(object_id, …)` alone is insufficient for that case, so `object_id` stays denormalised for convenience queries.

**Index:** btree on `(marking_id)` for “everything under this TLP”; btree on `(object_id)` for object-centric lookups.

**Granular markings:** **not** exploded into rows (see Open Questions). They remain inside `raw` only for v0.1.

### 5. `audit_log` — append-only operational history

| Column | Type | Notes |
|--------|------|--------|
| `id` | `bigserial` | Primary key. |
| `at` | `timestamptz` | `NOT NULL`, default `now()`. |
| `actor_type` | `text` | `NOT NULL` — `'connector'`, `'user'`, `'system'`. |
| `actor_id` | `text` | Nullable; instance id, user id, etc. |
| `action` | `text` | `NOT NULL` — e.g. `object.created`, `object.updated`, `object.revoked`, `connector.started`. |
| `subject_id` | `text` | Nullable STIX id or connector id. |
| `details` | `jsonb` | Nullable structured payload. |

Immutability is **by convention** in v0.1 (no `UPDATE`/`DELETE` in application code). Row-level security or event-table patterns are explicitly deferred.

### 6. `connector_state` — durable `ctx.set_state` / `ctx.get_state`

| Column | Type | Notes |
|--------|------|--------|
| `connector_instance_id` | `text` | `NOT NULL`. |
| `key` | `text` | `NOT NULL`. |
| `value` | `jsonb` | `NOT NULL` — JSON values match protocol payloads. |
| `updated_at` | `timestamptz` | `NOT NULL`. |

**Primary key:** `(connector_instance_id, key)`.

This replaces Pass B/C1 in-memory dicts in production supervises.

---

## The persister component

**Prose component diagram:** the KEV connector (or any other) finishes `fetch`, constructs a STIX `bundle` dict, and calls `await ctx.emit(bundle)` inside the connector process. The runtime transport forwards an `EmitPayload` to the host. The host supervisor resolves the injected **`emit_handler`** — in production this is **`Persister.handle_emit`**. The persister orchestrates validation, deduplication classification, repository writes inside one transaction, audit rows, and returns a fully populated **`EmitAckPayload`** (`accepted`, `duplicates`, `validation_failures`).

Internally:

- **`Persister`** — public façade; knows how to unpack bundles, iterate objects, coordinate ordering (for example ensuring referenced identities exist as `raw` rows even if soft refs are not FK-enforced), and translate fatal errors into a failed emit response.
- **`DedupResolver`** — pure logic unit; given the current database state **as visible inside the open transaction** plus the candidate objects, returns a per-object classification: `new`, `updated`, `duplicate`, `stale`, or `validation_skipped` (the latter is not a database state — see semantics section).
- **Repositories** — `StixObjectRepository`, `RelationshipRepository`, `ObservableIndexRepository`, `MarkingRepository`, `AuditLogRepository`, `StateRepository`; each owns one table’s write/read contracts.
- **`PersisterTransaction`** — async context manager acquiring a connection from the shared async engine, opening a transaction, exposing repository instances bound to that session, and committing or rolling back as a unit.

Import direction: API and connector layers import protocols from `prow.db.repositories`; only composition roots and tests import `prow.db.postgres`.

---

## Transactional semantics

**One bundle, one transaction.** After validation filtering, every database mutation for the surviving objects happens in a **single** `BEGIN … COMMIT`. If any statement raises an unexpected integrity error after the persister’s prechecks, the transaction rolls back and the supervisor receives an acknowledgement consistent with “nothing landed” for that emit (zeros for accepted and duplicates, and either an empty validation list if failure was post-validation, or the validation list unchanged — see below). Connector authors should treat that as a hard failure to retry on the next schedule.

**Validation ordering — chosen behavior:** run `prow.stix.validate_stix_object` (OASIS JSON Schema path from `_validate.py`) on **every** non-bundle object **before** acquiring the database transaction or mutating any table. Objects that fail validation populate `EmitAckPayload.validation_failures` with `object_id` and error text, and are **skipped** for persistence **without** failing the whole emit. All remaining objects participate in the single transaction. Justification: the protocol’s `validation_failures` field is a list, not a single error, which strongly implies per-object reporting; KEV-scale bundles should not lose thousands of good rows because one malformed extension slipped through; and supervisors already treat emit as an acknowledged operation — partial success is easier to reason about than silent total loss.

**Important nuance:** if validation fails for **all** objects, the persister still returns success at the protocol level with `accepted = 0`, `duplicates = 0`, and a populated failure list — that is not a database rollback case.

**Dedup inside the transaction:** classification reads current row versions using the same snapshot as the subsequent writes (`REPEATABLE READ` is the default sensible isolation; final choice is Pass C). Two concurrent emits of the same new object contend on the unique indexes; one wins as `new`, the other observes `duplicate` or `stale` after refresh — exact handling is implementation detail, but the design requirement is **no double insert** of the same business key.

**No silent overwrites of newer data:** if an incoming versioned object has the same `id` as an existing row but **strictly older** `modified`, classify **`stale`**, do not write, count toward **`duplicates`** in the ack. If `modified` is **newer**, classify **`updated`** and overwrite the prior row (and dependent satellite rows) for that `id` in line with STIX versioning semantics. SCO path: same `id` always **`duplicate`** on second insert attempt.

---

## Dedup policy

**SDOs and SROs (including `relationship` in `stix_objects`):** compare `(id, modified)`. Same pair → `duplicate`. Incoming newer `modified` → `update` replacing the prior row for that `id` (there is at most one “current” row per `id` for non-relationship SDOs in many UIs — this design keeps the storage model aligned with “latest wins” while still allowing historical audit via `audit_log` entries). Incoming older `modified` → `stale`.

**Relationships and `stix_relationships`:** in addition to per-relationship-id versioning, enforce the **global triple** uniqueness described above. When triple collision happens with differing STIX ids, count as **`duplicate`** for ack tallies.

**SCOs:** dedup strictly by `id` (deterministic per ADR-0009 amendment boundary at the connector; persister trusts incoming ids). Second insert attempt → **`duplicate`**.

**Emit counts:** `accepted = len(new) + len(updated)`; `duplicates = len(duplicate) + len(stale)`; `validation_failures` list length is **not** subtracted from accepted — it is orthogonal metadata.

---

## Memory and streaming

KEV’s single-bundle footprint (~4.5k–5k objects) is acceptable to hold in memory as a Python structure for v0.1 (order of a few megabytes JSON). ATT&CK will be larger; still acceptable short term.

**Insert strategy:** batch writes of **500 rows** per statement (tunable constant). Use SQLAlchemy Core `insert().values([...])` batches with executemany-style binding rather than one five-thousand-value statement. The **transaction** remains one per bundle; batching is only to reduce parse/plan overhead and wire size spikes.

**Future:** bundles beyond ~10k objects may need streaming parse or chunked transactions — explicitly **out of scope** for v0.1; document as follow-up if a connector exceeds comfortable RAM.

---

## Repository interfaces

Protocols live in `prow.db.repositories`; Postgres implementations in `prow.db.postgres`. Shapes below are indicative — names may shift slightly during implementation, but capabilities should not.

```python
class StixObjectRepository(Protocol):
    async def get_current_by_stix_id(self, stix_id: str) -> StixObjectRecord | None: ...
    async def get_version(self, stix_id: str, modified: datetime) -> StixObjectRecord | None: ...
    async def list_by_type(
        self, stix_type: str, *, limit: int = 100, offset: int = 0
    ) -> list[StixObjectRecord]: ...
    async def full_text_search(self, query: str, *, limit: int = 50) -> list[StixObjectRecord]: ...
    async def fuzzy_name_search(self, needle: str, *, limit: int = 50) -> list[StixObjectRecord]: ...


class RelationshipRepository(Protocol):
    async def outgoing(self, stix_id: str, *, limit: int = 500) -> list[RelationshipEdge]: ...
    async def incoming(self, stix_id: str, *, limit: int = 500) -> list[RelationshipEdge]: ...
    async def find_by_triple(
        self, source_ref: str, relationship_type: str, target_ref: str
    ) -> RelationshipEdge | None: ...


class ObservableIndexRepository(Protocol):
    async def lookup(self, value: str, *, observable_type: str | None = None) -> list[StixObjectRecord]: ...


class MarkingRepository(Protocol):
    async def markings_for_object(self, object_row_id: int) -> list[str]: ...


class AuditLogRepository(Protocol):
    async def append(self, entry: AuditLogEntry) -> None: ...


class StateRepository(Protocol):
    async def get(self, instance_id: str, key: str) -> Any | None: ...
    async def set(self, instance_id: str, key: str, value: Any) -> None: ...
```

`StixObjectRecord` / `RelationshipEdge` / `AuditLogEntry` are prow-owned dataclasses or Pydantic models defined next to the protocols, not STIX library types.

---

## Migrations

- Add `alembic.ini` at the repository root and a `migrations/` package with env.py targeting async SQLAlchemy.
- **Initial revision** creates extensions (`pg_trgm`), all six tables, all indexes, generated column for `search_text`, partial unique indexes on `stix_objects`, and the triple uniqueness index on `stix_relationships`.
- Workflow: developers run Alembic autogenerate where appropriate, **hand-review** every diff (especially generated columns and partial indexes — autogenerate is never trusted blindly), commit revision files with the PR that needs them, and **never rewrite** merged history. Reverts ship as new down revisions.
- Subsequent schema changes each get their own revision in the same PR as the code that depends on them.

---

## Connection management

- Construct **one** async SQLAlchemy engine per process at startup, shared by the persister, future API repositories, and health checks.
- Pool defaults: size **10**, max overflow **5**, acquire timeout **30 seconds** — all configurable (see below).
- Startup health: `SELECT 1` through the engine; failure logs a actionable error and **exits the process** — fail-fast beats limping without storage in v0.1.

---

## Configuration

Extend `prow.config` (currently scaffolded) with Pydantic settings fields:

| Field | Purpose |
|-------|---------|
| `database_url` | Async DSN, e.g. `postgresql+asyncpg://prow:prow@localhost:5432/prow` locally. |
| `database_pool_size` | Default `10`. |
| `database_pool_max_overflow` | Default `5`. |
| `database_pool_timeout_seconds` | Default `30`. |

Environment override: **`PROW_DATABASE_URL`** and friends following whatever naming convention `prow.config` already standardises when implemented.

---

## Testing strategy

**Unit tests:** `DedupResolver` and any normalisation helpers (IOC value extraction, marking extraction) run without Postgres — pure tables of fixtures.

**Repository integration tests — chosen approach:** **Docker Compose–managed Postgres 16** is the default developer and CI path. Rationale: the real database must load `pg_trgm`, accept generated `tsvector` columns, and exercise partial unique indexes exactly like production; Compose matches how solo operators already run prow’s small tier, and CI services can reuse the same compose file with minimal drift. **`pytest-postgresql`** remains a valid future optimisation for contributors who cannot run Docker, but v0.1 documentation should not multiply golden paths — one blessed integration harness keeps CI predictable.

**End-to-end:** drive a frozen KEV fixture bundle through `Persister.handle_emit` (or the full supervisor with a test `emit_handler` shim) and assert row counts, key triples, observable index rows, and ack counters — cheaper and stabler than live network pulls.

---

## Open questions

1. **JSON Schema validation on read:** whether repository `get` methods should re-validate `raw` into `prow.stix.types` with `parse_external` every time — probably optional (`validate=False` default) but worth an explicit API decision when the REST layer ships.
2. **`revoked` retention semantics:** STIX allows removal; prow leans toward **retain + default filter** with an `include_revoked` switch on future queries — needs product text in the API note.
3. **Audit log retention and compaction:** indefinite growth is unsafe; no policy in v0.1.
4. **Cross-process / multi-supervisor races on `connector_state`:** database serialisation helps, but two supervisors touching the same logical instance is undefined — flag for ADR-0003’s later split work.
5. **Granular markings denormalization explosion:** deferred intentionally; if ISO-style field-level enforcement becomes a compliance requirement, expect a new table or JSONB indexing strategy.
6. **Exact isolation level and `SERIALIZABLE` necessity:** likely unnecessary for v0.1 single-node writes, but worth validating under concurrent connector tests.

---

## Implementation order

1. **Pass A — schema and migrations.** Alembic skeleton, initial revision with all six tables, extensions, indexes, generated `search_text`, partial uniques. Tests apply up/down against Compose Postgres.
2. **Pass B — repositories.** Protocol modules, async SQLAlchemy table definitions, Postgres repository classes, state repository backing supervisor handlers in tests.
3. **Pass C — persister core.** `Persister`, `PersisterTransaction`, `DedupResolver`, validation orchestration, batch insert loops, audit writes, triple enforcement — with KEV-scale fixture test.
4. **Pass D — production wiring.** Inject persister into `Supervisor`, replace in-memory state with `StateRepository`, optional CLI flag for `prow connector dev` to enable persister vs print-only sink.

**Rough LOC budget (all passes, including tests):** on the order of **4,000–6,500 LOC** — migrations and verbose repository methods dominate; this is intentionally larger than the supervisor runtime estimate because data-layer tests are heavy.

---

## References

- [ADR-0003 — Modular monolith with split-ready seams](../04_DECISION_LOG.md#adr-0003--modular-monolith-with-split-ready-seams)
- [ADR-0006 — Postgres-first storage](../04_DECISION_LOG.md#adr-0006--postgres-first-storage)
- [ADR-0009 — Wrap stix2, plan for soft fork](../04_DECISION_LOG.md#adr-0009--wrap-the-oasis-stix2-python-library-plan-for-soft-fork)
- [Architecture §6 — STIX 2.1 mechanics](../01_ARCHITECTURE.md#6-stix-21-mechanics)
- [Architecture §7 — Storage schema sketch](../01_ARCHITECTURE.md#7-storage-schema-canonical-sketch)
- [Architecture §8 — Ingestion pipeline](../01_ARCHITECTURE.md#8-ingestion-pipeline)
- [Connector runtime design note](connector-runtime.md)
- [Connector protocol design note](connector-protocol.md)
