# Prow Connector SDK — Specification

This document is the contract between the prow platform and connector authors.
It is the single most important DX document in the project. The walking-
skeleton connector (CISA KEV) is built against this spec; the framework is
shaped to make this spec ergonomic, not the other way round.

## Design principles

1. **A weekend project, not a platform onboarding.** A competent Python dev
   should ship a working external-import connector in one sitting.
2. **Connector authors write business logic; the framework handles
   plumbing.** Validation, dedup, persistence, retries, scheduling, state,
   metrics, and logging are framework concerns.
3. **Same code, different runtimes.** A connector runs as an `asyncio` task
   in the monolith and as a worker pod in split mode without modification.
4. **Local dev is fast.** Hot reload on file change. No container rebuild
   loop.
5. **Tests are first class.** Ship a fixture-based harness in the SDK so
   contributors can write tests without standing up prow.

## Connector types

| Type | Purpose | Example |
|---|---|---|
| `external_import` | Pull from a source on a schedule | URLhaus, MISP, MITRE ATT&CK |
| `stream` | Push events to an external system | Splunk HEC, blocklist, webhook |
| `enrichment` | Given an observable, look it up and enrich | VirusTotal, AbuseIPDB, Shodan |
| `internal_export` | Generate exports from prow data | STIX bundle, Suricata rules, IOC list |
| `internal_import` | Process user-uploaded artefacts | PDF report → extracted IOCs |

## Package layout

```
prow-connector-<name>/
├── pyproject.toml
├── manifest.yaml
├── README.md
├── LICENSE                # Apache 2.0 by convention
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

## Manifest

The `manifest.yaml` is the declarative metadata. Prow reads it to build
config UI, validate user-supplied configuration, and populate the connector
catalog.

```yaml
name: urlhaus                      # unique slug, kebab-case
display_name: "abuse.ch URLhaus"
version: 0.1.0                     # semver
type: external_import              # one of the five types above
author: "Your Name <you@example.com>"
license: Apache-2.0
homepage: https://github.com/prow-cti/connectors/tree/main/urlhaus
description: |
  Pulls malicious URL submissions from abuse.ch URLhaus.

# Scheduling — only meaningful for external_import and stream
schedule:
  default_interval: "1h"           # ISO 8601 duration or human-friendly
  cron_supported: true             # connector accepts cron expressions
  jitter: true                     # framework adds jitter to avoid thundering herd

# JSON Schema for user-provided configuration
config_schema:
  type: object
  required: [api_key]
  properties:
    api_key:
      type: string
      secret: true                 # framework redacts in logs and UI
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

# What STIX object types this connector emits or consumes
provides:                          # for external_import / internal_import
  - indicator
  - url
  - file
  - relationship
consumes:                          # for stream / enrichment / internal_export
  - indicator

# For catalog browsing and search
data_sources:
  - https://urlhaus.abuse.ch/

# Default markings applied if connector does not set them explicitly
tlp_default: white

# Operational
runtime:
  python_min: "3.12"
  memory_hint_mb: 128              # rough hint for split-mode pod sizing
  network_egress: required         # 'required', 'optional', 'none'

# Deprecation signaling — when this connector becomes unmaintained
status: active                     # 'active', 'deprecated', 'broken'
```

## Connector class — `external_import` example

```python
from datetime import timedelta
from prow.connector import ExternalImportConnector, ConnectorContext
from prow.stix import bundle, indicator, url_observable, relationship

class UrlhausConnector(ExternalImportConnector):

    async def fetch(self, ctx: ConnectorContext) -> None:
        """Called by the framework on the configured schedule."""
        since = ctx.last_run_at or (ctx.now - timedelta(days=7))

        async for entry in self._stream_urlhaus(ctx, since):
            obs = url_observable(value=entry.url)
            ind = indicator(
                name=f"Malicious URL: {entry.url}",
                pattern=f"[url:value = '{entry.url}']",
                pattern_type="stix",
                confidence=ctx.config["confidence"],
                valid_from=entry.first_seen,
                indicator_types=["malicious-activity"],
            )
            rel = relationship(ind, "based-on", obs)
            await ctx.emit(bundle([obs, ind, rel]))

        ctx.log.info("urlhaus run complete", extra={"objects_emitted": ctx.metrics.emitted})

    async def _stream_urlhaus(self, ctx, since):
        async with ctx.http() as client:                # framework HTTP client
            response = await client.get(
                "https://urlhaus-api.abuse.ch/v1/urls/recent/",
                headers={"Auth-Key": ctx.config["api_key"]},
            )
            response.raise_for_status()
            for row in response.json().get("urls", []):
                yield self._parse(row)

    def _parse(self, row): ...
```

## Connector class — `enrichment` example

```python
from prow.connector import EnrichmentConnector, ConnectorContext, EnrichmentRequest

