# ADR-0011 — Connector isolation model in monolith mode

**Status:** proposed  
**Date:** 2026-05-07  
**Supersedes:** nothing  
**Refines:** ADR-0003 (modular monolith with split-ready seams), ADR-0008 (connectors as in-process tasks vs worker pods)  
**Related:** [Connector SDK specification](../02_CONNECTOR_SDK.md)

## Context

ADR-0008 rejects container-per-connector overhead by committing to `asyncio` tasks in monolith mode and worker pods in split mode, with `ConnectorContext` hiding the difference. It leaves **failure isolation inside the monolith** unstated: connectors can block the loop (sync code or bad deps), pin CPU via native extensions, leak heap across runs, or crash the interpreter—all realistic. Sharing FastAPI’s process turns those into API outage or total process loss, not a localized ingest failure.

The SDK’s first PyPI-stable generation (~v0.2) is the point of no return: the isolation contract becomes ABI for external authors. “Tasks only,” without a boundary, promotes flaky connectors into platform incidents.

## Options

### Option A — Asyncio tasks in the API process

**Summary:** Connectors run as `asyncio` tasks in the FastAPI process; cancellation is cooperative (`asyncio.Event`, timeouts); no second process.

**What it means:** One address space, one event loop, one heap. The runtime schedules `fetch()` / `enrich()` work and applies timeouts around awaits, but cannot recover from a blocked loop except by escalating to process-level intervention anyway. Memory is shared; a leak in a connector leaks the API.

- **Isolation:** Weak—helps cooperative cancellation; **does not** contain blocking sync I/O, CPU-heavy native work, segfaults, or interpreter crashes.
- **Dev-loop speed:** Excellent—reload connector code and rerun on the order of hundreds of milliseconds.
- **Hot-reload:** Straightforward: reload module and reschedule tasks without spawning.
- **Observability:** Trivial—same logging pipeline and trace context as the API.
- **Resource cost (4 GB VPS):** Best—one RSS footprint; incremental cost per connector is mostly heap inside one process.
- **Split-mode path:** Strong story: today’s task becomes tomorrow’s pod; context stays abstract.
- **Cancellation semantics:** Cooperative—cancel means “stop awaiting at well-behaved points,” not “hard stop.”

### Option B — Subprocess per connector with JSON-line stdin/stdout protocol

**Summary:** Each connector **instance** runs as a child process; the runtime speaks a line-delimited JSON protocol over stdin/stdout for emits, logs, metrics, and state; lifecycle and crash recovery are supervisor responsibilities.

**What it means:** Connector authors still write idiomatic async Python against `ConnectorContext`, but production-mode context methods proxy across the boundary. The framework defines framing, back-pressure, and error envelopes.

- **Isolation:** Strong for crash and runaway CPU (kill/restart). Moderate for memory (process RSS bounded per connector; kernel accounts separately). Weak against malicious code—this is not a sandbox without seccomp/cgroups (explicitly out of scope for v0.1).
- **Dev-loop speed:** Poor if every save spawned a process—startup dominates.
- **Hot-reload:** Swap binary/process cheaply; **sub-second edit-run is not realistic** if subprocess is the only path.
- **Observability:** Structured logs and OTel spans must cross the boundary (additional pipes or side-channel); strictly more moving parts than Option A.
- **Resource cost (4 GB VPS):** Measurable—each child has baseline RSS (order tens of MB). Ten connectors × ~50 MB is ~500 MB before work—acceptable but not free; must be budgeted against Postgres and the API.
- **Split-mode path:** Excellent—the subprocess protocol is the same logical RPC split mode would send over NATS; swap transport, keep connector bytecode unchanged (ADR-0003’s seam test).
- **Cancellation semantics:** Strong—SIGTERM grace window, then SIGKILL; stronger than cooperative cancel, weaker than VM isolation.

### Option C — Multiprocessing pool with one connector per worker

**Summary:** A prow-owned supervisor keeps a pool of long-lived worker processes; connectors execute inside workers with IPC via queues or a shared-memory ring.

