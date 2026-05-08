# Connector runtime and supervisor — design note

**Date:** 2026-05-07  
**Status:** draft  
**Implements:** [ADR-0011](../adr/ADR-0011-connector-isolation.md) (with applicable amendments from this note)  
**Related:** [Connector protocol](connector-protocol.md) · [Connector SDK](../02_CONNECTOR_SDK.md) · [Architecture §9](../01_ARCHITECTURE.md#9-connector-framework--the-most-important-dx-surface)

---

## Goals

- Specify the **production supervisor** that spawns, monitors, restarts, and shuts down connector subprocesses.
- Specify the **dev-mode asyncio runtime** that bypasses subprocesses so `prow connector dev` keeps sub-second hot reload.
- Define one **`ConnectorContext` shape backed by two transports**: stdio JSONL in production and direct in-process calls in dev.
- Make restart backoff, circuit breaking, health probing, and cancellation propagation operationally explicit.
- Revise ADR-0011's supervisor size estimate honestly now that the lifecycle, protocol, dev runtime, and observability surface are visible.

## Non-goals

- **Not** the wire protocol. `docs/design/connector-protocol.md` owns framing, envelopes, message kinds, and error codes.
- **Not** the connector author's API. Authors write against `ConnectorContext`; this runtime is the framework implementation behind it.
- **Not** the persistence pipeline. The runtime hands acknowledged emits to the ingest/persistence path via `prow.bus`; validation, deduplication, and storage behavior live elsewhere.
- **Not** the scheduler. Cron and interval rules decide when `fetch()` is called; this note covers what happens during a connector run.
- **Not** container or Kubernetes orchestration. Split-mode worker pods and NATS-backed transport are v0.3+ concerns. v1 is local subprocesses plus dev-mode direct calls.

## The two transports

The runtime boundary is a small `ConnectorTransport` protocol, in the Python typing sense: structural interface, not an inheritance hierarchy connector authors see. Its methods correspond to the protocol operations the context needs: `emit`, `set_state`, `get_state`, `log`, `metric`, `health`, `cancel`, and `shutdown`. Methods that the SDK exposes as awaited operations (`emit`, state reads/writes, health, cancellation, shutdown) return only after their protocol ack or direct-call equivalent completes. Fire-and-forget operations (`log`, `metric`) are best-effort.

`StdioTransport` is the production transport. It owns one connector subprocess, serialises runtime-originated operations to JSONL on stdin, reads stdout in a loop, dispatches connector-originated messages, and resolves pending futures by `id_ref`. It also enforces the protocol's 64 in-flight acknowledged-operation ceiling. The transport does not decide restart policy; it reports EOF, malformed protocol, timeouts, and subprocess exit to the supervisor.

`InProcessTransport` is the dev transport. It loads connector code into the local process and calls framework services directly. There is no JSONL serialisation, no pipe buffering, and no protocol negotiation. It still presents the same async method behavior, including an awaited `emit`, so connector code observes the same API contract in both modes.

`ConnectorContext` is constructed with identity, validated config, time fields, helpers, cancellation event, and the selected transport. Connector code never receives or imports the transport. `await ctx.emit(bundle)` is the author's stable action; only the injected transport changes.

## Subprocess lifecycle (production)

**Spawn:** the supervisor starts each production connector instance as `python -c "from prow.connector.runner import main; main()"`. The connector identifier, instance identifier, and validated config are passed in one environment variable, `PROW_CONNECTOR_RUNNER_CONFIG`, encoded as JSON. Environment config keeps argv free of secrets in process listings on platforms where argv is easier to inspect. The runtime still redacts that variable from logs and crash reports.

Stdin and stdout are pipes used only for the JSONL protocol. Stderr is a separate captured stream for tracebacks and dependency noise. The runner main reads the environment config, loads the connector class via the `prow.connectors` Python entry point group, instantiates it, builds the connector-side `ConnectorContext`, and enters the protocol loop.

**Hello exchange:** immediately after spawn, the runtime writes `hello` with runtime version, supported protocol versions, connector identity, instance identity, and config. The connector responds with `hello-ack`, selecting one version. Mismatch is fatal: the runtime closes pipes, terminates the subprocess, logs supported and selected versions, and marks the instance failed. No operational messages are valid before `hello-ack`.

**Operational loop:** after `hello-ack`, runtime messages (`health`, `cancel`, `shutdown`) and connector messages (`emit`, `log`, `metric`, `set-state`, `get-state`) share the same stdout/stdin pair. Acks are matched to pending operations by `id_ref`. Connector-originated requests are dispatched to runtime services, and their acks are written back in order. Multiple acknowledged operations may be in flight up to the protocol limit. The transport preserves per-direction ordering but does not infer cross-direction ordering.

**Shutdown:** graceful shutdown starts with `shutdown`. The connector cancels in-flight work, runs cleanup, sends `shutdown-ack`, flushes stdout, and exits with code 0. The default grace period is 30 seconds. If no `shutdown-ack` arrives, the supervisor sends SIGTERM. After another 10 seconds, it sends SIGKILL where the platform supports it. On Windows, the runtime uses the nearest process-termination primitive and records the weaker signal semantics in logs.

**Crash:** unexpected subprocess exit is detected by process wait completion, stdout EOF, or broken stdin writes. The supervisor drains any remaining stderr, marks pending operations failed, records exit code and last protocol activity, and applies restart policy.

## The supervisor

One supervisor instance lives under `prow.connector.runtime`. It owns the set of configured connector instances for the local runtime. Each instance record holds the subprocess handle, `StdioTransport`, `ConnectorContext`, pid, state, most recent restart timestamps, restart attempt count, current backoff, and last health result.

The per-instance states are `starting`, `ready`, `running`, `draining`, `dead`, `crashed`, and `circuit-broken`.

```text
starting → ready → running → draining → dead
                         ↓
                       crashed → starting (if restartable)
                                → circuit-broken (if not)
```

`starting` begins at spawn and lasts through protocol negotiation. A successful `hello-ack` moves to `ready`. `ready` means the subprocess is alive, protocol-compatible, and waiting for scheduled work. `running` means a connector operation such as `fetch()` or `enrich()` is in flight. The scheduler decides when to enter `running`; the supervisor tracks it so health and cancellation have the right target.

`draining` begins when shutdown is requested, either by runtime stop, config reload, or restart. A graceful `shutdown-ack` and process exit move to `dead`. Unexpected process exit from any active state moves to `crashed`. From `crashed`, the restart policy either schedules a new `starting` attempt after backoff or moves to `circuit-broken`.

Health probes run every 30 seconds for each `ready` or `running` instance. A probe sends `health` and expects `health-ack` within 5 seconds. Two consecutive health failures, whether timeout, malformed ack, or `status: "unhealthy"`, trigger restart. A single `degraded` health result is recorded and exposed but does not restart by itself.

## Restart policy

Restarts use exponential backoff: 1s, 2s, 4s, 8s, then a 30s ceiling for subsequent attempts. The attempt counter resets after the connector has remained healthy for five minutes.

The circuit-break threshold is three restarts inside a five-minute rolling window. Precisely: after recording a restart timestamp, the supervisor looks at restart timestamps newer than `now - 5 minutes`; if there are three or more, the next crash or failed start moves the instance to `circuit-broken` instead of scheduling another spawn.

Circuit-broken means the supervisor stops trying automatically. The connector instance is marked unavailable in runtime status, surfaced through the connector status API, and excluded from scheduled runs. The manifest's packaged `status` field is not rewritten; instance status is operational state, not connector catalog metadata. An operator must call `POST /connectors/{id}/clear-circuit-break` or use the equivalent CLI command to reset attempts and return to `starting`.

Supervisor metrics include restart count, time since last restart, current state, current backoff delay, consecutive health failures, and circuit-break count. The principle is automatic recovery up to a sane limit, then a clear human action. Prow must not spin forever on a broken connector.

## Logs and metrics forwarding

Connector `log` messages are converted to structlog-bound records on prow's main logger. The runtime binds `connector_id`, `instance_id`, connector package name when known, and pid. Connector logs are intentionally interleaved with prow logs so one request or ingest timeline can be read in order.

Connector `metric` messages are emitted through prow's OpenTelemetry meter. Metric names are namespaced as `prow.connector.<instance_id>.<metric_name>`, with connector identity also attached as attributes. The metric message remains fire-and-forget: it is never allowed to block connector progress.

Subprocess stderr is captured continuously and logged at ERROR level with connector identity. This is where Python tracebacks, import failures, and noisy third-party libraries appear. If a connector exits unexpectedly, the final stderr tail is included in the crash diagnostic.

Logs and metrics are not part of supervisor correctness. If the observability backend is down or slow, forwarding fails soft and the runtime continues supervising, ingesting, and shutting down connectors.

## Cancellation propagation

Cancellation flows from prow to the connector. When the runtime cancels an awaited operation, it sends `cancel` and awaits `cancel-ack` as included in the v1 protocol by maintainer amendment. The ack means the connector-side runtime observed the cancellation request and has signalled the operation; it does not mean user cleanup has finished.

Inside the connector process, the runner sets the context's `cancelled` event and cancels the asyncio task running the current operation. Well-behaved connector code sees either a set event or an `asyncio.CancelledError` at the next cancellable await. Existing Python cleanup patterns (`try` / `finally`, context managers, and explicit cancellation checks) run normally.

`shutdown` implies cancellation of all in-flight operations before graceful exit. The connector should stop emitting new bundles after cancellation, finish cleanup, send `shutdown-ack`, and exit.

Cancellation remains cooperative. A connector in blocking synchronous I/O or CPU-bound native code may not observe it. The hard ceiling is supervisor-enforced: if an operation is still in flight 30 seconds after `cancel-ack`, the subprocess receives SIGTERM, then follows the shutdown escalation path.

## Dev-mode asyncio runtime

`prow connector dev` loads the connector class directly into the running prow process. It constructs `InProcessTransport`, builds the same `ConnectorContext` shape, calls `setup()`, and runs connector methods as asyncio tasks. Emits go into the local prow process and local Postgres through the same ingest services production uses. The transport is the only intended behavioral difference.

Dev mode watches connector source files with `watchdog` or the platform equivalent: inotify on Linux, FSEvents on macOS, and `ReadDirectoryChangesW` on Windows. On file change, the dev runtime cancels any in-flight `fetch()` or other operation, waits briefly for cleanup, calls `teardown()`, evicts the connector module from `sys.modules`, reimports it, calls `setup()`, and runs `fetch()` again.

Reimport is the foot-gun. Active asyncio tasks that hold old function or class objects will keep running stale code unless cancelled first, so dev mode cancels aggressively before reload. Python caches modules by name, so `sys.modules` eviction is mandatory but not magic. Import-time side effects can still leak state into other modules.

Connector authors should keep connector modules boring: no global mutable caches, no import-time network calls, no metaclass registration tricks, no reliance on `__init_subclass__` side effects for runtime behavior. If a connector depends on compiled extensions or libraries that cannot be reloaded cleanly, dev mode should report that a full dev-runtime restart is required.

## Configuration loading and validation

On supervisor startup, prow reads configured connector instances from the main application config. Each instance points to a discovered connector entry point and carries a per-instance config dict. The runtime loads the connector's `manifest.yaml`, validates the config dict against `config_schema`, and rejects only the invalid instance. Other connector instances continue starting.

Validation failures include connector ID, instance ID, schema path, and human-readable failure text. Secret fields marked with `secret: true` in the manifest are redacted from logs, metrics, `hello` diagnostics, and crash dumps.

## Resource posture

Per-subprocess RSS depends more on imports than on the supervisor. A minimal connector using `httpx`, `structlog`, and the SDK is expected around 25-35 MB. A typical connector using `prow.stix` and compiled schema validators is closer to 50-70 MB. Heavy dependencies such as `pandas` can push an instance past 200 MB.

Ten typical connector instances on a 4 GB VPS cost roughly 500-700 MB before workload spikes. That is meaningful but not prohibitive. The architecture's lightweight claim still holds for the common solo install running one to three connectors, but power users need a visible budget.

The runtime can later mitigate idle RSS by stopping instances after long inactivity and respawning on demand. That is out of v1 because it complicates scheduling latency, health semantics, and state transitions. v1 should measure and expose memory rather than pretending the cost is negligible.

## Open questions

- **Idle eviction policy:** should the supervisor stop a connector instance after N hours of inactivity and respawn on demand? Resource pressure supports it; cold-start latency and schedule predictability complicate it. Defer to v0.3+.
- **Per-instance resource limits:** cgroups can cap subprocess CPU and memory on Linux. Windows and macOS need different primitives. Defer as a Linux-first hardening pass.
- **Supervisor-as-PID-1 in containers:** when prow is PID 1, it must reap connector children correctly. The entry point should `exec` properly or install a SIGCHLD handler; exact container entrypoint shape needs implementation discovery.
- **Hot-reload of compiled extensions:** dev mode cannot reliably reimport C extensions. Connectors depending on compiled modules may require full dev-runtime restart.
- **Crash dump capture:** stderr tail plus the last N protocol messages would make connector crashes much easier to debug. The runtime should probably persist crash dumps, but format, retention, and secret redaction rules need a follow-up design.

## Conflicts with the existing SDK doc

The SDK doc's `ConnectorContext` definition lists fields and methods but does not explain that `ctx.http()` and `ctx.files()` are framework-provided helpers that must behave consistently across dev and production. The doc should clarify which helpers are local wrappers and which operations cross the transport boundary.

The "Local development loop" section already describes `prow connector dev` at the right level for authors, but it should reference this note for the reload mechanism and its caveats.

The "What connectors must NOT do" list remains correct, but should add: do not assume the connector is in the same process as prow. In production it is not; in dev it is. Connector code must work in both modes.

Recommendation: amend `docs/02_CONNECTOR_SDK.md` in one follow-up PR after both connector design notes are accepted, so SDK-facing language changes coherently.

## LOC estimate revision

ADR-0011's 200-400 LOC estimate is too low for this design. A more honest implementation estimate is:

- Subprocess lifecycle and pipe management: ~250 LOC.
- Protocol parsing and dispatch: ~200 LOC, partly shared with the protocol library.
- State machine and restart policy: ~200 LOC.
- Health probing and metrics: ~150 LOC.
- Logs and metrics forwarding: ~150 LOC.
- Dev-mode runtime and watchdog integration: ~250 LOC.
- Configuration validation and secret redaction: ~100 LOC.

That totals roughly **800-1,200 LOC of supervisor/runtime implementation**, depending on factoring, plus **1,500-2,000 LOC of tests**. This is materially larger than ADR-0011's estimate and should land in multiple passes, not as one heroic PR.

## Implementation order

1. **Pass A — Protocol library.** Message envelope, framing, encode/decode, version negotiation, and error handling. No supervisor yet. Tests cover round-trip, malformed input, version mismatch, and `cancel-ack`.
2. **Pass B — Transports and `ConnectorContext`.** Define `ConnectorTransport`, implement `StdioTransport` and `InProcessTransport`, and wire the unified context. Tests use mock transports and verify author-visible behavior.
3. **Pass C — Supervisor and runner.** Add subprocess spawn, runner entry point, state machine, restart policy, health probing, cancellation escalation, and logs/metrics forwarding. This is the largest pass.
4. **Pass D — Dev runtime and CLI.** Add `prow connector dev`, watchdog reload, module eviction, stale-task cancellation, and documented reload limitations.

The CISA KEV connector should follow Pass D as the first real consumer. It can stay small while exercising the full runtime path: config validation, setup, fetch, awaited emit, state, logs, metrics, cancellation, and dev reload.

---

## References

- [ADR-0011 — Connector isolation model in monolith mode](../adr/ADR-0011-connector-isolation.md)
- [ADR-0003 — Modular monolith with split-ready seams](../04_DECISION_LOG.md#adr-0003--modular-monolith-with-split-ready-seams)
- [ADR-0008 — Connectors run as in-process tasks or worker pods](../04_DECISION_LOG.md#adr-0008--connectors-run-as-in-process-tasks-monolith-or-worker-pods-split)
- [Connector protocol design note](connector-protocol.md)
- [prow.stix wrapper design note](prow-stix-wrapper.md)
- [Connector SDK specification](../02_CONNECTOR_SDK.md)
- [Architecture §9 — Connector framework](../01_ARCHITECTURE.md#9-connector-framework--the-most-important-dx-surface)
