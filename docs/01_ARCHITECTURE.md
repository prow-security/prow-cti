# Prow — Architecture & Decisions

This document captures load-bearing architectural decisions for prow. It is the
canonical reference. When something changes, update this file and note the
revision at the bottom.

## 1. Mission and positioning

Prow is a fully open-source cyber threat intelligence platform built on STIX
2.1. It is a deliberate alternative to OpenCTI, designed around three pillars:

1. **Truly open** — Apache 2.0 across the entire codebase. No open-core, no
   enterprise tier, no features gated behind commercial licenses. SSO, audit
   logs, RBAC, automation, multi-tenancy are all in the free product.
2. **Lightweight by default** — runs on a 4 GB / 2 vCPU VPS for solo and small
   team use, scales horizontally for SOCs without re-architecting.
3. **Connector-first** — the contributor experience for writing a feed
   connector is the most important DX surface in the project. Goal: a
   competent Python developer can ship a working connector in a weekend.

**Tagline candidates:** "Prow through the noise." / "The threat intel
platform that's actually open."

**Sustainability model (committed, not paid features):** hosted SaaS (same
codebase, operated by us), paid support contracts, custom development,
training. Never feature-gating.

## 2. Strategic context

OpenCTI is the dominant modern CTI platform but uses an open-core model.
Features behind their Enterprise Edition include SSO (OIDC/SAML/LDAP), audit
logs, automation playbooks, dissemination workflows, granular RBAC, and
multi-tenancy. Charging for SSO especially is the textbook "SSO tax" — for any
org with more than five people, SSO is a baseline security control, not a
luxury. Charging for it makes deployments less secure.

MISP is the closest philosophical competitor (also fully OSS, AGPL-3.0). MISP
strengths: feed ecosystem, correlation, established community. MISP weaknesses:
PHP, dated UX, event-centric rather than knowledge-graph-centric, partial STIX
2.1 support.

Prow's competitive position: **MISP's open-source ethos + OpenCTI's STIX-native
graph model + a modern, lighter-weight architecture + a deliberately better
connector developer experience.**

## 3. Architectural principles

**Modular monolith that splits cleanly.** Single deployable artifact by
default; service boundaries enforced as package boundaries so any module can
be lifted out into its own process without rewriting business logic.

**Discipline that makes the split possible:**
- Module boundaries are Python package boundaries. Enforce no cross-module
  internal imports via `import-linter` or `tach` in CI.
- Every async hand-off uses a message bus interface, even in monolith mode. In
  monolith mode the implementation is `asyncio.Queue`. In split mode it is
  NATS JetStream. Calling code never changes.
- Storage access goes through repository interfaces, not direct DB calls.

**Postgres-first storage.** Postgres serves as graph store (recursive CTEs over
edge table), full-text search (`tsvector` + `pg_trgm`), object metadata store,
and (via `LISTEN/NOTIFY` or table-based queue) lightweight queue for the small
deployment tier. OpenSearch is an optional drop-in for FTS at scale. This
single decision is what unlocks the 4 GB minimum footprint.

**Source-of-truth is the raw STIX object.** Every STIX object is stored as
`jsonb` plus derived indexed columns. STIX spec changes don't require schema
migrations, only re-indexing.

**REST + OpenAPI as the primary API.** GraphQL adapter optional later. OpenCTI's
GraphQL-only API is part of the learning-curve complaint. REST means `curl`
works, every language has a client, the OpenAPI doc is the contract.

## 4. Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend language | Python 3.12+ | Same language as the CTI ecosystem and as connector authors. |
| Web framework | FastAPI | Async-native, OpenAPI-first, Pydantic validation. |
| Frontend | React + TypeScript + Vite | TanStack Query, shadcn/ui, deliberately not the OpenCTI dashboard aesthetic. |
| Primary datastore | PostgreSQL 16 | With `pgvector` and `pg_trgm` extensions. |
| Search (scale tier) | OpenSearch (optional) | Apache 2.0 fork, aligned with our license stance. |
| Message bus | NATS JetStream (split mode) / `asyncio.Queue` (monolith mode) | Single bus interface, two implementations. |
| Cache | In-process LRU by default, Redis optional | |
| Auth | Built-in IdP + OIDC/SAML/LDAP/header out of the box | This is a marketing moment — "SSO is free." |
| Object storage | Local FS by default, S3-compatible optional | MinIO / S3 / R2 / B2. |
| Observability | OpenTelemetry first-class | Traces and metrics out of the box. |
| Deployment | Single Docker image (all-in-one) + Compose (split services) + Helm chart | Same codebase, different process configs. |

## 5. Deliberate departures from OpenCTI

Each is a considered trade-off, not an oversight:

- **Python over Node.js** — connector ecosystem alignment.
- **REST over GraphQL** — lower learning curve, ubiquitous tooling.
- **Postgres-only small tier over Elasticsearch+Redis+RabbitMQ+MinIO** — the 4 GB minimum.
- **In-process connectors (monolith) over container-per-connector** — operational simplicity for the dominant deployment shape.
- **Apache 2.0 throughout over open-core** — the entire pitch.

## 6. STIX 2.1 mechanics

Prow uses STIX 2.1 (the current OASIS standard) for both internal data model
and over-the-wire. The OASIS Python `stix2` library is used for
serialization/deserialization behind **`prow.stix`** — the wrapper exists for
**fork-readiness** and a localized dependency swap; **operational definition**
(evidence, triggers, watch list) lives in **ADR-0009** and its **2026-05-07**
amendment.

Validation is performed against the OASIS JSON schemas directly on every
ingest, not solely via the library's validators.

**TAXII 2.1** is supported as both server (other tools pull from prow) and
client (prow pulls from other TAXII servers) starting v1.0. TAXII is the
federation primitive.

### Upstream watch list

Quarterly review against **ADR-0009**’s trigger conditions:

- Most recent **`stix2`** release on **PyPI** (date and version).
- Commits to upstream **`master`** in the **last 90 days** (GitHub commits API
  **`since=`** window ending on review date).
- Open **STIX 2.1** spec compliance issues **older than 90 days** with **no
  maintainer response** (Errata / schema alignment — see memo §STIX 2.1 spec
  coverage).
- Known **CVEs** in **`stix2`** or its **direct dependencies**.
- Public **fork signals** from major CTI vendors (**Filigran**, **MITRE**, **MISP**).

If any trigger fires, open an issue tagged **`upstream-watch`** with a **30-day
decision deadline**. The decision is binary: **continue wrapping** or **move to a
soft fork** under the **`prow-cti`** GitHub org.

**First review due `2026-08-12`** (**PyPI `stix2` `3.0.2` release date
`2026-02-12` + six months**, per ADR-0009 amendment).

## 7. Storage schema (canonical sketch)

```
stix_objects        — one row per STIX object across all types
  id                 text PK         -- STIX ID
  type               text            -- 'indicator', 'malware', etc.
  spec_version       text            -- '2.1'
  created            timestamptz
  modified           timestamptz
  created_by_ref     text            -- FK to identity
  revoked            bool
  raw                jsonb           -- full STIX object as received (source of truth)
  search_text        tsvector        -- generated column for FTS
  -- selective indexed columns for hot fields per type

stix_relationships   — denormalized edges for fast graph traversal
  id                 text PK
  source_ref         text            -- indexed
  target_ref         text            -- indexed
  relationship_type  text            -- indexed
  -- timestamps, confidence, etc.

stix_observables_index — inverted index for IOC lookup
  value              text            -- '8.8.8.8' or hash
  observable_type    text            -- 'ipv4-addr', 'file:md5'
  object_id          text            -- FK to stix_objects

stix_markings        — TLP, statement, granular markings
stix_external_refs   — denormalized for filtering by source

connector_state      — per-connector cursors and state
audit_log            — every mutating action, immutable
```

The `raw` column is authoritative; other columns are derived from it.

## 8. Ingestion pipeline

```
[Connector] → [Bundle Validator] → [Deduplicator] → [Enricher Chain]
                                                       → [Persister] → [Event Bus]
```

- **Bundle Validator:** schema-validates against STIX 2.1. Rejects malformed
  objects with structured errors back to the connector.
- **Deduplicator:** uses STIX deterministic IDs where the spec defines them
  (SCOs); soft-dedups SDOs by hashing on type + name + key fields.
- **Enricher Chain:** pluggable, configurable per-deployment. Confidence
  scoring, TLP propagation, MITRE ATT&CK enrichment, optional VT/AbuseIPDB
  lookups. This is prow's "playbook" equivalent and is **free in CE**.
- **Persister:** transactional write to Postgres.
- **Event Bus:** publishes `object.created` / `object.updated` for UI,
  webhooks, federation subscribers.

Every object carries: source connector ID, ingest timestamp, original
confidence (if provided), prow-computed confidence, TLP. **Provenance is
immutable.** Objects can be revoked; their origin cannot be rewritten.

## 9. Connector framework — the most important DX surface

**Contract:** a connector is a Python package with a `manifest.yaml` and one
or more entry-point classes inheriting from a connector base class.

