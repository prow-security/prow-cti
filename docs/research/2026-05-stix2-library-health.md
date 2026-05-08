# Upstream `stix2` (OASIS `cti-python-stix2`) — health memo

**Date:** 2026-05-07  
**Author:** Prow Maintainers  
**Status:** research memo, not a decision

Partial supersession (2026-05-07): The trigger conditions in the
Recommendation section are superseded by the [ADR-0009 amendment of
2026-05-07](../04_DECISION_LOG.md). The four operational
triggers in the amendment replace the duration-based triggers in
this memo. All other sections of this memo remain accurate as a
2026-05 research snapshot.

## TL;DR

- **PyPI shows a large historical gap, then a fresh release:** `stix2` **3.0.2** published **2026-02-12**, following **3.0.1** on **2021-09-24** (same major line). After **2026-02-12**, **GitHub reports no commits on `master` with timestamp after `2026-02-13T00:00:00Z`** as of this memo’s retrieval — signal is **bursty**, not monthly cadence.
- **Governance is alive but throughput is uneven:** listed maintainers and merge activity exist (recent merges include **2026-02-12**, **2026-02-09**, **2026-01-22**), while **`open_issues_count` was 66** and **open pull requests returned by the pulls API numbered 10** on retrieval — backlogs are material.
- **Recommendation:** **Option 2 — thick wrapper + fork readiness (not a fork today).** Treat ADR-0009’s *strategy* (wrap + validate against OASIS JSON schemas + contingency) as sound, but **replace “functionally inactive” prose with dated facts** from this memo.

## Findings

### Release cadence

| Version | First wheel/sdist `upload_time` (UTC) | Source |
|---:|---|---|
| **3.0.2** | **2026-02-12** | PyPI JSON API |
| **3.0.1** | **2021-09-24** | PyPI JSON API |
| **3.0.0** | **2021-07-13** | PyPI JSON API |
| **2.1.0** | **2020-11-20** | PyPI JSON API |
| **2.0.2** | **2020-07-07** | PyPI JSON API |

**Observation:** Latest release is **3.0.2** (`requires_python`: **`>=3.10`**); PyPI classifiers include **Python 3.12–3.14** on the project page JSON. **Interpretation:** **3.x is the current stable major line**, but **patch cadence was extremely slow across 2021–2025**, then **resumed in 2026**.

### Repository activity

**Observation (GitHub REST, retrieved 2026-05-07):**

- Default branch **`master`**; repository **`pushed_at`: `2026-02-12T06:21:36Z`**.
- **`updated_at` (repo metadata): `2026-04-27T03:05:51Z`** — reflects GitHub metadata churn, not necessarily code commits.
- Commit API **`since=2025-05-07`**: **14** commits returned (single page, `<100` commits — treated as complete list for that query).
- Commit API **`since=2026-02-07` (≈90 days before memo)**: **11** commits returned.
- Commit API **`since=2026-02-13`**: **[]** (empty array).

**Observation:** Latest merge visible in sampled history: **2026-02-12** (`Merge pull request #642…`). **Interpretation:** **Activity clustered around early 2026**, with **no subsequent commits on `master` after mid‑February through memo retrieval**.

### Issue and PR backlog

**Observation:**

- Repository **`open_issues_count`: 66** includes **PRs and issues** (GitHub’s aggregate).
- **GitHub Search API:** `is:issue is:open` in `oasis-open/cti-python-stix2` → **`total_count`: 56** (retrieved **2026-05-07**).
- **Open PRs** from pulls API (`state=open`, `per_page=100`): **10** (page not full → treated as complete count).

**Observation (six‑month “new open work”):** `is:open` + `created:>=2025-11-07` → **`total_count`: 0** (same API). **Interpretation:** **no new open item was created in the last ~six months of the memo date**; the backlog is **older work**, not a **fresh 2026 defect spike**.

