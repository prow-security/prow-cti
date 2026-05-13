# Prow Connector SDK — Specification

This document is the contract between the prow platform and connector authors.
It is the single most important DX document in the project. The walking-
skeleton connector (CISA KEV) is built against this spec; the framework is
shaped to make this spec ergonomic, not the other way round.

> **Status (Pass D, 2026-05).** v0.1 of the framework has shipped:
> protocol library, stdio and in-process transports, supervisor, subprocess
> runner, dev-mode runtime, watcher, and the `prow connector` CLI surface
> (`dev`, `test`, `validate`). The KEV walking-skeleton connector is not
> yet built. Several SDK features mentioned in the original draft of this
> document are scoped for **v0.2 or later** and are marked as such below
> rather than removed; the goal is for a contributor reading this doc
> to know which APIs they can call today and which ones they have to wait
> for.

## Design principles

1. **A weekend project, not a platform onboarding.** A competent Python dev
   should ship a working external-import connector in one sitting.
2. **Connector authors write business logic; the framework handles
   plumbing.** Validation, dedup, persistence, retries, scheduling, state,
   metrics, and logging are framework concerns.
3. **Same code, different runtimes.** A connector runs as an `asyncio` task
   in dev mode and as a subprocess in production without modification.
4. **Local dev is fast.** Hot reload on file change. No container rebuild
   loop.
5. **Tests are first class.** Ship a fixture-based harness in the SDK so
   contributors can write tests without standing up prow. *(planned for
   v0.2+; see "Testing" below.)*

## Connector types

The framework currently ships **`ConnectorBase`** as the only base class.
Type-specific base classes (`ExternalImportConnector`, `EnrichmentConnector`,
`StreamConnector`, `InternalImportConnector`, `InternalExportConnector`) are
deferred to v0.2+ as each connector type's lifecycle (scheduled fetch vs.
request/response enrichment vs. push stream) lands. Today, all v0.1
connector code subclasses `ConnectorBase` and the dev runtime probes for a
`fetch()` method on the instance.

| Type | Purpose | Status |
|---|---|---|
| `external_import` | Pull from a source on a schedule | v0.1 — supported via `ConnectorBase.fetch()` |
| `stream` | Push events to an external system | v0.2+ |
| `enrichment` | Given an observable, look it up and enrich | v0.2+ |
| `internal_export` | Generate exports from prow data | v0.2+ |
| `internal_import` | Process user-uploaded artefacts | v0.2+ |

The `manifest.type` field accepts any of these strings, but `prow connector
dev` only runs `external_import` today; other types are rejected with an
explicit error.

## Package layout

```
prow-connector-<name>/
├── pyproject.toml
├── manifest.json        # JSON is the default and only required parser today
├── README.md
├── LICENSE              # Apache 2.0 by convention
├── src/prow_connector_<name>/
│   ├── __init__.py
│   └── connector.py
└── tests/
    ├── fixtures/
    │   └── sample_response.json
    └── test_connector.py
```

The `pyproject.toml` registers the connector via Python entry points so prow
auto-discovers it on `pip install`:

```toml
[project.entry-points."prow.connectors"]
urlhaus = "prow_connector_urlhaus.connector:UrlhausConnector"
```

`prow connector dev` and `prow connector validate` require exactly one entry
under the `prow.connectors` group in the package's `pyproject.toml`. Multiple
entries are a configuration error in v0.1.

## Manifest

The `manifest.json` (or `manifest.yaml`) is the declarative metadata. Prow
reads it to validate user-supplied configuration today, and will eventually
use it to build config UI and populate the connector catalog. JSON is the
canonical format: `manifest.yaml` is accepted but requires PyYAML, which is
**not** a project dependency — install it separately if you prefer YAML.

### What `validate_manifest_shape` enforces today

Only three keys are required at the structural-validation step:

- `name` — string slug
- `type` — string (one of the connector-type strings; only `external_import`
  is operationally supported)
- `config_schema` — JSON Schema object validating user-supplied config