**Connector types** (modeled on OpenCTI's taxonomy, which is sound):
- `external_import` — pull from a feed on a schedule
- `stream` — push events to another system (SIEM, EDR, blocklist)
- `enrichment` — given an observable, look it up and enrich
- `internal_export` — generate exports (STIX bundle, CSV, IOC list, Suricata, YARA, Sigma)
- `internal_import` — process user uploads (PDF report → IOCs)

**What the framework provides** (so connector authors don't write it):
- Validation, deduplication, persistence on `ctx.emit(bundle)`
- State management via `ctx.last_run_at`, `ctx.cursor`, `ctx.set_state()`
- Structured logging via `ctx.log`
- Retries with backoff
- Metrics (objects emitted, errors, duration)
- Hot-reload dev loop via `prow connector dev ./path/`
- Test harness with HTTP fixture replay

**Critical property:** connector **packages** stay one shape across runtimes, but
the **execution model for production monolith mode is refined in ADR-0011**
(subprocess isolation + protocol vs the fast in-process path reserved for
`prow connector dev`). Split mode still uses worker-style execution behind the same
`ConnectorContext` façade. See [ADR-0011 — Connector isolation model in monolith mode](adr/ADR-0011-connector-isolation.md).

**Distribution:** `pip install prow-connector-foo`. Prow auto-discovers via
Python entry points. Public catalog at (eventual) `connectors.prow.io` or
similar.

## 10. Initial connector library — ship priorities

**v0.1 (walking skeleton):** CISA KEV only. Smallest scope, JSON, no auth,
immediate value. Forces the framework API to be ergonomic by being the first
real consumer.

**v0.2 ship list:**
- MISP (any MISP instance)
- MITRE ATT&CK (STIX 2.1 native)
- abuse.ch URLhaus
- abuse.ch ThreatFox
- abuse.ch MalwareBazaar
- abuse.ch Feodo Tracker
- abuse.ch SSLBL
- AlienVault OTX / LevelBlue (with platform-risk note in the connector readme)
- TAXII 2.1 server (output)
- Generic webhook (output)
- Suricata rule export (output)
- Pi-hole / blocklist export (output) — sleeper hit for home-lab adopters

**v0.3+:** MITRE CAPEC, CISA KEV expansions, Spamhaus DROP/EDROP, PhishTank,
OpenPhish, Tor exit nodes, Emerging Threats rules, ISC, CIRCL OSINT,
DigitalSide. Enrichment connectors: VirusTotal, AbuseIPDB, Shodan, GreyNoise,
URLscan.io. Output connectors: Splunk HEC, Elastic, Sigma, YARA.

## 11. Phased roadmap

**v0.1 — walking skeleton (4–6 weeks).** Backend + Postgres schema +
STIX validate/store/retrieve + CISA KEV connector + minimal UI (list, single
view, IOC search) + local username/password auth + single Docker image.
Demo: prow up, KEV imported, search a CVE, see graph.

**v0.2 — connector library + UX (6–8 weeks).** Connector SDK on PyPI +
hot-reload dev loop + test harness + the v0.2 connector list above + graph
viz + relationship browser + dashboard + OIDC ("SSO is free" moment).

**v0.3 — multi-user & automation (8–10 weeks).** Granular RBAC + audit log +
enricher chains with visual builder + webhook subscriptions + optional
OpenSearch backend + public connector catalog.

**v1.0 — federation (10–14 weeks).** TAXII 2.1 client+server + per-collection
sharing rules + trust groups + signed intel between peers + dissemination
workflows + LTS branch with 12-month security commitment.

## 12. Acknowledged risks

1. **Solo-developer scope risk.** Mitigation: ship v0.1 fast and publicly. A
   working demo on day 30 beats a perfect architecture on day 90.
2. **Connector framework must be first-class from day one.** If platform
   ships first, framework will be awkward. CISA KEV connector is built
   *against the framework you intend others to use*.
3. **Postgres-as-graph has scale limits.** ~50M+ indicators with deep
   traversals will feel it. Repository interfaces keep this swappable.
4. **"Fully OSS" position will be tested.** Commit publicly to the
   sustainability model in the README. Hosted SaaS is the cleanest play.
5. **Threat-feed landscape changes.** OTX → LevelBlue is a recent example.
   Connector framework needs graceful deprecation signaling.
6. **STIX Python upstream cadence is uneven.** Wrap `stix2` in `prow.stix`;
   validate against OASIS JSON schemas; follow **ADR-0009** (amendment **2026-05-07**)
   for triggers and the §6 **Upstream watch list**.
7. **Naming.** "Prow" is a common word; trademark is hard. Kubernetes "Prow"
   CI tool is in a different category but worth namespacing GitHub org as
   `prow-cti`. Get a proper trademark search before branding spend.

## Revision history

- 2026-05-07: Initial document.
- 2026-05-07: ADR-0009 amendment — memo-backed evidence, operational fork triggers,
  §6 **Upstream watch list** + first review **`2026-08-12`**; risk #6 aligned.
