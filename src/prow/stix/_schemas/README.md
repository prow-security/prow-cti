# Vendored OASIS STIX 2.1 JSON Schemas

**This directory is read-only at runtime and must not be edited by hand.**
It contains a verbatim snapshot of the OASIS STIX 2.1 JSON Schemas
consumed by `prow.stix._validate`. Hand-edits will break round-trip
refresh and silently diverge prow's validation behaviour from the
authoritative spec.

## Provenance

| Field | Value |
|-------|-------|
| Upstream repository | <https://github.com/oasis-open/cti-stix2-json-schemas> |
| Branch | `master` |
| Pinned commit | `9af1db41b7b86c06324f899649ae83480134f66e` |
| Upstream commit date | 2026-01-19 |
| Vendoring date | 2026-05-07 |
| STIX spec target | 2.1 (Errata 01, April 2025) |

The pinned commit and vendoring date are also recorded in `version.txt`
in machine-readable form. Both files are kept in lockstep; if one is
updated the other must be too.

### Layout deviation from the design note

The wrapper design note
(`docs/design/prow-stix-wrapper.md`) describes an aspirational layout
with `scos/`, `smos/`, and a top-level `bundle.json` under `2.1/`. The
upstream tree uses `common/`, `observables/`, `sdos/`, and `sros/` and
puts `bundle.json`, `marking-definition.json`, and `language-content.json`
under `common/`. Cross-file `$ref` values (e.g. `../common/core.json`)
in the upstream schemas are relative to the upstream paths. Renaming
or splitting directories would either silently break those references
or require modifying schema bodies, which is forbidden by the Pass A
constraints. We therefore preserve the upstream `schemas/` layout
verbatim under `2.1/`. The Pydantic types, validator, and helpers in
the wrapper consume schemas by their declared STIX `type` field, not
by directory, so this deviation has no effect on the public surface.

## License

The OASIS STIX 2.1 JSON Schemas are distributed under the BSD 3-Clause
License. The verbatim upstream `LICENSE` text follows.

```text
Copyright (c) [2016], OASIS Open
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Refresh procedure

A future maintainer re-vendoring against a newer OASIS commit follows
these steps. The `prow stix refresh-schemas` CLI command is planned
for v0.2 and will automate steps 2–5; until then the procedure is
manual.

1. **Identify the target.** Pick a commit on
   `oasis-open/cti-stix2-json-schemas` `master` that aligns with the
   current STIX 2.1 errata level prow is targeting. Record the full
   SHA and the commit's authored date.
2. **Replace the tree.** From a clean checkout of that upstream
   commit, copy the contents of the upstream `schemas/` directory into
   `src/prow/stix/_schemas/2.1/`, **deleting** any files that exist
   locally but not upstream first. Do not reformat, reorder, or
   "clean up" any JSON. Cross-file `$ref` values are relative to the
   upstream layout — preserve directory names verbatim.
3. **Update `version.txt`.** Two lines exactly:
   ```
   commit: <full upstream SHA>
   date: <ISO date you re-vendored, e.g. 2026-05-07>
   ```
4. **Update this README.** The provenance table, the spec target line
   if errata level changed, and the layout-deviation note if upstream
   restructured.
5. **Run the test suite.** `pytest -q tests/stix/` must pass. The
   schema discovery test will catch an unexpected file count change;
   investigate any delta and document it in the commit message.
6. **Note schema additions or removals in the commit message.** Any
   new or deleted schema files MUST be called out by name. Removed
   schemas may break downstream type imports in Pass B's `types.py`;
   added schemas surface new STIX types that may need wrapper coverage.
7. **Open a PR with the upstream commit URL** in the description so
   reviewers can diff against the GitHub source directly.

## What lives where

| Subdirectory | Contents |
|--------------|----------|
| `2.1/common/` | Shared definitions: `bundle`, `core`, `cyber-observable-core`, `marking-definition`, `language-content`, `extension-definition`, plus type primitives (`identifier`, `timestamp`, `hashes-type`, etc.). |
| `2.1/sdos/` | STIX Domain Objects (`indicator`, `malware`, `threat-actor`, etc.). |
| `2.1/observables/` | STIX Cyber-observable Objects (`ipv4-addr`, `domain-name`, `file`, etc.). |
| `2.1/sros/` | STIX Relationship Objects (`relationship`, `sighting`). |