The rest of the fields listed below are accepted by the manifest loader
(extra keys are not rejected) but are **not** yet consumed by any code path.
They are reserved for v0.2+ when scheduling, the catalog, and the connector
UI come online.

### Full manifest example (v0.1 reads `name`, `type`, `config_schema`; rest is forward-looking)

```yaml
# --- consumed in v0.1 ---
name: urlhaus                      # unique slug, kebab-case
type: external_import              # required; only external_import runs today
config_schema:                     # JSON Schema for user config
  type: object
  required: [api_key]
  properties:
    api_key:
      type: string
      secret: true                 # secrets are redacted by LogForwarder
      description: "URLhaus API key (free with signup at urlhaus.abuse.ch)"
    confidence:
      type: integer
      default: 80
      minimum: 0
      maximum: 100
    tlp:
      type: string
      enum: [white, green, amber, red]
      default: white

# --- accepted but unused in v0.1; consumed in v0.2+ ---
display_name: "abuse.ch URLhaus"   # catalog display
version: 0.1.0                     # semver of the connector
author: "Your Name <you@example.com>"
license: Apache-2.0
homepage: https://github.com/prow-cti/connectors/tree/main/urlhaus
description: |
  Pulls malicious URL submissions from abuse.ch URLhaus.

schedule:                          # scheduler not yet implemented
  default_interval: "1h"
  cron_supported: true
  jitter: true

provides:                          # catalog metadata
  - indicator
  - url
  - file
  - relationship
consumes: []

data_sources:
  - https://urlhaus.abuse.ch/

tlp_default: white

runtime:                           # split-mode hints
  python_min: "3.12"
  memory_hint_mb: 128
  network_egress: required

status: active                     # 'active', 'deprecated', 'broken'
```

`config_schema.properties.*.secret = true` is honoured today: any string
value of a `secret: true` field is redacted from forwarded logs and crash
traces before they leave the connector subprocess (see
`prow.connector.log_forwarder`).

## Connector class — `external_import` example (v0.1, against `ConnectorBase`)

```python
from datetime import timedelta
from prow.connector.base import ConnectorBase
# STIX object constructors live in prow.stix.types as classes;
# free-function constructors (bundle/indicator/url_observable/relationship)
# are not exposed in v0.1.
from prow.stix.types import Bundle, Indicator


class UrlhausConnector(ConnectorBase):

    async def setup(self) -> None:
        """Called once after construction, before the protocol loop waits."""

    async def fetch(self) -> None:
        """Called by the framework on the configured schedule (v0.1: once per dev run)."""
        ctx = self.ctx                              # ConnectorContext
        since = ctx.last_run_at or (ctx.now - timedelta(days=7))

        # Connector authors are responsible for any HTTP client today.
        # A framework-managed httpx client (ctx.http) is deferred to v0.2+.
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://urlhaus-api.abuse.ch/v1/urls/recent/",
                headers={"Auth-Key": ctx.config["api_key"]},
            )
            response.raise_for_status()

        objects = []
        for row in response.json().get("urls", []):
            indicator = Indicator(
                id=f"indicator--{row['id']}",
                created=row["dateadded"],
                modified=row["dateadded"],
                pattern=f"[url:value = '{row['url']}']",
                pattern_type="stix",
                valid_from=row["dateadded"],
            )
            objects.append(indicator.model_dump(mode="json"))

        bundle = {"type": "bundle", "id": f"bundle--{ctx.connector_instance_id}", "objects": objects}
        result = await ctx.emit(bundle)
        ctx.log.info(
            "urlhaus run complete",
            accepted=result.accepted,
            duplicates=result.duplicates,
        )

    async def teardown(self) -> None:
        """Called once after shutdown has been observed."""
```

### Connector class — other types

`EnrichmentConnector`, `StreamConnector`, `InternalImportConnector`, and
`InternalExportConnector` are **deferred to v0.2+** along with their
lifecycle hooks (`enrich`, `push`, etc.). For now, all connectors subclass
`ConnectorBase` and the dev runtime invokes `fetch()` if present.

