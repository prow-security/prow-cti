# Prow CTI

**Open-source threat intelligence, without the asterisks.**

Prow CTI is a STIX 2.1–native cyber threat intelligence platform built
around three commitments:

- **Apache 2.0, all of it.** Single-sign-on, audit logs, role-based access
  control, automation, multi-tenancy — in the project, not behind a
  commercial tier.
- **Lightweight by default.** Runs on a 4 GB VPS for solo researchers and
  small teams. Scales horizontally for SOCs without a rewrite.
- **Connectors are the product.** Writing a feed connector should be a
  weekend, not an onboarding programme.

Prow CTI is the first product from [Prow](https://github.com/prow-sh),
a company building open-source security infrastructure.

> **Status: pre-alpha.** The connector framework is in: a versioned
> stdin/stdout JSON protocol, a subprocess supervisor with restart and
> health policy, an in-process dev runtime with hot reload, the
> `prow connector dev` / `prow connector validate` CLI, and the CISA KEV
> connector as the first real consumer. **Postgres schema (Alembic) for
> the persister** is in — see `src/prow/db/migrations/` and `docs/design/persister.md`.
> The persister implementation (emit → DB), the HTTP API, and the UI are
> next. Watch the repo for the v0.1 milestone when Prow CTI runs end-to-end.

## Quickstart

```bash
git clone https://github.com/prow-security/prow-cti
cd prow-cti
docker compose up
```

Wait ~30 seconds for Postgres to initialize and KEV to ingest
(~1,600 CVEs). Then open http://localhost:8000.

To skip the automatic KEV import:
```bash
PROW_SKIP_KEV_IMPORT=true docker compose up
```

For production deployments, set `POSTGRES_PASSWORD` (and other
secrets) from a secrets manager — the default `prow` password in
`docker-compose.yml` is for local development only.

---

## Why another threat intel platform

The two open platforms most teams actually consider are MISP and OpenCTI.
Both are good projects. Prow CTI exists because of the gaps between them.

**MISP** is fully open-source and battle-tested, with the strongest feed
ecosystem in the space. It's also PHP, event-centric rather than
graph-centric, and its STIX 2.1 support is partial. Teams that want a
modern data model and a knowledge-graph view of their intel often look
elsewhere.

**OpenCTI** is the modern, STIX-native, graph-centric platform — and it's
the one Prow CTI positions against most directly. OpenCTI is open-core:
SSO (OIDC/SAML/LDAP), audit logs, automation playbooks, granular RBAC,
and multi-tenancy live in the Enterprise Edition. For organisations of
more than a handful of people, SSO is a baseline security control, not a
premium feature. Charging for it pushes smaller teams toward less-secure
deployments. That's the gap Prow CTI is built into.

The pitch, in one line: **MISP's open-source ethos, OpenCTI's graph
model, a lighter footprint, and a connector developer experience that
respects your time.**

## Design principles

**STIX 2.1 native.** The current OASIS standard, end to end. Internal
data model, REST API, federation. Not a translation layer over something
else.

**Postgres-first.** A single Postgres 16 instance is the only required
stateful service in the small tier — graph storage via recursive CTEs,
full-text search via `tsvector` and `pg_trgm`, lightweight queue duties
via `LISTEN/NOTIFY`. OpenSearch is an optional drop-in for FTS at scale.
This is what makes the 4 GB minimum real.

**Modular monolith with split-ready seams.** One deployable artefact by
default; module boundaries enforced as Python package boundaries with
import-linter in CI. Every async hand-off goes through a bus interface
that has two implementations (in-process for monolith mode, NATS JetStream
for split mode). When a SOC needs to scale a component out, the code
doesn't change.

**REST plus OpenAPI as the primary API.** GraphQL is a fine fit for some
problems; it's also a learning-curve tax for everyone whose first
interaction with a CTI platform is `curl`. Prow CTI optimises for the
curl case. A GraphQL adapter can come later for teams that want it.

**Python end to end.** The CTI ecosystem and its connector authors
overwhelmingly work in Python. Same language for the platform and for
contributors lowers the bar to the most important contribution Prow CTI
can receive: a new connector.

## What's planned

The roadmap is broken into four milestones, each independently useful:

**v0.1 — Walking skeleton.** Backend, Postgres schema, STIX
validate/store/retrieve, the CISA KEV connector, a minimal UI, local
auth, single Docker image. Demo: `docker run prow/prow-cti:0.1` and
import KEV on first boot.

**v0.2 — Connector library and UX.** Connector SDK on PyPI, hot-reload
dev loop, test harness, the first batch of connectors (MITRE ATT&CK,
abuse.ch URLhaus, MISP, and more), graph visualisation, and OIDC. This
is the milestone where "SSO is free" becomes a thing you can actually
deploy.

**v0.3 — Multi-user and automation.** Granular RBAC, immutable audit log,
enricher chains with a visual builder, webhook subscriptions, optional
OpenSearch backend, public connector catalog.

**v1.0 — Federation.** TAXII 2.1 client and server, per-collection
sharing rules, trust groups, signed intel between peers, dissemination
workflows, and an LTS branch with a 12-month security commitment.

A detailed roadmap will land in the repository alongside v0.1.

## Sustainability

Apache 2.0 across the codebase means Prow has to make money some other
way to last. The plan, stated up front so it's holdable to:

- **Hosted Prow CTI** — same codebase, operated by us, for teams that
  don't want to run their own.
- **Support contracts** for organisations that need a number to call.
- **Custom development** for orgs with specific connector or workflow
  needs.
- **Training**.

What Prow will not do: gate features behind a commercial tier. SSO,
audit logs, RBAC, multi-tenancy, and automation stay in the project.

## Get involved

The repository is in scaffold state. The most useful things to do right
now, in roughly increasing order of effort:

- **Watch the repo** to see v0.1 land.
- **Tell us about a feed.** If there's a CTI source you'd want a
  connector for, open an issue with the source URL and a brief
  description of what it provides. The v0.2 connector list is shaped by
  what real users want first.
- **Open an issue** if a design choice looks wrong, even before there's
  code to argue about. Early architectural feedback is the
  highest-leverage contribution Prow CTI can receive right now.
- **Write a connector** once the SDK ships. If a weekend project against
  the SDK turns out to be harder than that, treat it as a bug in the SDK
  and tell us.

A `CONTRIBUTING.md` with the full process will land alongside v0.1.

## License

[Apache License 2.0](LICENSE). The whole project, no carve-outs.

## Project status

| | |
|---|---|
| Product | Prow CTI |
| Version | 0.0.0 (scaffold) |
| Python | 3.12+ |
| License | Apache-2.0 |
| Maintainer | [Prow](https://github.com/prow-sh) |