# Prow — Decision Log

This log captures architectural decisions with the context and trade-offs at
the time. New entries appended at the bottom. Reverse a decision only by
adding a new entry that explicitly supersedes the old one.

Format borrowed from Architecture Decision Records (ADRs).

---

## ADR-0001 — License: Apache 2.0 throughout, no open-core
**Status:** accepted, 2026-05-07
**Context:** OpenCTI's open-core model puts SSO, audit logs, automation, and
RBAC behind a commercial license. This is the strategic opening for prow.
**Decision:** Apache 2.0 across the entire codebase. No EE tier. Sustainability
via hosted SaaS, support contracts, custom dev, and training — never
feature-gating.
**Consequences:** Pricing pressure on the eventual SaaS offering. Lower
revenue ceiling than open-core competitors. In exchange, a defensible
position no open-core vendor can match without breaking their model.

## ADR-0002 — STIX 2.1 over 2.0
**Status:** accepted, 2026-05-07
**Context:** Initial framing mentioned 2.0; that's the older spec. 2.1 is the
current OASIS standard and what every modern CTI tool implements.
**Decision:** Internal data model and over-the-wire format are STIX 2.1.
**Consequences:** Slightly later spec but better tooling alignment. Will need
to keep an eye on Errata and CSDs.

## ADR-0003 — Modular monolith with split-ready seams
**Status:** accepted, 2026-05-07
**Context:** Need to serve both solo researchers on a 4 GB VPS and SOCs
running horizontal deploys. Cannot afford to maintain two codebases.
**Decision:** Single codebase deploys as a monolith by default. Module
boundaries enforced as Python package boundaries with import-linter in CI.
All async hand-offs go through a bus interface with two implementations
(`asyncio.Queue` for monolith, NATS JetStream for split). Storage access
through repository interfaces.
**Consequences:** Higher up-front discipline cost. Architectural drift will
break the split-readiness; needs CI enforcement.

## ADR-0004 — Python + FastAPI backend
**Status:** accepted, 2026-05-07
**Context:** OpenCTI uses Node + GraphQL. Connector authors in CTI overwhelmingly
work in Python. Same-language end-to-end lowers contributor friction.
**Decision:** Python 3.12+ with FastAPI for the backend.
**Consequences:** Forgo Node ecosystem advantages on the backend. Accept
Python's GIL trade-offs (mitigated by `asyncio` and per-process workers).

## ADR-0005 — REST + OpenAPI as primary API
**Status:** accepted, 2026-05-07
**Context:** OpenCTI's GraphQL-only API contributes to its learning-curve
complaints. REST has ubiquitous tooling.
**Decision:** REST with OpenAPI as the contract. GraphQL adapter optional later.
**Consequences:** GraphQL users must wait or use the adapter. Acceptable.

## ADR-0006 — Postgres-first storage
**Status:** accepted, 2026-05-07
**Context:** OpenCTI's hard dependency on Elasticsearch + Redis + RabbitMQ +
MinIO drives the 16 GB minimum footprint. Postgres can credibly serve graph
storage (recursive CTEs), FTS (`tsvector` + `pg_trgm`), and lightweight queue
duties for small deployments.
**Decision:** Postgres 16 is the only required stateful service in the small
tier. OpenSearch is an optional drop-in for FTS at scale. Redis and NATS
optional in split mode. Source of truth is the raw STIX `jsonb`; everything
else is derived.
**Consequences:** Hits the 4 GB minimum target. Will feel scale pressure
above ~50M indicators with deep traversals. Repository interfaces keep this
swappable.

## ADR-0007 — Connector framework is first-class from day one
**Status:** accepted, 2026-05-07
**Context:** Solo-developer TIPs die without community connectors.
**Decision:** The connector SDK spec is written before platform code. The
walking-skeleton CISA KEV connector is built against the SDK as its first
real consumer, forcing the API to be ergonomic under real use.
**Consequences:** Slower start. Worth it.

## ADR-0008 — Connectors run as in-process tasks (monolith) or worker pods (split)
**Status:** accepted, 2026-05-07
**Context:** OpenCTI runs one container per connector, which is operationally
heavy for the dominant small-deployment shape.
**Decision:** Connectors are Python packages registered via entry points.
The framework runs them as `asyncio` tasks in monolith mode, as worker pods
in split mode. The `ConnectorContext` abstracts the runtime — connector code
does not change.
**Consequences:** Connector failure isolation is weaker in monolith mode (a
hung connector can affect the host process). Mitigation: per-connector
asyncio task supervision with timeouts and circuit breakers.

## ADR-0009 — Wrap the OASIS stix2 Python library, plan for soft fork
**Status:** accepted, 2026-05-07
**Context:** The reference `stix2` library has been functionally inactive
for 12+ months per Snyk's package-health analysis. Full reimplementation is
disproportionate; full dependence is risky.
**Decision:** Use `stix2` for serialization wrapped in `prow.stix`.
Validate against OASIS JSON schemas directly on every ingest, not solely
via the library's validators. Plan to either contribute upstream or
maintain a soft fork under the prow GitHub org.
**Consequences:** Slight duplicate-effort cost for schema validation;
buys insurance against upstream rot.

## ADR-0010 — TAXII 2.1 as the federation primitive (not a custom protocol)
**Status:** accepted, 2026-05-07
**Context:** Federation is a v1.0 feature. Tempting to design a custom
prow-to-prow protocol. TAXII 2.1 already exists and every CTI tool speaks it.
**Decision:** Prow ships a TAXII 2.1 server and client at v1.0. Federation
between prow instances uses TAXII. Custom prow-specific extensions (signed
intel, trust groups) ride on top via STIX extensions, not a parallel protocol.
**Consequences:** Bound by TAXII's design choices. Acceptable; the
interoperability win is large.

---

## Open decisions (not yet resolved)

- **Project domain & GitHub org name.** `prow.io` / `prow.security` /
  `prow-cti.org` candidates. Trademark search not yet done. GitHub org
  recommended as `prow-cti` to disambiguate from Kubernetes Prow.
- **License of bundled MITRE ATT&CK data.** MITRE's CTI repo is permissive
  but attribution is required. Need to confirm exact requirements before
  bundling vs fetching at runtime.
- **Default IdP at install time.** Bundle a built-in IdP (Authentik-style)
  vs require the operator to bring an OIDC provider? Leaning bundled-but-
  optional: ship with a built-in IdP that handles the single-admin use case
  out of the box, OIDC for everything bigger.
- **Connector signing for the public catalog.** Sigstore/cosign vs PGP vs
  GitHub attestations. Defer until catalog is real.
- **Hosted SaaS pricing model.** Per-org flat fee vs per-indicator vs
  per-user. Defer; not a v1.0 problem.