## `ConnectorContext` — what the framework gives you today

```python
class ConnectorContext:
    # Identity
    connector_instance_id: str

    # Validated config (already checked against config_schema)
    config: dict[str, Any]

    # Time
    @property
    def now(self) -> datetime: ...        # framework-injected for testability
    last_run_at: datetime | None          # may be None on the first run

    # Cancellation
    @property
    def cancelled(self) -> asyncio.Event: ...   # cooperative cancellation signal

    # Emission — awaited round-trip with the runtime
    async def emit(self, bundle: Bundle | dict[str, Any]) -> EmitResult: ...

    # Connector-owned state (persisted across runs in production)
    async def set_state(self, key: str, value: JsonValue) -> None: ...
    async def get_state(self, key: str, default=None) -> JsonValue: ...

    # Logging — routed through the protocol log forwarder
    log: _RoutingBoundLogger               # structlog-like .debug/.info/.warning/.error/.critical
```

`EmitResult` is a frozen dataclass with three fields:

```python
@dataclass(frozen=True)
class EmitResult:
    accepted: int
    duplicates: int
    failures: list[ValidationFailure]
```

### Not yet on `ConnectorContext` (deferred to v0.2+)

- **`ctx.http()`** — a framework-managed `httpx.AsyncClient` with configured
  retries, user-agent, optional proxy, and recorded HTTP fixture support for
  the test harness. v0.1 connectors instantiate their own client.
- **`ctx.files()`** — local-FS / S3-compatible storage handle. v0.1
  connectors that need scratch space manage their own paths.
- **`ctx.metrics`** — a typed `ConnectorMetrics` surface with `.emitted`,
  `.errors`, `.duration_ms`. The wire protocol carries metrics today
  (`MetricForwarder`), but the connector-facing `ctx.metrics` accessor has
  not been added.
- **`ctx.cursor`** — a convenience opaque-cursor string. Until then,
  `await ctx.set_state("cursor", ...)` and `await ctx.get_state("cursor")`
  are the supported pattern.
- **`ctx.next_run_at`** — meaningful once the scheduler ships in v0.2+.
- **Scope-bound `ctx.log`** — today's logger is a thin async-routing wrapper
  that schedules log frames on a best-effort task; it does not implement the
  full structlog `BoundLogger` surface.

These are intentionally listed so connector authors know what to use today
and what to expect later.

## Lifecycle hooks (v0.1)

`ConnectorBase` exposes three optional async hooks. The dev runtime calls
them in this order:

```python
class ConnectorBase:
    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx                # injected by the framework

    async def setup(self) -> None: ...        # called once on startup
    async def teardown(self) -> None: ...     # called once on shutdown
    async def health(self) -> HealthStatus:   # responding to runtime health probes
        return HealthStatus.HEALTHY
```

`fetch()` is **not** declared on `ConnectorBase`. The dev runtime invokes
it via `hasattr(conn, "fetch")` and calls `conn.fetch()` with no arguments.
This is intentional — type-specific base classes will declare type-specific
async hooks (`fetch`, `enrich`, `push`, `consume`) as they land in v0.2+.

## Local development loop

```bash
# Validate manifest, entry point, and importability — exits 0 on success.
prow connector validate ./prow-connector-my-feed

# Run prow's dev runtime with hot reload watching one or more connector
# packages. Logs and emits stream to the terminal as JSON lines.
prow connector dev ./prow-connector-my-feed

# Same, but run fetch() once and exit cleanly (good for smoke tests).
prow connector dev --no-watch ./prow-connector-my-feed

# Offline connector tests against recorded HTTP fixtures.
# NOTE: stub in v0.1; exits with a roadmap pointer. Planned for v0.2.
prow connector test ./prow-connector-my-feed --fixture sample_response.json
```

`prow connector init` (scaffold a new package) is deferred to v0.2+. For
now, copy `tests/connector/dev_fixtures/good_pkg/` as a starting point.