class VirusTotalConnector(EnrichmentConnector):

    supports_observable_types = ["ipv4-addr", "domain-name", "url", "file"]

    async def enrich(self, ctx: ConnectorContext, request: EnrichmentRequest) -> None:
        observable = request.observable
        async with ctx.http() as client:
            result = await client.get(
                f"https://www.virustotal.com/api/v3/{self._endpoint(observable)}",
                headers={"x-apikey": ctx.config["api_key"]},
            )
            if result.status_code == 404:
                return
            result.raise_for_status()
            await ctx.emit(self._to_bundle(observable, result.json()))
```

## `ConnectorContext` — what the framework gives you

```python
class ConnectorContext:
    # Identity
    connector_id: str
    instance_id: str               # for multiple configs of same connector

    # Time
    now: datetime                  # framework-injected for testability
    last_run_at: datetime | None
    next_run_at: datetime | None

    # Config (validated against config_schema)
    config: dict[str, Any]

    # State (persisted across runs)
    cursor: str | None             # convenience: opaque cursor string
    async def set_state(key: str, value: JsonValue) -> None: ...
    async def get_state(key: str, default=None) -> JsonValue: ...

    # Emission
    async def emit(stix_bundle: dict | Bundle) -> EmitResult: ...

    # I/O helpers
    def http() -> AsyncHTTPClient: ...   # configured retries, UA, optional proxy
    def files() -> FileStorage: ...      # local FS / S3-compatible

    # Logging & metrics
    log: structlog.BoundLogger
    metrics: ConnectorMetrics      # .emitted, .errors, .duration_ms

    # Cancellation
    cancelled: asyncio.Event       # cooperative cancellation signal
```

## Lifecycle hooks

```python
class ExternalImportConnector(ConnectorBase):
    async def setup(self, ctx): ...        # called once on startup
    async def fetch(self, ctx): ...        # called on schedule
    async def teardown(self, ctx): ...     # called on shutdown
    async def health(self, ctx) -> Health: # optional health probe
        return Health.ok()
```

## Local development loop

```bash
# Scaffold a new connector
prow connector init --type external_import my-feed

# Run prow with hot reload watching one or more connector packages
prow connector dev ./prow-connector-my-feed

# Run the connector once against fixtures, snapshot the output bundle
prow connector test ./prow-connector-my-feed --fixture sample_response.json

# Validate manifest and config schema
prow connector validate ./prow-connector-my-feed
```

`prow connector dev` watches the package source, reloads the connector on
change, and runs it against the local prow instance. Logs stream to the
terminal. This loop should be sub-second from save to re-run.

## Testing

The SDK ships a `prow.connector.testing` module:

```python
from prow.connector.testing import ConnectorTestCase, http_fixture

class TestUrlhaus(ConnectorTestCase):
    connector_class = UrlhausConnector
    config = {"api_key": "test", "confidence": 80}

    @http_fixture("fixtures/recent_urls.json")
    async def test_emits_indicators_for_recent_urls(self, ctx):
        await self.connector.fetch(ctx)
        emitted = ctx.captured_bundles
        assert len(emitted) == 50
        assert all(b.objects[0].type == "url" for b in emitted)
```

`http_fixture` decorates the test with a recorded HTTP response so the
connector code runs unmodified but never makes a real network call.

## Distribution and discovery

- Connectors are published to PyPI as `prow-connector-<name>`.
- Prow installations discover connectors via Python entry points on the
  `prow.connectors` group.
- The public catalog at `connectors.prow.io` (eventual) reads PyPI plus a
  curated index. Catalog entries show: signed-by, last-tested-against-prow-
  version, status (active/deprecated/broken), download counts.

## Versioning and compatibility

- Connectors declare a minimum prow version in their `pyproject.toml`
  (`requires = ["prow-sdk>=0.2,<0.4"]`).
- The SDK follows semver. Breaking changes to the SDK bump the major
  version and trigger a deprecation window of one minor version.
- The framework refuses to load a connector whose declared SDK range
  excludes the current version, with an actionable error.

## What connectors must NOT do

- Touch Postgres, Redis, NATS, or any other infrastructure directly. All
  persistence goes through `ctx.emit()`.
- Manage their own scheduling (the framework calls `fetch()`).
- Implement their own retry loops for emission (the framework handles it).
- Log secrets. The framework redacts known-secret config keys; do not log
  raw config dicts.

## Open questions (to revisit before locking the spec)

- Should `ctx.emit()` be sync-by-default with an explicit `flush()` for
  batching, or always async + framework-batched? Current lean: always async,
  framework batches.
- How to express "this connector needs to run on a worker with more memory"
  in the manifest? Current `runtime.memory_hint_mb` is advisory only.
- Should we support non-Python connectors via a thin RPC? Not for v1.0;
  revisit when there's demand.
