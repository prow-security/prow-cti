# Connector configuration and catalog system — design note

**Date:** 2026-05-16  
**Status:** draft  
**Implements:** [ADR-0007](../04_DECISION_LOG.md#adr-0007--connector-framework-is-first-class-from-day-one)  
**Related:** [Connector SDK](../02_CONNECTOR_SDK.md) · [Connector runtime](connector-runtime.md) · [`src/prow/config/`](../../src/prow/config/)

---

## Goals

- Establish a **single source of truth** for which connectors are enabled, how they are configured, and how often they run — one YAML file instead of scattered environment variables and ad hoc flags such as `PROW_SKIP_KEV_IMPORT`.
- Ship **built-in connectors enabled by default** with sensible defaults in `prow.yml.example`; operators opt out by setting `enabled: false`, not opt in.
- Support **community connectors** installed as Python packages (`pip install prow-connector-misp`); discovery is automatic via entry points, but configuration is explicit opt-in.
- Enable **per-connector data management**: purge all objects ingested by one connector instance without touching another connector's provenance rows.
- Apply **config changes on restart** without code changes; no hot-reload in v0.2.
- Act as the **bridge between operator intent** (YAML file plus top-level env overrides) and the supervisor's `add_instance(instance_id, entry_point_name, config)` API, including manifest `config_schema` validation before spawn.
- Keep connector packages **free of configuration I/O**: connectors never read `prow.yml`, `.env`, or process environment for their own settings; they only see the validated dict on `ConnectorContext.config` after the `hello` exchange, consistent with the settled framework contract.

## Non-goals

- **Not a connector marketplace or web UI** for installing or managing connectors. v0.2 is file-based configuration only.
- **Not runtime hot-reload** of configuration. Operators restart prow (or the container) after editing `prow.yml`.
- **Not multi-tenancy.** One prow deployment, one config file, one Postgres database.
- **Not connector signing, provenance attestation, or security scanning** of community packages. That belongs to the v0.3 public catalog story.

---

## The config file format

Prow reads a single YAML file on startup. Default search order: `prow.yml` in the process working directory, then `/etc/prow/prow.yml` when running in a container image. Override the path with `PROW_CONFIG_FILE` (absolute or relative path).

### Top-level structure

| Section | Purpose |
|---------|---------|
| `connectors` | Ordered list of connector instances. Each item becomes one supervisor instance. |
| `database` | Postgres DSN and pool settings for the whole platform. |
| `api` | HTTP API bind address, port, CORS. |
| `log` | Global structlog level. |

Per-connector fields:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | string | *required* | Entry point name from `[project.entry-points."prow.connectors"]` (e.g. `cisa-kev`, `mitre-attack`). |
| `enabled` | boolean | `true` for built-ins listed in `prow.yml.example`; omitted community connectors are not configured | When `false`, the instance is not registered with the supervisor. |
| `schedule` | string | connector-specific default in `prow.yml.example` | ISO 8601 duration (v0.2) or cron expression (target; see Scheduling). |
| `config` | object | manifest defaults | Validated against the connector's `config_schema` before `add_instance()`. Delivered to the connector via `hello` as `ctx.config`. |

Example (illustrative; see Default `prow.yml` for shipped defaults):

```yaml
connectors:
  - name: cisa-kev
    enabled: true
    schedule: "6h"
    config:
      feed_url: "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
      http_timeout_seconds: 30

  - name: mitre-attack
    enabled: true
    schedule: "24h"
    config:
      stix_url: "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json"
      include_deprecated: false

  - name: urlhaus
    enabled: false
    schedule: "1h"
    config:
      limit: 1000

database:
  url: "postgresql+asyncpg://prow:prow@localhost:5432/prow"
  pool_size: 10

api:
  host: "0.0.0.0"
  port: 8000
  cors_origins: ["*"]

log:
  level: "info"
```

### Format choice: YAML

YAML is the operator-facing format because it matches the surrounding infra toolchain (Docker Compose, Kubernetes, Ansible), supports comments, and is familiar to the CTI operator audience. TOML is acceptable technically but adds a second mental model. JSON lacks comments and is painful for multi-line URLs and lists.

### Environment variable overrides (top-level only)

After loading YAML, prow applies env overrides for **platform** settings only. Convention: `PROW_` prefix, uppercase, nested keys joined with `_`.

| YAML path | Env var | Example |
|-----------|---------|---------|
| `database.url` | `PROW_DATABASE_URL` | Already used in `docker-compose.yml` today. |
| `database.pool_size` | `PROW_DATABASE_POOL_SIZE` | |
| `api.host` | `PROW_API_HOST` | |
| `api.port` | `PROW_API_PORT` | |
| `log.level` | `PROW_LOG_LEVEL` | |

**Individual connector `config` fields are not overridable via env vars.** The combinatorics (connectors × fields × instances) explode, and env-based per-connector config recreates the scattered-configuration problem this system removes. Secrets in connector config are addressed in Open questions (`${VAR}` substitution).

`PROW_CONFIG_FILE` selects the file path; it is not a nested override.

### Built-in default: enabled

Built-in connectors registered in the main `pyproject.toml` appear in `prow.yml.example` with `enabled: true`. If no `prow.yml` exists at startup, prow synthesizes an in-memory config equivalent to all built-ins enabled with manifest defaults and the default schedules in the table below — the zero-config `docker compose up` path.

Community connectors discovered via `importlib.metadata` entry points `prow.connectors` are **never** auto-enabled. The operator adds an explicit list entry.

### Relationship to today's `Settings`

The repo already has `prow.config.settings.Settings` (pydantic-settings, `PROW_DATABASE_URL`, pool sizes). Pass A **folds** those fields into `ProwConfig.database` and routes env overrides through the loader's single override table. Call sites that today call `get_settings()` migrate to receiving `ProwConfig` from the application bootstrap. This preserves the modular-monolith rule from [Architecture §3](../01_ARCHITECTURE.md#3-architectural-principles): configuration is a `prow.config` concern; `prow.connector` and `prow.db` depend on typed config objects, not on YAML parsing.

### Discovery at startup

1. Load and validate `ProwConfig`.
2. Enumerate all entry points in group `prow.connectors` (built-in + installed community packages).
3. For each `connectors:` list entry, verify `name` resolves to an entry point; if not, log an error and skip that entry (other instances still start).
4. Log at INFO any discovered entry points with no config entry (hints for community packages the operator installed but did not enable).

---

## Built-in vs community connectors

The distinction is **distribution and defaults**, not capability. Both kinds use the same manifest, `config_schema`, `ConnectorContext`, supervisor lifecycle, and persistence provenance.

### Built-in connectors

- Live under `src/prow/connectors/` and are registered in the main package's `[project.entry-points."prow.connectors"]`.
- Listed in `prow.yml.example` with documented defaults.
- **Enabled by default** when using the example file or the zero-config fallback.
- Stable **instance IDs** derived from config list position (see below).
- **Purge** and **run** CLI commands target the entry point `name` and affect all instances sharing that name unless an instance suffix is given (advanced).

Shipped built-ins for v0.2: `cisa-kev`, `mitre-attack`, `urlhaus`, `threatfox`, `malwarebazaar`.

### Community connectors

- Distributed as separate packages (e.g. `prow-connector-misp`) that register `prow.connectors` entry points on `pip install`.
- Discovered at startup; prow logs available entry point names not present in config (informational).
- **Opt-in only:** operator adds a `connectors:` entry with `name` matching the entry point.
- Same validation path: manifest `config_schema` → supervisor → `hello` → `ctx.config`.
- Operators are responsible for version compatibility via each manifest's `sdk_version` range; prow does not pin community package versions.

---

## The connector instance model

Each element of `connectors:` creates exactly one **connector instance**: one entry point, one config dict, one subprocess (production) or supervised task, one schedule.

**Instance ID:** `{name}-{index}` where `index` is the zero-based position of that entry in the `connectors` list. A single `cisa-kev` entry is `cisa-kev-0`. Two `urlhaus` entries with different configs are `urlhaus-0` and `urlhaus-1`.

The instance ID is written to `stix_objects.source_connector_instance_id` (and related ingest paths) and is the purge key. It is **stable across restarts only if the list order is unchanged**. Reordering entries reassigns IDs and breaks provenance continuity — treat reordering as a migration: purge old IDs or accept orphaned rows. Document this prominently in operator docs.

**Display name** in UI and APIs comes from the manifest `display_name`, not the instance ID. The dashboard must eventually list instances from the supervisor rather than a hardcoded map (Open questions).

The supervisor API remains:

```text
add_instance(instance_id, entry_point_name, config)
```

The config loader maps each enabled YAML entry to one `add_instance()` call after validation.

**Config validation pipeline** (per instance, before spawn):

1. Resolve `name` → entry point → connector module path → `manifest.json`.
2. Merge operator `config` onto manifest JSON Schema defaults (missing keys filled from `default` in schema).
3. Run JSON Schema validation (`config_schema`); on failure, log connector name, instance ID, and JSON pointer, skip instance.
4. Collect `secret: true` property paths for log redaction (existing supervisor behavior).
5. Call `supervisor.add_instance(instance_id, entry_point_name, validated_config)`.

Connectors must not re-validate beyond defensive asserts; the runtime already guarantees shape.

---

## Scheduling

Each instance has a `schedule` field. Two formats are specified; v0.2 ships **interval (ISO 8601 duration) only**.

| Format | Example | Semantics |
|--------|---------|-----------|
| ISO 8601 duration | `"1h"`, `"30m"`, `"24h"`, `"7d"` | After a run **completes**, wait the duration, then trigger the next fetch. Long runs do not stack overlapping fetches; the timer starts at completion (see Open questions). |
| Cron | `"0 */6 * * *"` | Run at wall-clock times. **Target for v0.2.x**; not required for the first scheduler merge. |

The scheduler module (initially under `prow.config.scheduler` or `prow.scheduler`) registers timers per enabled instance on startup. When a timer fires, it asks the supervisor to run `fetch()` on a `ready` instance (respecting `running` / circuit-broken state). The supervisor already owns subprocess lifecycle, health probes, and restarts; the scheduler owns **when** to start work.

Default schedules for built-ins (also used in zero-config fallback and `prow.yml.example`):

| Connector (`name`) | Default `schedule` | Rationale |
|--------------------|-------------------|-----------|
| `cisa-kev` | `6h` | Catalog updates on CISA's cadence; not real-time. |
| `mitre-attack` | `24h` | Enterprise ATT&CK releases are infrequent. |
| `urlhaus` | `1h` | High-velocity IOC feed. |
| `threatfox` | `1h` | Same class as URLhaus. |
| `malwarebazaar` | `6h` | Sample metadata; slower than live IOC streams. |

---

## Per-connector data management

Disabling a connector stops new ingests but leaves historical rows. **Purge** makes disable meaningful for disk and UI accuracy.

CLI commands extend the existing `prow connector` group in `src/prow/cli/connector.py`:

### `prow connector list`

Prints all configured instances: entry point `name`, instance ID, enabled flag, supervisor state (running / stopped / disabled / circuit-broken), object count in `stix_objects` for that `source_connector_instance_id`, and last successful run timestamp (from connector state or ingest metadata).

### `prow connector purge <name>`

**Destructive.** Deletes rows from `stix_objects`, `stix_relationships`, and `stix_observables_index` where `source_connector_instance_id` matches any instance ID for that entry point name (`<name>-0`, `<name>-1`, …). Prompts for confirmation unless `--yes`. Does not delete `connector_state` keys until a follow-up pass defines whether state should be cleared — v0.2 clears ingest tables only.

Warning text must state that objects ingested by this connector may still be referenced in relationships emitted by **other** connectors; purge removes rows by provenance, not a global graph repair. Relationship rows whose `source_ref` / `target_ref` point at deleted objects may become dangling until a future graph-hygiene job exists; v0.2 does not run automatic orphan cleanup.

`connector_state` rows keyed by instance ID should be deleted on purge so a re-enabled connector does not resume cursors against empty data. Pass B implements state table cleanup in the same transaction as ingest deletes where feasible.

### `prow connector run <name> [--once]`

Triggers an immediate fetch for the named instance (default: `<name>-0` if only one; flag `--instance` for multi-instance). Bypasses the schedule timer. `--once` runs a single fetch and exits without registering a recurring timer — production analogue to `prow connector dev --no-watch`.

---

## The config loader

Module layout (replaces the minimal `Settings`-only scaffold; database fields migrate into `ProwConfig`):

```text
src/prow/config/
├── __init__.py      # exports ProwConfig, load_config()
├── schema.py        # Pydantic models mirroring YAML
└── loader.py        # read file, merge defaults, env overrides, validate
```

- `load_config(path: Path | None = None) -> ProwConfig` — resolve path (`PROW_CONFIG_FILE` → `prow.yml` → `/etc/prow/prow.yml`), parse YAML, apply top-level env overrides, validate.
- If no file exists, return built-in defaults (all built-in connectors enabled, schedules from table above, manifest default `config` objects).
- Loaded **once per process start**. Passed into application wiring by constructor injection; tests construct `ProwConfig` directly. Avoid a second global singleton alongside the old `get_settings()` — migrate callers to `ProwConfig.database` and deprecate duplicate env reads.

Connector config validation: for each enabled entry, resolve entry point → load manifest → `validate_connector_instance_config()` (existing supervisor helper) → on failure, log and skip that instance only (same partial-start behavior as [connector runtime](connector-runtime.md#configuration-loading-and-validation)).

---

## Default `prow.yml`

- **`prow.yml.example`** — committed; every built-in connector with comments on each field and default schedules.
- **`prow.yml`** — gitignored; operator copy.

Local workflow:

```bash
cp prow.yml.example prow.yml
# edit prow.yml
docker compose up
```

Docker Compose addition:

```yaml
prow:
  volumes:
    - ./prow.yml:/app/prow.yml:ro
```

Existing `PROW_DATABASE_URL` in Compose continues to override `database.url`. Remove `PROW_SKIP_KEV_IMPORT` once KEV honors `enabled: false` in config (migration note in Pass B).

When both a mounted `prow.yml` and `PROW_DATABASE_URL` are set, **env wins** for `database.url` after YAML parse. This matches twelve-factor practice: Compose keeps the DSN pointed at the `postgres` service without editing the file on disk.

---

## Catalog vs configuration

This note defines **configuration** (how instances run), not a **catalog** (searchable registry of installable connectors). The catalog UI, signing, and `pip install` automation are out of scope. Operationally, "catalog" today means: entry points visible to Python packaging plus whatever manifests ship inside those packages. `prow connector list` is the operator's catalog view for the current deployment.

---

## Implementation order

### Pass A — config loader and schema

`prow.config` Pydantic models, YAML loader, env override layer, `prow.yml.example`, unit tests with fixture YAML files. No supervisor or connector changes.

**Estimated LOC:** ~350 implementation, ~250 tests.

### Pass B — supervisor wiring

On application startup: `load_config()` → for each enabled connector → `supervisor.add_instance()`. Interval scheduler. CLI: `list`, `purge`, `run`. Wire API/worker entrypoints to inject `ProwConfig`. Retire env-only KEV toggles.

**Estimated LOC:** ~700 implementation, ~450 tests.

### Pass C — four new connectors

`mitre-attack`, `urlhaus`, `threatfox`, `malwarebazaar`: manifests, entry points, `fetch()` reading `ctx.config`, integration tests, `prow.yml.example` entries. KEV already exists; align with config-driven enablement only.

**Estimated LOC:** ~1,200 implementation, ~800 tests (combined).

**Total across passes:** ~2,250 implementation + ~1,500 tests ≈ **3,750 LOC** (order-of-magnitude; connector complexity dominates Pass C).

---

## Open questions

| Question | v0.2 recommendation |
|----------|---------------------|
| **Multi-instance UI** | Defer dynamic "Connected Sources" to a small UI pass with Pass B; supervisor exposes instance list API. |
| **`${VAR}` secret substitution in YAML** | **Defer** past v0.2. v0.2 accepts API keys in `prow.yml` plaintext for self-hosted installs; document risk. Operators can use external secret mounts that render a full `prow.yml` at container start. Revisit for v0.2.1. |
| **Schedule drift** | **Decided:** interval means delay after last run **completed**, not after start. |
| **Community version pinning** | Document operator responsibility; optional `prow connector list` shows installed distribution version from `importlib.metadata`. No prow-level pin field in v0.2. |
| **Cron scheduling** | Specified; implement after interval scheduler is stable. |
| **Purge vs graph integrity** | v0.2: provenance delete only; no cascade into other connectors' objects. |

---

## References

- [ADR-0007 — Connector framework is first-class from day one](../04_DECISION_LOG.md#adr-0007--connector-framework-is-first-class-from-day-one)
- [ADR-0008 — Connectors as tasks or worker pods](../04_DECISION_LOG.md#adr-0008--connectors-run-as-in-process-tasks-monolith-or-worker-pods-split)
- [Connector runtime design note](connector-runtime.md)
- [Connector SDK specification](../02_CONNECTOR_SDK.md)
- [Architecture §3 — Modular monolith principles](../01_ARCHITECTURE.md#3-architectural-principles)
- [CISA KEV manifest](../../src/prow/connectors/kev/manifest.json)
