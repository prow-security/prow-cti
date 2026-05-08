# `tests/stix/fixtures/`

Hand-rolled fixtures and vendored OASIS examples for the
`prow.stix` test suite.

## `valid_indicator.json`

Hand-constructed minimal indicator used by `test_validator.py`. Pass A
landed this; the format intentionally mirrors what a connector would
emit so the validator and the Pydantic types share a single
known-good shape.

## `oasis_examples/`

Verbatim copies of the eight example bundles from the OASIS
`oasis-open/cti-stix2-json-schemas` repository at the same commit
SHA the schemas under `src/prow/stix/_schemas/` were vendored from
(`9af1db41b7b86c06324f899649ae83480134f66e`, vendored 2026-05-07).
Sources from upstream `examples/` plus the two longer bundles from
`examples/threat-reports/`.

`test_conformance.py` walks every file in this tree and exercises:

1. JSON Schema validation via `prow.stix.validate_stix_object`.
2. For every contained STIX object whose type is in the v0.1 prow
   modelled set, Pydantic round-trip via the matching type's
   `parse_external` + `model_dump_json` and a STIX-equivalence
   comparison against the original.

Examples may include STIX types prow does not yet model (e.g.
`course-of-action`, `infrastructure`); the per-object loop logs and
skips those entries explicitly so the conformance suite stays green
while pointing at exactly which types still need wrapper coverage.

License: BSD-3-Clause (the OASIS schema repo's `LICENSE` text is
copied verbatim into `src/prow/stix/_schemas/README.md`).

When re-vendoring schemas, also re-vendor these examples from the
same commit and inspect the diff for the conformance suite.