**Sample — five open issues (not PRs), by `updated` desc** ([search query](https://api.github.com/search/issues?q=repo:oasis-open/cti-python-stix2+is:issue+is:open&sort=updated&order=desc&per_page=5)):

| # | Created (UTC) | Comments | Maintainer/owner response (public thread) |
|---:|---|---:|---|
| [639](https://github.com/oasis-open/cti-python-stix2/issues/639) | 2025-06-10 | 1 | **Yes** — **chisholm** on **2025-06-10** ([comment](https://github.com/oasis-open/cti-python-stix2/issues/639#issuecomment-2960718713)) |
| [637](https://github.com/oasis-open/cti-python-stix2/issues/637) | 2025-05-28 | 0 | **No** public comments as of API snapshot |
| [636](https://github.com/oasis-open/cti-python-stix2/issues/636) | 2025-04-25 | 2 | **Thread activity**; **not** fully triaged in this memo |
| [618](https://github.com/oasis-open/cti-python-stix2/issues/618) | 2025-02-06 | 0 | Filed by contributor **chisholm**; **no** follow‑up comments in API snapshot |
| [617](https://github.com/oasis-open/cti-python-stix2/issues/617) | 2024-12-18 | 2 | **Thread activity**; **not** fully triaged in this memo |

**Sample — three open PRs older than 90 days (memo date 2026‑05‑07 ⇒ cutoff 2026‑02‑07):**

| PR | Created | Last updated (UTC) | Notes |
|---:|---|---|---|
| [576](https://github.com/oasis-open/cti-python-stix2/pull/576) | 2023-10-25 | 2026-01-22 | Long‑running open PR |
| [624](https://github.com/oasis-open/cti-python-stix2/pull/624) | 2025-03-17 | 2026-01-19 | Maintainer thread **2025‑04‑09/10**; still **open** |
| [606](https://github.com/oasis-open/cti-python-stix2/pull/606) | 2024-10-13 | 2026-01-19 | Still **open** |

**Median time to merge (definition used):** among the **10 most recent merges** (`merged_at` descending) parsed from the first **300** closed PRs (`state=closed`, `sort=updated`, `direction=desc`, pages **1–3**), **median(open→merge) ≈ 0.45 days**. **Interpretation:** **when merges happen, they are often fast**; **stalls show up as aging open PRs**, not as median latency.

### STIX 2.1 spec coverage

**Observation:** PyPI long description (JSON `info.description`) states support relative to **STIX 2.1 CS03 / “OASIS Standard”** language as packaged text on **2026‑05‑07**. **Interpretation:** marketing text tracks **CS03-era framing**; **Errata 01 (April 2025)** is **not referenced** in that PyPI description snapshot.

**Observation:** GitHub search `repo:oasis-open/cti-python-stix2 errata` returned **one** hit whose title does **not** discuss Errata 01 (legacy STIX 2.0 cyber‑observable naming thread). **Interpretation:** **Errata 01 is not obviously tracked as a first‑class keyword** in public issues from that narrow search.

**Observation (architecture contrast):** prow plans **direct JSON Schema validation on ingest** against **`oasis-open/cti-stix2-json-schemas`**, separate from library validators — see **01_ARCHITECTURE.md** / SDK spec. **Interpretation:** **spec conformance for ingest can be enforced outside `stix2`**, while **`stix2` remains responsible for Python object ergonomics**.

### Ecosystem alternatives

**Observation (primary):** Filigran **OpenCTI client-python** declares **`stix2~=3.0.1`** ([`requirements.txt`](https://raw.githubusercontent.com/OpenCTI-Platform/client-python/master/requirements.txt), retrieved 2026‑05‑07). **Interpretation:** **major CTI tooling remains coupled to the PyPI `stix2` distribution line**, not an unrelated alternate implementation.

**Observation:** GitHub **`stargazers_count`** for **`oasis-open/cti-python-stix2`** was **421** on retrieval. **Interpretation:** **reference implementation retains broad visibility**; this does **not** prove maintenance velocity.

**Observation:** **`oasis-open/cti-stix2-json-schemas`** shows activity into **2026‑01‑19** on `master` (merge commit **`9af1db41b7b…`**, message includes **“update maintainers list”**). **`open_issues_count`** was **4** on retrieval. **Interpretation:** **schema repo backlog is smaller than the Python repo’s**, but **“healthy” still depends on Errata alignment work you track separately**.

### Dependency health

**Observation:** PyPI JSON for **`stix2`** includes **`"vulnerabilities": []`** (empty list) in the snapshot retrieved **2026‑05‑07**.

**Observation:** Runtime deps on **`stix2` 3.0.2** per PyPI metadata: **`pytz`**, **`requests`**, **`simplejson`**, **`stix2-patterns>=2.1.2`**.

**Observation:** **`pip-audit` was not executed in this environment** (module unavailable). **Interpretation:** **no primary pip‑audit report is attached**; rely on PyPI vulnerability metadata above plus your CI audit later.

**Observation:** **`requires_python`: `>=3.10`** for **3.0.2**; classifiers list **3.12–3.14**. **Interpretation:** **Python 3.12 is explicitly in scope** for current metadata.

## Risk assessment

| Risk | Severity | One‑line description |
|---|---|---|
| Spec drift vs emitted/consumed objects | **Medium** | Long gaps between releases increase odds that object semantics lag **Errata** or ecosystem expectations even if parse/emit “usually works”. |
| Need to absorb maintenance via fork | **Medium** | **Not imminent**, but **multi‑year release gaps** plus **non‑trivial open backlog** keep fork contingency realistic for a platform‑critical dependency. |
| Wrong abstraction target | **Low** | **No competing Python STIX 2.1 library** with comparable ecosystem embedding surfaced here; **`stix2` remains the practical primitive** for interoperability. |

## Recommendation

**Choose Option 2 — thick wrapper, plan for soft fork (do not fork now).**

**ADR‑0009 update (prose, not strategy):** replace **“functionally inactive”** / Snyk‑style shorthand with **dated facts**: **no PyPI release between `2021‑09‑24` and `2026‑02‑12`**, **post‑release commit quiet on `master` from `2026‑02‑13` through memo retrieval**, **non‑zero backlog** (**66** open issues / **10** open PRs counts from GitHub API on **2026‑05‑07**). **Keep** the **wrap + JSON Schema validation + fork contingency** strategy.

**Wrapper sizing:** plan **`~600–1000` LOC insurance surface** (ingress/egress shaping, error taxonomy, narrow helpers) consistent with Option 2 — **not** because upstream is “dead”, but because **release cadence has been historically sparse** and **prow’s correctness bar is schema‑first.

### Trigger conditions (Option 2 → Option 3)

All are **public, testable signals**:

1. **No new PyPI release for ≥24 consecutive months** *and* **at least one** of: **security defect** in `stix2` dependencies affecting prow, or **Python baseline incompatibility** (e.g., new Python **GA** without compatible wheels/sdist for pinned ranges).
2. **Zero merged PRs over ≥18 months** *while* **critical correctness issues** (spec mismatch proven against **`cti-stix2-json-schemas`**) remain **unaddressed** after **documented** outreach / contribution attempts.
3. **Repository archival** or **maintainer DECLINED merge rights** with **no substitute bus factor** on the OASIS Open Repository.

### If Option 3 were ever selected — maintenance commitments (visibility only)

- Track **`cti-stix2-json-schemas` Errata** releases and **pin/tag** schema bundles used by prow.
- **Release hygiene:** PyPI **`stix2` compatibility**, **security patching** for vendored/forked code paths.
- **Community triage:** issue/PR backlog for connectors consuming the fork — budget **maintainer FTE** explicitly.

## Open questions

- **Errata 01 gap list** inside **`stix2` 3.0.2** vs **`cti-stix2-json-schemas`** — requires a dedicated conformance matrix (not completed in this memo).
- **Vendor‑funded maintenance** behind IBM/CIRCL/Mitre maintainer time — **not inferable** from public GitHub alone.
- **Whether substantive external PRs merge reliably** — **empirical**: ship a small, non‑controversial docs PR and measure **time‑to‑first‑maintainer‑response** (proposal only).

## References

### PyPI

- https://pypi.org/pypi/stix2/json

### GitHub — `cti-python-stix2`

- https://github.com/oasis-open/cti-python-stix2
- https://api.github.com/repos/oasis-open/cti-python-stix2
- https://api.github.com/search/issues?q=repo:oasis-open/cti-python-stix2+is:issue+is:open&sort=updated&order=desc&per_page=5
- https://api.github.com/search/issues?q=repo:oasis-open/cti-python-stix2+is:open+created:%3E=2025-11-07
- https://api.github.com/repos/oasis-open/cti-python-stix2/commits?since=2025-05-07T00:00:00Z&per_page=100
- https://api.github.com/repos/oasis-open/cti-python-stix2/commits?since=2026-02-07T00:00:00Z&per_page=100
- https://api.github.com/repos/oasis-open/cti-python-stix2/commits?since=2026-02-13T00:00:00Z&per_page=10
- https://api.github.com/repos/oasis-open/cti-python-stix2/pulls?state=open&per_page=100&sort=updated&direction=desc
- https://api.github.com/repos/oasis-open/cti-python-stix2/issues?state=open&sort=created&direction=desc&per_page=5
- https://api.github.com/search/issues?q=repo:oasis-open/cti-python-stix2+errata&per_page=5
- https://github.com/oasis-open/cti-python-stix2/issues/639
- https://github.com/oasis-open/cti-python-stix2/issues/639#issuecomment-2960718713
- https://github.com/oasis-open/cti-python-stix2/pull/624

### GitHub — `cti-stix2-json-schemas`

- https://api.github.com/repos/oasis-open/cti-stix2-json-schemas
- https://api.github.com/repos/oasis-open/cti-stix2-json-schemas/commits/master?per_page=1

### Ecosystem

- https://raw.githubusercontent.com/OpenCTI-Platform/client-python/master/requirements.txt