**What it means:** Amortizes process startup across runs of the same connector instance but couples scheduling to pool sizing and complicates fairness when many connectors share few workers.

- **Isolation:** Similar to B for crash containment within a worker; **weaker than B** when multiple connectors time-share a worker—one crash can evict unrelated connectors unless each worker is dedicated (collapsing toward B).
- **Dev-loop speed:** Middling—pool warm-up hides cold start but reload semantics get fuzzy (which worker holds stale code?).
- **Hot-reload:** Harder than A; comparable or worse than B depending on pool reuse strategy.
- **Observability:** Same boundary-crossing costs as B with extra correlation noise (which worker?).
- **Resource cost:** Better cold-start amortization than pure B; idle pool still burns RSS; fragmentation risk on small VPS.
- **Split-mode path:** Moderate—you still invent a worker protocol; mapping to pods is less direct than promoting B’s pipe protocol to NATS.
- **Cancellation semantics:** Worker kill/restart—strong if one connector per worker; muddy if pooled.

**Honest read:** Option C inherits much of B’s IPC cost without A’s dev speed or B’s clean per-process boundary.

## Decision

**Recommended:** **Option B for production monolith runs**, paired with **Option A restricted to `prow connector dev`** so the SDK keeps its sub-second save→run promise without pretending that tasks alone are production-safe.

The analysis supports the lean: Option A genuinely wins dev ergonomics and RSS; Option B genuinely wins containment and aligns with split mode (ADR-0003). Option C does not outperform both on any decisive axis for prow’s first SDK generation.

ADR-0008 remains valid: we still avoid Docker-per-connector for the solo VPS path. ADR-0011 makes explicit that **“in-process” applies only to the deliberate dev fast path**; production monolith uses **separate OS processes** with a stable protocol—still lighter operationally than a container per connector.

## Consequences

- **`02_CONNECTOR_SDK.md` / `ConnectorContext`:** In **production monolith** and **split**, context behaves like a **thin RPC client** (`emit`, state get/set, logs/metrics, HTTP helpers round-trip). **`prow connector dev`** uses **direct calls**. Serialize cleanly: `emit`, state, log/metrics paths, cancellation (`cancelled` ↔ channel semantics).
- **Author mental model:** Connector **source** stays one shape; **runtime wiring** swaps. Authors still never touch Postgres/NATS directly (existing prohibitions stand).
- **Serialization:** STIX bundles are JSON already—cheap on the wire. State values and log records need a versioned JSON envelope (type tag, schema version, connector/instance IDs). Tests pin compatibility.
- **Split-mode lift:** The subprocess JSONL protocol becomes the NATS-backed worker protocol with the same logical messages—connector packages unchanged (ADR-0003 seam preserved).
- **v0.1 cost:** A supervisor (spawn, watchdog, restart policy, protocol codec) is **real code**—expect **roughly 200–400 lines plus tests**, before observability polish.
- **Explicitly not in v0.1:** Graceful drain across long emits, cgroup-class per-connector limits, sandboxing, binary-level signing of connector wheels.

## Open questions

- **Protocol versioning** between runtime and connector subprocess (header on every line vs negotiated handshake once per spawn).
- **Dev vs prod implementation strategy:** single `ConnectorContext` implementation with pluggable transport vs a slim dev-only facade—impacts test matrix size.
- **Restart policy:** exponential backoff, max attempts, operator-visible circuit-break after N crashes.

## References

- ADR-0003 — Modular monolith with split-ready seams (`docs/04_DECISION_LOG.md`)
- ADR-0008 — Connectors run as in-process tasks (monolith) or worker pods (split) (`docs/04_DECISION_LOG.md`)
- ADR-0009 — Wrap the OASIS `stix2` library (`docs/04_DECISION_LOG.md`) — relevant because emitted bundles remain JSON-first on the wire
- `docs/02_CONNECTOR_SDK.md` — `ConnectorContext`, lifecycle hooks, connector prohibitions
