<!--
Copyright 2026 Prow Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
-->

# Upstream contributions

Tracks contributions prow has made or plans to make to dependency
projects. Each entry has: status, motivation, what we'd contribute,
and current state.

This file is part of how ADR-0009's "library health" position stays
operational — making upstream contributions is one signal of
ecosystem health, and tracking them keeps the signal visible.

---

## stix2 — `py.typed` marker

**Status:** planned
**Repo:** `oasis-open/cti-python-stix2`
**Last reviewed:** 2026-05-07

### Motivation

The `stix2` library does not ship a `py.typed` marker file per
[PEP 561](https://peps.python.org/pep-0561/). Without the marker,
mypy and other type checkers cannot consume any types the library
defines, even where stub-quality annotations exist in the source.

prow's `_stix2_adapter` carries two `# type: ignore[import-untyped]`
comments as a direct result. Adding the marker upstream removes
both ignores and improves type-checking for every downstream
consumer of stix2.

### What the contribution looks like

A small PR against `oasis-open/cti-python-stix2`:

1. Add an empty `py.typed` file inside the `stix2/` package
   directory.
2. Update `pyproject.toml` (or `setup.py`, depending on the
   project's build config at PR time) to include `py.typed` in the
   package data.
3. Add a one-line note to the changelog.

The change is mechanical and PEP 561-standard. No code, no behaviour
change.

### Why this is a good first upstream contribution

Per ADR-0009's amendment, one of the open questions is whether
upstream maintainers accept substantive PRs from prow contributors.
A small, mechanical, PEP-compliant PR is the cheapest possible test
of upstream responsiveness. The result informs whether the
soft-fork triggers in ADR-0009 should be tightened.

### Current state

- [ ] PR opened against upstream
- [ ] PR reviewed
- [ ] PR merged
- [ ] New stix2 release with the marker shipped to PyPI
- [ ] prow's `# type: ignore[import-untyped]` lines removed in a
      follow-up PR
- [ ] ADR-0009 amendment updated with the responsiveness signal

### Related

- `docs/04_DECISION_LOG.md` — ADR-0009 with 2026-05-07 amendment
- `docs/research/2026-05-stix2-library-health.md` — upstream health
  research
- `src/prow/stix/_stix2_adapter.py` — the two ignores this fixes
