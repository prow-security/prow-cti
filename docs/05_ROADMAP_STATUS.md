# Prow — Roadmap & Status

Operational view of where prow is and what's next. Update this file as
milestones move. Keep ARCHITECTURE.md for the "what and why," this for the
"where we are."

## Current status

**Phase:** Pre-development. Architecture and SDK spec drafted; no code yet.

**Immediate next actions** (in order):
1. Trademark search for "Prow" in the cybersecurity / software class.
2. Claim domain (`prow.io` or `prow.security`), GitHub org (`prow-cti`),
   social handles (Mastodon, Bluesky, Reddit).
3. Push public README + roadmap to the empty repo. Manifesto-style — the
   "fully OSS, no SSO tax" position is the headline.
4. Write `CONNECTOR_SDK.md` into the public repo verbatim from the project
   knowledge — this is the document people will judge prow on before any
   code exists.
5. Implement CISA KEV connector against the SDK spec — the framework is
   shaped to make this connector ergonomic.
6. Then, and only then, start the platform: Postgres schema → STIX
   persistence → connector runner → API → minimal UI.

## v0.1 — Walking skeleton

**Target window:** 4–6 weeks of focused work
**Goal:** prow runs, ingests CISA KEV, you can see STIX objects in a UI.
**Demo:** `docker run prow/prow:0.1`, KEV imported on first boot, search
for a recent CVE, see the indicator and its relationships.

Scope:
- [ ] FastAPI app skeleton with health checks, OpenAPI docs
- [ ] Postgres schema (stix_objects, stix_relationships, stix_observables_index, connector_state)
- [ ] `prow.stix` module wrapping OASIS stix2 + JSON-schema validation
- [ ] Connector runtime (in-process asyncio task supervisor)
- [ ] Connector base classes per type
- [ ] CISA KEV connector implementing the SDK spec
- [ ] REST endpoints: list/get/search indicators, get relationships, list connectors
- [ ] Minimal React UI: indicator list, indicator detail, IOC search
- [ ] Local username/password auth
- [ ] Single Docker image with supervisord
- [ ] CI: lint (ruff), typecheck (mypy/pyright), tests (pytest), import-linter

Not in scope:
- Auth beyond local username/password
- Connector SDK published to PyPI (it's internal still)
- Graph visualization
- OpenSearch backend

## v0.2 — Connector library + UX

**Target window:** 6–8 weeks after v0.1
**Goal:** Enough connectors to be genuinely useful day one. SDK ergonomic
enough to publish.

Scope:
- [ ] `prow-connector-sdk` published to PyPI
- [ ] Hot-reload dev loop (`prow connector dev`)
- [ ] Test harness (`prow connector test`)
- [ ] Connectors:
  - [ ] MISP (any MISP instance)
  - [ ] MITRE ATT&CK
  - [ ] abuse.ch URLhaus
  - [ ] abuse.ch ThreatFox
  - [ ] abuse.ch MalwareBazaar
  - [ ] abuse.ch Feodo Tracker
  - [ ] abuse.ch SSLBL
  - [ ] AlienVault OTX / LevelBlue
- [ ] Output connectors:
  - [ ] TAXII 2.1 server (read-only collections)
  - [ ] Generic webhook
  - [ ] Suricata rule export
  - [ ] Pi-hole / blocklist export
- [ ] Graph visualization (relationship browser)
- [ ] Dashboard with key metrics (indicator counts, recent activity, source breakdown)
- [ ] OIDC support — **the "SSO is free" marketing moment**

## v0.3 — Multi-user & automation

**Target window:** 8–10 weeks after v0.2
**Goal:** A small SOC can adopt prow without hitting paywalls.

Scope:
- [ ] Granular RBAC (orgs, groups, users, roles, capabilities)
- [ ] Audit log (immutable, queryable)
- [ ] Enricher chains with visual builder
- [ ] Webhook subscription system
- [ ] Optional OpenSearch backend for FTS
- [ ] Public connector catalog at connectors.prow.io (or similar)
- [ ] Connector signing (sigstore or GH attestations)

## v1.0 — Federation

**Target window:** 10–14 weeks after v0.3
**Goal:** prow instances talk to each other and to other TAXII servers
securely.

Scope:
- [ ] TAXII 2.1 client (consume from external TAXII servers)
- [ ] TAXII 2.1 server (writable collections, multi-collection)
- [ ] Per-collection sharing rules (TLP-aware)
- [ ] Trust groups with mutual-auth (cert pinning or signed tokens)
- [ ] Signed intel between trusted peers
- [ ] Dissemination workflows (PDF reports, email lists)
- [ ] LTS branch + 12-month security commitment

## Beyond v1.0

- AI-assisted IOC extraction from PDFs and blog posts (genuinely useful
  LLM application: pulling structured IOCs from unstructured threat reports)
- ATT&CK Navigator integration
- Sandbox connectors (Cuckoo, Joe Sandbox, Hybrid Analysis)
- Federated identity across prow instances
- Mobile-friendly read-only UI for analysts on call

## Ongoing tracks (run alongside the above)

- **Documentation.** Every shipped feature ships with docs in the same PR.
- **Public-build cadence.** Demo video or written update at least monthly
  on Mastodon/Bluesky/r/blueteamsec. Build pull from the community early.
- **Contributor onboarding.** "Good first connector" issues curated; SDK
  docs kept in sync with the code; CONTRIBUTING.md kept honest about
  what's expected.
- **Threat-feed monitoring.** Watch for terms changes, license changes,
  acquisitions (OTX → LevelBlue is the recent example). Connector
  status field in manifests reflects this honestly.