`prow connector dev` watches the package source with `watchdog`, reloads the
connector on change, and runs `fetch()` again. The reload loop cancels any
in-flight operation, calls `teardown()`, evicts the connector module from
`sys.modules`, reimports, calls `setup()`, and re-runs. See
[`docs/design/connector-runtime.md`](design/connector-runtime.md#dev-mode-asyncio-runtime)
for the reload caveats — keep your modules boring (no import-time network
calls, no global mutable caches, no metaclass tricks).

## Testing — *deferred to v0.2+*

The original SDK draft showed a `prow.connector.testing` module with a
`ConnectorTestCase` and an `http_fixture` decorator. Both are deferred to
v0.2+. The `prow.connector.testing` package currently exists, but it holds
the bundled test-connector packages used by the framework's own test suite
(`minimal_test`, `lifecycle_test`, `hang_test`, ...), not an author-facing
harness.

Until the v0.2 harness lands, write tests against the connector class
directly: instantiate `ConnectorBase` subclasses with a hand-rolled
`ConnectorContext` that wraps a mock transport, or run
`prow connector dev --no-watch <pkg>` and assert on the JSON-line output.

## What the framework provides today (v0.1, Pass D)

- **Protocol library.** Versioned JSONL envelopes over stdin/stdout, with
  framing, codec, negotiation, and the full v1 message set
  (`hello`/`hello-ack`, `emit`/`emit-ack`, `log`, `metric`,
  `set-state`/`set-state-ack`, `get-state`/`get-state-ack`,
  `health`/`health-ack`, `cancel`/`cancel-ack`, `shutdown`/`shutdown-ack`).
- **Two transports.** `StdioTransport` for production subprocesses and
  `InProcessTransport` for in-process dev mode. Both implement the same
  `ConnectorTransport` structural protocol.
- **Supervisor.** Process spawn, state machine, restart policy with
  exponential backoff and circuit-breaker, health probing, log forwarding
  with secret redaction, metric forwarding through OpenTelemetry, and
  stderr capture.
- **Dev runtime + watcher.** Hot reload, module eviction, stale-task
  cancellation, configurable `stay_alive_after_fetch`.
- **Connector CLI.** `prow connector dev`, `prow connector validate`, and a
  `prow connector test` stub that returns a roadmap pointer.

## What connectors must NOT do

- Touch Postgres, Redis, NATS, or any other infrastructure directly. All
  persistence goes through `await ctx.emit()`.
- Manage their own scheduling. The framework will call `fetch()` — today
  via `prow connector dev`, in v0.2+ via the production scheduler.
- Implement their own retry loops for emission. The framework handles
  retries above the transport.
- Log secrets. The framework redacts known-secret config keys before
  forwarding log records; do not log raw config dicts and do not bypass
  `ctx.log` by writing to stdout (stdout is reserved for the protocol).
- Assume the connector is in the same process as prow. In production it is
  not; in dev it is. Connector code must work in both modes.

## Distribution and discovery

- Connectors are published to PyPI as `prow-connector-<name>`.
- Prow installations discover connectors via Python entry points on the
  `prow.connectors` group.
- A public catalog at `connectors.prow.io` is forward-looking; it is not
  shipped in v0.1.

## Versioning and compatibility

- Connectors declare a minimum prow version in their `pyproject.toml`
  (`requires = ["prow-sdk>=0.2,<0.4"]`) once the SDK is published as its
  own package. The `prow-sdk` separation is also v0.2+.
- The SDK follows semver. Breaking changes to the SDK bump the major
  version and trigger a deprecation window of one minor version.
- The framework refuses to load a connector whose declared SDK range
  excludes the current version, with an actionable error.

## Open questions (to revisit before locking the spec)

- Should `ctx.emit()` ever be sync-by-default with an explicit `flush()`
  for batching, or always async + framework-batched? Current lean: always
  async, framework batches.
- How should "this connector needs to run on a worker with more memory" be
  expressed in the manifest? Current `runtime.memory_hint_mb` is advisory
  only.
- Non-Python connectors via a thin RPC? Not for v1.0; revisit when there
  is demand.
