# prow.stix wrapper — design note

**Date:** 2026-05-07  
**Status:** draft  
**Implements:** [ADR-0009](../04_DECISION_LOG.md) (2026-05-07 amendment)  
**Related:** [Connector SDK](../02_CONNECTOR_SDK.md) · [Architecture §6](../01_ARCHITECTURE.md#6-stix-21-mechanics)

---

## Amendments

**2026-05-07** — Pre-implementation maintainer decisions on Open Questions:

- `StixObject` discriminated union is **internal**. Public API exposes
  specific types; the union is used inside the wrapper for routing
  cases (the persister legitimately handles "any STIX object").
- TLP and well-known marking IDs live in `prow.stix.markings` as a
  constants module, not as string literals. TLP 2.0 constants only at
  v0.1; TLP 1.0 deferred until a connector needs legacy ingest.
- Custom STIX extensions are preserved as `extensions: dict[str, Any]`
  on round-trip. Typed models for specific tools (OpenCTI, MISP) only
  when a real connector requires reading specific fields.

**2026-05-07** — SCO deterministic ID computation in v0.1 delegates to
`stix2`'s utility via `_stix2_adapter.compute_sco_id`. Native prow-side
implementation deferred until a fork is required or until a contract
test against OASIS test vectors is in place.

**2026-05-07** — Schema vendoring uses upstream OASIS layout
(`common/`, `observables/`, `sdos/`, `sros/`) rather than the
design note's speculative layout. Schemas are referenced by STIX type
in code, not by filesystem path. See `_schemas/README.md` for details.

---

## Goals

- Provide **prow-owned STIX boundary types** (Pydantic v2) so **no package outside `prow.stix` imports `stix2` directly** — import-linter and package discipline enforce this; the adapter file is the sole bridge.
- **Validate every ingested STIX object** against **authoritative OASIS JSON Schemas** (STIX 2.1, Errata 01 target), vendored in-tree — not `stix2`’s bundled validators.
- Make **`bundle()`, `indicator()`, `url_observable()`, `relationship()`, and peers** match the ergonomics of the SDK examples so `ctx.emit(bundle([...]))` stays one obvious path for connector authors.
- Keep **fork-swap cost bounded** to roughly **one week** of focused work: non-adapter code unchanged when upstream is replaced (per ADR-0009 amendment).
- Establish a **performance baseline** for high-volume connectors (URLhaus-scale batches) so JSON Schema + construction stays off the hot-path flame graph’s top frame under normal batch sizes.

## Non-goals

- **Not** a full STIX 2.1 reference implementation or OASIS conformance certification. Prow consumes and emits STIX for interoperability; exhaustive clause-by-clause certification is out of scope.
- **Not** a graph query language, SQL dialect, or persistence layer — those belong to **`prow.db`** and related services.
- **Not** TAXII — that is **`prow.taxii`**; this module deals in STIX objects and bundles only.
- **Not** enrichment, deduplication, provenance merging, or storage. The wrapper outputs **validated, typed** STIX; the **ingestion pipeline** owns everything downstream.

## The boundary types

### Type taxonomy

Pydantic models are defined for each supported STIX category:

- **SDOs:** one model per supported type — e.g. `Indicator`, `Vulnerability`, `Malware`, `ThreatActor`, `Report`, `AttackPattern`, `Campaign`, `IntrusionSet`, `Tool`, and others as connectors require.
- **SCOs:** one model per supported observable type — e.g. `IPv4Address`, `IPv6Address`, `DomainName`, `Url`, `File`, `EmailAddr`, `Mutex`, `WindowsRegistryKey`, etc., grown iteratively with connectors.
- **SROs:** `Relationship`, `Sighting`.
- **SMOs / markings:** `MarkingDefinition`, `LanguageContent`, and granular marking objects as needed for TLP and statement markings.
- **Union:** a discriminated union **`StixObject`** keyed on the JSON **`type`** field using Pydantic’s **`Field(discriminator="type")`** pattern (exact API name per Pydantic v2 docs at implementation time).
- **`Bundle`:** wraps ordered **`objects`** with STIX bundle semantics.

Unsupported **`type`** values are rejected before model construction on ingest; connectors only emit types the SDK has shipped models for.

### Field strategy

- Fields **required by STIX 2.1** for a given type are **required** on the model.
- Spec-optional fields use **`Optional[...] = None`**.
- **Custom properties:** STIX allows vendor-specific keys on SDOs and SCOs. Every concrete model carries **`extensions: dict[str, Any] | None`** (name finalized at implementation; semantics = non-standard keys not lifted into first-class fields). Missing keys vs empty dict — implementation chooses one convention and applies it consistently in `model_dump`.
- **External references, granular markings, object markings:** modeled where the walking connectors need them; otherwise deferred to a later revision of `types.py`.

### Validation modes

Two layers serve different failures:

1. **Pydantic** — fast structural validation for Python-authored objects (correct types, required keys present). Catches connector bugs quickly.
2. **OASIS JSON Schema** — authoritative STIX shape and constraint checks for **external** data.

Operational rules:

| Path | JSON Schema | Pydantic |
|------|---------------|----------|
| Connector calls **`indicator(...)`** inside prow | No | Yes |
| Ingest from **TAXII**, **third-party JSON**, or untrusted feed paths | Yes | Yes |
| **Persistence read → API/TAXII emit** (already validated) | No | Yes (round-trip integrity) |

Re-validation with JSON Schema on every emit would **duplicate cost** without adding safety once objects are in the trusted store.

### Serialisation

- Default outward serialisation: **`model_dump(mode="json")`** with any extra config needed for STIX compatibility.
- **`datetime`** fields use a **custom serializer** so emitted timestamps are **ISO 8601**, **UTC**, **millisecond precision**, **`Z` suffix** — matching STIX examples. Pydantic’s default ISO format may differ; the implementation **must** pin the exact format in field serializers or model config.

## The validation flow

Ingest accepts **`bytes`**, **`str`**, or **`dict`**. Parse JSON if needed. Steps:

1. **Parse** to `dict` (or accept pre-parsed dict from callers that already decoded).
2. **Inspect `type`**. Unknown or missing → **fail fast** with a structured error (no schema disk read).
3. **JSON Schema validate** using the vendored schema for that type (bundle vs object entry paths documented in `validate.py`).
4. **Construct** the Pydantic model — narrows unions, parses enums, applies STIX-specific field formats schemas express loosely.
5. **Prow policy hooks** (same ingest path, after construction): TLP propagation rules, confidence bounds, **deterministic SCO IDs** where the spec defines them (`ids.py`). These are **platform rules**, not OASIS schema checks.

The wrapper **returns** typed objects (or bundle containers). It does **not** assign database IDs, merge duplicates, call enrichment APIs, or write storage — those stages live **after** `prow.stix` in the pipeline graph.

## The schema vendoring layout

Vendored artefacts ship inside **`prow.stix`** and load via **`importlib.resources`** (or equivalent) — **no network access at runtime**.

```text
src/prow/stix/
├── __init__.py
├── types.py              # Pydantic models
├── validate.py           # JSON Schema validation entry point
├── helpers.py            # bundle(), indicator(), url_observable(), etc.
├── ids.py                # SCO deterministic ID computation
├── _schemas/             # vendored OASIS schemas, read-only at runtime
│   ├── README.md         # provenance, version, refresh procedure
│   ├── 2.1/
│   │   ├── sdos/
│   │   ├── scos/
│   │   ├── sros/
│   │   ├── smos/
│   │   ├── common/
│   │   └── bundle.json
│   └── version.txt       # single line: source commit hash + date
└── _stix2_adapter.py     # the ONLY file allowed to import stix2
```

Underscore prefixes mark **internal implementation surfaces** — external code imports **`prow.stix`** public API only.

**Refresh:** `_schemas/README.md` records **upstream repo** (`oasis-open/cti-stix2-json-schemas`), **pinned commit**, **Errata level** (Errata 01 as current target), **vendoring date**, **maintainer**. CLI command **`prow stix refresh-schemas`** (planned **v0.2**) will re-copy trees and rewrite **`version.txt`** — out of scope for the first wrapper landing but documented here so vendoring is never tribal knowledge.

**Schema bundle:** Errata 01 (April 2025) is the **compatibility target** for validation; if OASIS tags releases, pin to a tag; otherwise pin to a commit hash on default branch that matches Errata alignment per upstream release notes.

## The fork-swap rehearsal

**Invariant:** **`from stix2 ...` appears only in `_stix2_adapter.py`.** A dedicated **import-linter contract** (extend `importlinter.ini`) forbids `stix2` anywhere under **`prow.stix`** except that file — CI fails otherwise.

**Adapter surface (illustrative names; ≤10 public functions):**

- `serialize_to_stix2_json(obj: StixObject | Bundle) -> dict`
- `parse_stix2_dict_to_prow(data: dict, *, trusted_author: bool) -> StixObject | Bundle`
- Possibly thin helpers for **Observable** vs **SDO** paths if `stix2` forces split entry points — kept minimal.

Behaviour is **mechanical translation** between prow models and `stix2` Python objects / dicts — **no business logic**, no HTTP, no DB.

**Guardrail test:** **`tests/test_fork_swap_surface.py`** introspects **`prow.stix._stix2_adapter`** `__all__` or a documented allow-list of callables and **`inspect.signature`** counts — any **new exported name** without updating the test allow-list **fails CI**. That forces an explicit design conversation when the adapter grows.

**Promise:** Replacing upstream means **rewriting one module**; **`types.py`**, **`validate.py`**, **`helpers.py`** stay stable unless STIX itself changes.

## Performance posture

JSON Schema validation dominates CPU for large batches — **dict validation** and **`Draft202012Validator`** (or faster backend) cost more than Pydantic construction for typical indicator-shaped payloads.

Mitigations:

- **Compile validators once per STIX type** at import (or lazy singleton registry first touch), **not per object**.
- Expose **`validate_many(objects: Sequence[dict])`** (and typed batch siblings) that **reuses** compiled validators and amortises overhead.
- **Target:** **10,000** `indicator` SDOs (minimal realistic fields + one URL SCO relationship path as fixture defines) **validated + constructed** in **under 5 seconds** on **one CPU core** in CI-class hardware — pinned in **`pytest`** as a performance assertion (margin allowed for CI variance; median over several runs if flaky).

If **`jsonschema`** cannot meet the budget after compilation and batching, **`fastjsonschema`** is **pre-approved** as a drop-in generation path from the same vendored schemas — **no second design review** required, only proof that outputs match `jsonschema` on the conformance corpus.

## Testing strategy

1. **Unit tests per type:** golden JSON fixture → JSON Schema → model → `model_dump` → compare to normalized expected (timestamps normalized). Round-trip preserves semantics.
2. **Conformance corpus:** every **OASIS example** shipped under the pinned schema repo revision that we vendor — run through ingest path. Failure = wrapper bug until proven otherwise.
3. **Fork-swap surface test:** described above — **adapter API freeze** via introspection.
4. **Performance test:** 10k-indicator budget on one core.

**Fixtures:** **`tests/stix/fixtures/`** — naming **`{stix_type}.json`** (STIX `type` field value, kebab-case filename). Plus **`bundle_realistic.json`** with interrelated SDOs/SCOs/SROs for integration smoke.

## Open questions

- **`StixObject` union visibility:** expose publicly vs keep internal — **default:** internal; public helpers take concrete types; ingest returns **`Bundle`** or typed sequences.
- **TLP well-known `marking-definition` IDs:** central **`constants.py`** vs inline strings — decision deferred; implementation picks one pattern.
- **OpenCTI / MISP custom extensions:** **`extensions`** dict holds opaque payloads until a connector needs typed extension models.

## Implementation order

1. **Vendor schemas + loader + compiled validators** — `_schemas/`, `version.txt`, `validate.py` registry.
2. **Pydantic types** for the **v0.1 / early connector set** (see scoped types below) — not the full spec day one.
3. **`helpers.py`** — `bundle`, `indicator`, `url_observable`, `relationship`, etc., aligned with SDK snippets.
4. **Fork-swap test + conformance harness + performance test.**

Then **CISA KEV** exercises the stack end-to-end; pipeline work wires validated bundles to persistence.

### v0.1 type scope (initial models)

Scoped for **CISA KEV** plus **v0.2 connectors** (URLhaus, MITRE ATT&CK, MISP) — **SDOs / SCOs / SROs** first pass:

| Area | Types (representative) |
|------|-------------------------|
| **KEV / vulns** | `vulnerability`, `indicator`, `relationship`, `malware`, `software` |
| **URLhaus (SDK example)** | `indicator`, `url`, `file`, `relationship` |
| **MITRE ATT&CK** | `attack-pattern`, `intrusion-set`, `malware`, `tool`, `campaign`, `relationship`, `marking-definition` (as needed) |
| **MISP** | Broad surface — start with **`indicator`**, **`observed-data`**, common **SCOs** (`ipv4-addr`, `domain-name`, `url`, `file`, `email-addr`), **`threat-actor`**, **`report`**, **`relationship`**; expand per connector tranche |

Additional types land **with** each connector tranche, not spec completeness upfront.

**Hand-waved for implementation discovery:** **Part 3 deterministic ID** algorithms for SCOs in **`ids.py`** — the STIX spec is precise; this note does not duplicate the prose — treat as **spec-tracing task** with golden vectors from OASIS examples.

---

## References

- [ADR-0009 (decision log)](../04_DECISION_LOG.md) — wrap `stix2`, OASIS JSON Schema validation, amendment **2026-05-07**
- [STIX upstream memo](../research/2026-05-stix2-library-health.md) — fork-risk context (partial supersession note applies to memo triggers)
- [OASIS STIX 2.1 JSON schemas](https://github.com/oasis-open/cti-stix2-json-schemas) — vendoring source
- [STIX 2.1 specification](https://docs.oasis-open.org/cti/stix/v2.1/stix-v2.1.html) — normative prose (Errata 01, April 2025)
